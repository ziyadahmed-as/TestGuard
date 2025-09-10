import uuid
import pandas as pd
from io import BytesIO
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.core.files.base import ContentFile
from core.models import User, Section, Institution, UserDeviceSession


class BulkQuestionImport(models.Model):
    """
    Manages bulk import operations for assessment questions from spreadsheet files.
    Provides tracking and auditing for large-scale question database population.
    """
    
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Processing'
        PROCESSING = 'PROCESSING', 'Processing in Progress'
        COMPLETED = 'COMPLETED', 'Successfully Completed'
        FAILED = 'FAILED', 'Processing Failed'
        PARTIAL = 'PARTIAL', 'Partial Success with Errors'

    uploaded_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='question_imports',
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        help_text="Instructor who initiated the question import operation"
    )
    question_bank = models.ForeignKey(
        'QuestionBank', 
        on_delete=models.CASCADE, 
        related_name='imports',
        help_text="Question bank where questions will be imported"
    )
    import_file = models.FileField(
        upload_to='question_imports/%Y/%m/%d/',
        help_text='Excel spreadsheet containing structured question data'
    )
    status = models.CharField(
        max_length=12, 
        choices=Status.choices, 
        default=Status.PENDING,
        help_text="Current processing status of the import operation"
    )
    total_records = models.PositiveIntegerField(
        default=0,
        help_text="Total number of question records identified in the import file"
    )
    successful_imports = models.PositiveIntegerField(
        default=0,
        help_text="Number of questions successfully created"
    )
    failed_imports = models.PositiveIntegerField(
        default=0,
        help_text="Number of questions that failed to import"
    )
    error_log = models.TextField(
        blank=True,
        help_text="Detailed error messages for failed import operations"
    )
    started_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Timestamp when processing commenced"
    )
    completed_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Timestamp when processing completed"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'uploaded_by']),
            models.Index(fields=['question_bank']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Bulk Question Import"
        verbose_name_plural = "Bulk Question Imports"

    def __str__(self):
        return f"Question Import #{self.id} for {self.question_bank.name} - {self.get_status_display()}"

    def process_import(self):
        """
        Execute the bulk question import process from the uploaded spreadsheet.
        Handles file parsing, validation, and question creation with comprehensive error handling.
        """
        self.status = self.Status.PROCESSING
        self.started_at = timezone.now()
        self.save()

        try:
            # Parse and process the Excel file
            df = pd.read_excel(self.import_file.path)
            self.total_records = len(df)
            
            success_count = 0
            errors = []
            
            for index, row in df.iterrows():
                try:
                    self._create_question_from_row(row)
                    success_count += 1
                except Exception as e:
                    errors.append(f"Row {index + 2}: {str(e)}")
            
            self.successful_imports = success_count
            self.failed_imports = len(errors)
            self.error_log = "\n".join(errors)
            
            # Determine final status based on processing results
            if errors:
                self.status = self.Status.PARTIAL if success_count > 0 else self.Status.FAILED
            else:
                self.status = self.Status.COMPLETED
                
        except Exception as e:
            self.status = self.Status.FAILED
            self.error_log = f"File processing error: {str(e)}"
        
        self.completed_at = timezone.now()
        self.save()

    def _create_question_from_row(self, row):
        """
        Create a question record from a single row of import data.
        
        Args:
            row (pandas.Series): Data row containing question information
            
        Raises:
            ValidationError: If required data is missing or invalid
        """
        question_text = str(row.get('question_text', '')).strip()
        if not question_text:
            raise ValidationError("Question text is required")
        
        question_type = str(row.get('type', Question.Type.MULTIPLE_CHOICE)).strip().upper()
        if question_type not in dict(Question.Type.choices):
            raise ValidationError(f"Invalid question type: {question_type}")
        
        points = float(row.get('points', 1.0))
        if points <= 0:
            raise ValidationError("Points must be greater than 0")
        
        question = Question(
            question_text=question_text,
            type=question_type,
            bank=self.question_bank,
            points=points,
            estimated_time=int(row.get('estimated_time', 60)),
            learning_objective=str(row.get('learning_objective', '')).strip(),
            created_by=self.uploaded_by,
            is_active=bool(row.get('is_active', True))
        )
        
        question.full_clean()
        question.save()
        
        return question

    @property
    def success_rate(self):
        """Calculate the percentage of successfully imported questions."""
        if self.total_records > 0:
            return (self.successful_imports / self.total_records) * 100
        return 0


class QuestionBank(models.Model):
    """
    Repository for organizing and managing assessment questions.
    Provides categorization and access control for question collections.
    """
    
    name = models.CharField(
        max_length=200,
        help_text="Descriptive name for the question bank"
    )
    institution = models.ForeignKey(
        Institution, 
        on_delete=models.CASCADE, 
        related_name='question_banks',
        help_text="Institution that owns this question bank"
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed description of the question bank's purpose and content"
    )
    is_global = models.BooleanField(
        default=False,
        help_text="Designates whether this question bank is available across the entire institution"
    )
    is_public = models.BooleanField(
        default=False,
        help_text="Designates whether this question bank is visible to all instructors"
    )
    created_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        related_name='created_banks',
        help_text="Instructor who created this question bank"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['institution', 'name']
        ordering = ['name']
        indexes = [
            models.Index(fields=['institution', 'is_global']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Question Bank"
        verbose_name_plural = "Question Banks"

    def __str__(self):
        return f"{self.name} ({self.institution.name})"

    def get_import_template(self):
        """
        Generate a standardized Excel template for bulk question imports.
        
        Returns:
            ContentFile: Excel file containing template structure
        """
        template_data = {
            'question_text': ['Sample multiple choice question?'],
            'type': ['MC'],
            'points': [1.0],
            'estimated_time': [60],
            'learning_objective': ['Understand basic concepts'],
            'is_active': [True]
        }
        
        df = pd.DataFrame(template_data)
        output = BytesIO()
        df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        
        return ContentFile(output.read(), name=f'{self.name}_import_template.xlsx')

    @property
    def active_questions_count(self):
        """Return the number of active questions in this bank."""
        return self.questions.filter(is_active=True).count()


class Question(models.Model):
    """
    Base assessment question model supporting multiple question types.
    Provides foundation for various assessment formats and evaluation methods.
    """
    
    class Type(models.TextChoices):
        MULTIPLE_CHOICE = 'MC', 'Multiple Choice'
        TRUE_FALSE = 'TF', 'True/False'
        FILL_BLANK = 'FB', 'Fill-in-the-Blank'
        SHORT_ANSWER = 'SA', 'Short Answer'
        ESSAY = 'ES', 'Essay'

    question_text = models.TextField(
        help_text="Full text of the assessment question"
    )
    type = models.CharField(
        max_length=4, 
        choices=Type.choices,
        help_text="Type of question determining response format and evaluation method"
    )
    bank = models.ForeignKey(
        QuestionBank, 
        on_delete=models.CASCADE, 
        related_name='questions',
        help_text="Question bank containing this question"
    )
    learning_objective = models.CharField(
        max_length=300, 
        blank=True,
        help_text="Specific learning objective addressed by this question"
    )
    points = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=1.00,
        validators=[MinValueValidator(0.01)],
        help_text="Point value awarded for correct response"
    )
    estimated_time = models.PositiveIntegerField(
        default=60,
        help_text="Estimated time in seconds required to complete this question"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this question is available for use in assessments"
    )
    created_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='created_questions',
        help_text="Instructor who created this question"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['type', 'is_active']),
            models.Index(fields=['bank', 'is_active']),
            models.Index(fields=['created_by', 'is_active']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Question"
        verbose_name_plural = "Questions"

    def __str__(self):
        return f"{self.get_type_display()}: {self.question_text[:100]}..."

    def clean(self):
        """Validate question data integrity and institutional consistency."""
        if self.bank.institution != self.created_by.institution:
            raise ValidationError("Question bank and creator must belong to the same institution.")

    @property
    def requires_manual_grading(self):
        """Determine if this question type requires manual evaluation."""
        return self.type in [self.Type.SHORT_ANSWER, self.Type.ESSAY]


class Exam(models.Model):
    """
    Comprehensive exam definition and configuration model.
    Manages assessment settings, scheduling, security, and access controls.
    """
    
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        LIVE = 'LIVE', 'Live'
        COMPLETED = 'COMPLETED', 'Completed'
        ARCHIVED = 'ARCHIVED', 'Archived'

    title = models.CharField(
        max_length=255,
        help_text="Descriptive title of the exam"
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed description of the exam's purpose and content"
    )
    instructions = models.TextField(
        help_text="Complete instructions for exam takers"
    )
    status = models.CharField(
        max_length=10, 
        choices=Status.choices, 
        default=Status.DRAFT,
        help_text="Current lifecycle status of the exam"
    )
    duration = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Total allowed time for exam completion in minutes"
    )
    max_attempts = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Maximum number of attempts allowed per student"
    )
    pass_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=35.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Minimum score percentage required to pass the exam"
    )
    
    # Exam Security
    exam_password = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional password required for exam access"
    )
    
    # Scheduling
    start_date = models.DateTimeField(
        help_text="Date and time when the exam becomes available"
    )
    end_date = models.DateTimeField(
        help_text="Date and time when the exam becomes unavailable"
    )
    time_zone = models.CharField(
        max_length=50, 
        default='UTC',
        help_text="Time zone for exam scheduling"
    )
    
    # Security Settings
    shuffle_questions = models.BooleanField(
        default=False,
        help_text="Randomize question order for each attempt"
    )
    shuffle_answers = models.BooleanField(
        default=False,
        help_text="Randomize answer choices for multiple choice questions"
    )
    disable_copy_paste = models.BooleanField(
        default=True,
        help_text="Prevent copy-paste operations during exam"
    )
    full_screen_required = models.BooleanField(
        default=False,
        help_text="Require full-screen mode for exam duration"
    )
    require_webcam = models.BooleanField(
        default=False,
        help_text="Require webcam access for proctoring"
    )
    allow_backtracking = models.BooleanField(
        default=True,
        help_text="Allow returning to previous questions"
    )
    enable_auto_save = models.BooleanField(
        default=True,
        help_text="Automatically save progress during exam"
    )
    
    created_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        related_name='created_exams',
        help_text="Instructor who created this exam"
    )
    sections = models.ManyToManyField(
        Section, 
        related_name='exams',
        help_text="Course sections with access to this exam"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_by']),
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Exam"
        verbose_name_plural = "Exams"

    def __str__(self):
        return self.title

    @property
    def is_active(self):
        """
        Determine if exam is currently available based on schedule and status.
        
        Returns:
            bool: True if exam is live and within scheduled timeframe
        """
        now = timezone.now()
        return (self.status == self.Status.LIVE and 
                self.start_date <= now <= self.end_date)

    @property
    def requires_password(self):
        """
        Check if exam requires password authentication.
        
        Returns:
            bool: True if exam password is set and not empty
        """
        return bool(self.exam_password.strip())

    def validate_password(self, password_attempt):
        """
        Validate provided exam password against stored value.
        
        Args:
            password_attempt (str): Password provided by user
            
        Returns:
            bool: True if password matches or no password required
        """
        if not self.requires_password:
            return True
        return self.exam_password == password_attempt

    def clean(self):
        """Validate exam configuration integrity and scheduling logic."""
        if self.start_date >= self.end_date:
            raise ValidationError("Exam end date must be after start date.")
        
        if self.pass_percentage > 100:
            raise ValidationError("Pass percentage cannot exceed 100%.")

    @property
    def total_points(self):
        """Calculate total possible points for the exam."""
        return sum(
            eq.points for eq in self.exam_questions.select_related('question').all()
        )


class ExamQuestion(models.Model):
    """
    Through model managing question inclusion and customization within exams.
    Provides ordering and point override capabilities for exam questions.
    """
    
    exam = models.ForeignKey(
        Exam, 
        on_delete=models.CASCADE, 
        related_name='exam_questions',
        help_text="Exam containing this question"
    )
    question = models.ForeignKey(
        Question, 
        on_delete=models.CASCADE, 
        related_name='exam_usage',
        help_text="Question being included in the exam"
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order within the exam sequence"
    )
    points = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        help_text="Point value for this question within the exam (overrides default)"
    )

    class Meta:
        ordering = ['order']
        unique_together = ['exam', 'question']
        indexes = [
            models.Index(fields=['exam', 'order']),
        ]
        verbose_name = "Exam Question"
        verbose_name_plural = "Exam Questions"

    def __str__(self):
        return f"{self.exam.title} - Question {self.order}"

    def clean(self):
        """Validate question point value integrity."""
        if self.points <= 0:
            raise ValidationError("Question points must be greater than zero.")


class ExamAttempt(models.Model):
    """
    Tracks individual student attempts at exams with comprehensive monitoring.
    Manages timing, device security, and attempt lifecycle.
    """
    
    class Status(models.TextChoices):
        NOT_STARTED = 'NOT_STARTED', 'Not Started'
        PASSWORD_REQUIRED = 'PASSWORD_REQUIRED', 'Password Required'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        SUBMITTED = 'SUBMITTED', 'Submitted'
        AUTO_SUBMITTED = 'AUTO_SUBMITTED', 'Auto-Submitted'
        TERMINATED = 'TERMINATED', 'Terminated'

    exam = models.ForeignKey(
        Exam, 
        on_delete=models.CASCADE, 
        related_name='attempts',
        help_text="Exam being attempted"
    )
    student = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.STUDENT},
        related_name='exam_attempts',
        help_text="Student attempting the exam"
    )
    start_time = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Timestamp when the attempt commenced"
    )
    end_time = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Timestamp when the attempt concluded"
    )
    status = models.CharField(
        max_length=20, 
        choices=Status.choices, 
        default=Status.NOT_STARTED,
        help_text="Current status of the exam attempt"
    )
    ip_address = models.GenericIPAddressField(
        null=True, 
        blank=True,
        help_text="IP address from which the attempt was initiated"
    )
    technical_notes = models.JSONField(
        default=dict,
        help_text="Technical metadata and system notes for the attempt"
    )
    
    # Device session tracking
    device_session = models.ForeignKey(
        UserDeviceSession, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='exam_attempts',
        help_text="Device session used for this attempt"
    )
    session_token = models.UUIDField(
        null=True, 
        blank=True,
        help_text="Unique identifier for this attempt session"
    )
    termination_reason = models.CharField(
        max_length=200, 
        blank=True,
        help_text="Reason for attempt termination if applicable"
    )
    
    # Auto-save metadata
    last_auto_save = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Timestamp of most recent auto-save operation"
    )
    auto_save_count = models.PositiveIntegerField(
        default=0,
        help_text="Total number of auto-save operations performed"
    )

    # Password attempt tracking
    password_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Number of unsuccessful password attempts"
    )
    last_password_attempt = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Timestamp of most recent password attempt"
    )

    class Meta:
        unique_together = ['exam', 'student']
        ordering = ['-start_time']
        indexes = [
            models.Index(fields=['exam', 'student', 'status']),
            models.Index(fields=['student', 'status']),
            models.Index(fields=['device_session']),
            models.Index(fields=['session_token']),
            models.Index(fields=['start_time']),
        ]
        verbose_name = "Exam Attempt"
        verbose_name_plural = "Exam Attempts"

    def __str__(self):
        return f"{self.student.email} - {self.exam.title} - {self.get_status_display()}"

    def clean(self):
        """Validate attempt integrity and prevent multiple active sessions."""
        if self.status == self.Status.IN_PROGRESS and self.device_session:
            # Check for existing active sessions for this user+exam
            active_sessions = ActiveExamSession.objects.filter(
                user=self.student, 
                exam=self.exam, 
                is_active=True
            ).exclude(attempt=self)
            
            if active_sessions.exists():
                other_session = active_sessions.first()
                raise ValidationError(
                    f"Active exam session already exists started at "
                    f"{other_session.started_at.strftime('%Y-%m-%d %H:%M')}"
                )

    def start_exam(self, device_session, password_attempt=None):
        """
        Initiate exam attempt with password validation and device registration.
        
        Args:
            device_session (UserDeviceSession): Validated device session
            password_attempt (str, optional): Password for exam access
            
        Returns:
            tuple: (success: bool, message: str)
        """
        if self.exam.requires_password:
            if not password_attempt:
                self.status = self.Status.PASSWORD_REQUIRED
                self.save()
                return False, "Password required to start exam"
            
            if not self.exam.validate_password(password_attempt):
                self.password_attempts += 1
                self.last_password_attempt = timezone.now()
                self.save()
                return False, "Incorrect exam password"
        
        # Password validated or not required - start exam
        self.status = self.Status.IN_PROGRESS
        self.start_time = timezone.now()
        self.device_session = device_session
        self.session_token = uuid.uuid4()
        self.save()
        return True, "Exam started successfully"

    def terminate_session(self, reason="Multiple device access detected"):
        """
        Terminate exam attempt due to policy violation or system action.
        
        Args:
            reason (str): Explanation for termination
        """
        self.status = self.Status.TERMINATED
        self.termination_reason = reason
        self.end_time = timezone.now()
        self.save()
        
        # Deactivate any active session
        ActiveExamSession.objects.filter(
            user=self.student, 
            exam=self.exam, 
            is_active=True
        ).update(is_active=False)

    def can_access_from_device(self, device_hash):
        """
        Validate device authorization for attempt access.
        
        Args:
            device_hash (str): Device fingerprint hash to validate
            
        Returns:
            bool: True if device is authorized for access
        """
        if not self.device_session:
            return True
            
        return (self.status != self.Status.IN_PROGRESS or 
                self.device_session.device_hash == device_hash)

    @property
    def duration(self):
        """
        Calculate total attempt duration in minutes.
        
        Returns:
            float: Duration in minutes or None if not completed
        """
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() / 60
        return None

    @property
    def time_remaining(self):
        """
        Calculate remaining time for in-progress attempts.
        
        Returns:
            float: Remaining time in seconds or 0 if not in progress
        """
        if self.status == self.Status.IN_PROGRESS and self.start_time:
            elapsed = (timezone.now() - self.start_time).total_seconds()
            remaining = (self.exam.duration * 60) - elapsed
            return max(0, remaining)
        return 0

    @property
    def requires_password_input(self):
        """
        Check if attempt currently requires password entry.
        
        Returns:
            bool: True if password input is required
        """
        return (self.status == self.Status.PASSWORD_REQUIRED or 
                (self.status == self.Status.NOT_STARTED and self.exam.requires_password))

    @property
    def is_completed(self):
        """Check if attempt has reached a final state."""
        return self.status in [
            self.Status.SUBMITTED, 
            self.Status.AUTO_SUBMITTED, 
            self.Status.TERMINATED
        ]


class QuestionResponse(models.Model):
    """
    Stores student responses with real-time auto-save and versioning capabilities.
    Manages both draft and final answer states for comprehensive response tracking.
    """
    
    attempt = models.ForeignKey(
        ExamAttempt, 
        on_delete=models.CASCADE, 
        related_name='responses',
        help_text="Exam attempt containing this response"
    )
    question = models.ForeignKey(
        Question, 
        on_delete=models.CASCADE,
        help_text="Question being responded to"
    )
    student_answer = models.JSONField(
        null=True, 
        blank=True,
        help_text="Final submitted answer data"
    )
    draft_answer = models.JSONField(
        null=True, 
        blank=True, 
        help_text="Temporary draft answer storage for auto-save functionality"
    )
    points_awarded = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Points awarded for this response after evaluation"
    )
    auto_save_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of auto-save operations performed for this response"
    )
    last_auto_save = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Timestamp of most recent auto-save operation"
    )
    is_submitted = models.BooleanField(
        default=False,
        help_text="Designates whether this response has been formally submitted"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['attempt', 'question']
        indexes = [
            models.Index(fields=['attempt', 'question']),
            models.Index(fields=['last_auto_save']),
            models.Index(fields=['created_at']),
        ]
        ordering = ['created_at']
        verbose_name = "Question Response"
        verbose_name_plural = "Question Responses"

    def __str__(self):
        return f"Response for {self.question} by {self.attempt.student}"

    def save_draft(self, answer_data):
        """
        Save draft answer with auto-save metadata tracking.
        
        Args:
            answer_data: Response data to save as draft
        """
        self.draft_answer = answer_data
        self.auto_save_count += 1
        self.last_auto_save = timezone.now()
        self.save(update_fields=[
            'draft_answer', 'auto_save_count', 'last_auto_save', 'updated_at'
        ])

    def finalize_answer(self, answer_data):
        """
        Finalize answer submission and clear draft state.
        
        Args:
            answer_data: Final response data to submit
        """
        self.student_answer = answer_data
        self.draft_answer = None
        self.is_submitted = True
        self.save(update_fields=[
            'student_answer', 'draft_answer', 'is_submitted', 'updated_at'
        ])

    @property
    def has_draft(self):
        """Check if response has unsaved draft data."""
        return self.draft_answer is not None

    @property
    def is_graded(self):
        """Check if response has been evaluated and scored."""
        return self.points_awarded is not None


class MonitoringEvent(models.Model):
    """
    Tracks security and proctoring events during exam attempts.
    Provides comprehensive monitoring for academic integrity enforcement.
    """
    
    class EventType(models.TextChoices):
        TAB_SWITCH = 'TAB_SWITCH', 'Tab Switch Detected'
        COPY_PASTE = 'COPY_PASTE', 'Copy/Paste Detected'
        FULLSCREEN_EXIT = 'FULLSCREEN_EXIT', 'Fullscreen Exit'
        MULTIPLE_FACES = 'MULTIPLE_FACES', 'Multiple Faces Detected'
        NO_FACE = 'NO_FACE', 'No Face Detected'
        VOICE_DETECTED = 'VOICE_DETECTED', 'Voice Detected'
        MANUAL_FLAG = 'MANUAL_FLAG', 'Manually Flagged'
        DEVICE_MISMATCH = 'DEVICE_MISMATCH', 'Device Mismatch'
        PASSWORD_BRUTE_FORCE = 'PASSWORD_BRUTE_FORCE', 'Multiple Password Attempts'

    class ReviewedStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending Review'
        REVIEWING = 'REVIEWING', 'Under Review'
        APPROVED = 'APPROVED', 'Approved - No Issue'
        VIOLATION = 'VIOLATION', 'Violation Confirmed'
        FALSE_ALARM = 'FALSE_ALARM', 'False Alarm'

    attempt = models.ForeignKey(
        ExamAttempt, 
        on_delete=models.CASCADE, 
        related_name='monitoring_events',
        help_text="Exam attempt where event occurred"
    )
    event_type = models.CharField(
        max_length=20, 
        choices=EventType.choices,
        help_text="Type of monitoring event detected"
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        help_text="Exact time when event was detected"
    )
    severity = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Severity level from 1 (low) to 10 (critical)"
    )
    evidence = models.JSONField(
        default=dict,
        help_text="Supporting evidence and contextual data for the event"
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed description of the event circumstances"
    )
    reviewed_status = models.CharField(
        max_length=12, 
        choices=ReviewedStatus.choices, 
        default=ReviewedStatus.PENDING,
        help_text="Current review status of the event"
    )
    reviewed_by = models.ForeignKey(
        User, 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL,
        limit_choices_to={'role__in': [User.Role.ADMIN, User.Role.INSTRUCTOR]},
        help_text="Staff member who reviewed this event"
    )
    reviewed_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Timestamp when event was reviewed"
    )
    review_notes = models.TextField(
        blank=True,
        help_text="Notes and observations from the review process"
    )
    action_taken = models.TextField(
        blank=True, 
        help_text="Actions taken based on this event assessment"
    )

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['attempt', 'event_type', 'reviewed_status']),
            models.Index(fields=['timestamp']),
            models.Index(fields=['reviewed_status']),
            models.Index(fields=['severity']),
        ]
        verbose_name = "Monitoring Event"
        verbose_name_plural = "Monitoring Events"

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.attempt}"

    def assign_for_review(self, assigned_to):
        """
        Assign event for review to designated staff member.
        
        Args:
            assigned_to (User): Staff member responsible for review
        """
        self.reviewed_status = self.ReviewedStatus.REVIEWING
        self.reviewed_by = assigned_to
        self.save(update_fields=['reviewed_status', 'reviewed_by'])

    def complete_review(self, status, notes="", action_taken=""):
        """
        Complete event review with final assessment and actions.
        
        Args:
            status (str): Final review status
            notes (str): Review notes and observations
            action_taken (str): Actions implemented based on review
        """
        self.reviewed_status = status
        self.review_notes = notes
        self.action_taken = action_taken
        self.reviewed_at = timezone.now()
        self.save(update_fields=[
            'reviewed_status', 'review_notes', 'action_taken', 'reviewed_at'
        ])

    @property
    def requires_immediate_attention(self):
        """Check if event severity warrants immediate action."""
        return self.severity >= 8

    @property
    def is_resolved(self):
        """Check if event has been fully reviewed and addressed."""
        return self.reviewed_status in [
            self.ReviewedStatus.APPROVED,
            self.ReviewedStatus.VIOLATION,
            self.ReviewedStatus.FALSE_ALARM
        ]


class ActiveExamSession(models.Model):
    """
    Tracks currently active exam sessions for monitoring and security purposes.
    Provides real-time visibility into ongoing exam attempts.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='exam_active_sessions',  # Ensure unique
        help_text="User participating in the exam session"
    )
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name='exam_active_sessions',  # Ensure unique
        help_text="Exam associated with this active session"
    )
    attempt = models.OneToOneField(
        ExamAttempt,
        on_delete=models.CASCADE,
        related_name='exam_active_session',  # Ensure unique
        help_text="Specific exam attempt associated with this session"
    )
    device_session = models.ForeignKey(
        UserDeviceSession,
        on_delete=models.CASCADE,
        related_name='active_exam_sessions',
        help_text="Device session used for this exam attempt"
    )
    session_token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for this active session"
    )
    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the session started"
    )
    last_activity = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of the last activity in this session"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Indicates whether this session is currently active"
    )
    risk_level = models.CharField(
        max_length=10,
        choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        default='low',
        help_text="Current risk level assessment for this session"
    )

    class Meta:
        unique_together = ['user', 'exam']
        indexes = [
            models.Index(fields=['user', 'exam']),
            models.Index(fields=['session_token']),
            models.Index(fields=['is_active']),
            models.Index(fields=['risk_level']),
        ]
        verbose_name = "Active Exam Session"
        verbose_name_plural = "Active Exam Sessions"

    def __str__(self):
        return f"Active session: {self.user.username} - {self.exam.title}"

    @property
    def duration(self):
        """Calculate the duration of the active session in minutes."""
        return (timezone.now() - self.started_at).total_seconds() / 60

    def update_risk_level(self, new_risk_level):
        """
        Update the risk level for this session.
        
        Args:
            new_risk_level (str): New risk level ('low', 'medium', 'high')
        """
        if new_risk_level in ['low', 'medium', 'high']:
            self.risk_level = new_risk_level
            self.save(update_fields=['risk_level'])

    def deactivate(self):
        """Deactivate this session."""
        self.is_active = False
        self.save(update_fields=['is_active'])


# Signal Handlers for Automated System Management
@receiver(pre_save, sender=ExamAttempt)
def validate_single_device_access(sender, instance, **kwargs):
    """
    Prevent multiple device access for the same exam attempt.
    Ensures concurrency control integrity before attempt persistence.
    """
    if instance.status == ExamAttempt.Status.IN_PROGRESS:
        instance.clean()


@receiver(post_save, sender=ExamAttempt)
def manage_active_sessions(sender, instance, created, **kwargs):
    """
    Manage active exam sessions when attempt status changes.
    Synchronizes session state with attempt lifecycle events.
    """
    if instance.status == ExamAttempt.Status.IN_PROGRESS and instance.device_session:
        # Create or update active session
        ActiveExamSession.objects.update_or_create(
            user=instance.student,
            exam=instance.exam,
            defaults={
                'device_session': instance.device_session,
                'attempt': instance,
                'session_token': instance.session_token or uuid.uuid4(),
                'is_active': True,
                'last_activity': timezone.now()
            }
        )
    elif instance.status in [ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.TERMINATED]:
        # Deactivate session on completion or termination
        ActiveExamSession.objects.filter(
            user=instance.student,
            exam=instance.exam
        ).update(is_active=False)