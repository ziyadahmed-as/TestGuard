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
from core.models import User, Section, Institution, UserDeviceSession, ActiveExamSession

class BulkQuestionImport(models.Model):
    """Tracks bulk question import operations by instructors."""
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
        PARTIAL = 'PARTIAL', 'Partial Success'

    uploaded_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='question_imports',
        limit_choices_to={'role': User.Role.INSTRUCTOR}
    )
    question_bank = models.ForeignKey(
        'QuestionBank', 
        on_delete=models.CASCADE, 
        related_name='imports'
    )
    import_file = models.FileField(
        upload_to='question_imports/%Y/%m/%d/',
        help_text='Excel file containing question data'
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    total_records = models.PositiveIntegerField(default=0)
    successful_imports = models.PositiveIntegerField(default=0)
    failed_imports = models.PositiveIntegerField(default=0)
    error_log = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'uploaded_by']),
            models.Index(fields=['question_bank']),
        ]

    def __str__(self):
        return f"Question Import #{self.id} for {self.question_bank.name}"

    def process_import(self):
        """Process the bulk question import file."""
        self.status = self.Status.PROCESSING
        self.started_at = timezone.now()
        self.save()

        try:
            # Read the Excel file
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
        """Create a question from a single row of import data."""
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

class QuestionBank(models.Model):
    """Repository for assessment questions."""
    name = models.CharField(max_length=200)
    institution = models.ForeignKey(
        Institution, 
        on_delete=models.CASCADE, 
        related_name='question_banks'
    )
    description = models.TextField(blank=True)
    is_global = models.BooleanField(
        default=False,
        help_text="Available across institution"
    )
    is_public = models.BooleanField(
        default=False,
        help_text="Visible to all instructors"
    )
    created_by = models.ForeignKey(
        User, 
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        on_delete=models.CASCADE, 
        related_name='created_banks'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['institution', 'name']
        ordering = ['name']
        indexes = [
            models.Index(fields=['institution', 'is_global']),
        ]

    def __str__(self):
        return f"{self.name} ({self.institution.name})"

    def get_import_template(self):
        """Generate a template Excel file for bulk question import."""
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

class Question(models.Model):
    """Base question model supporting multiple question types."""
    class Type(models.TextChoices):
        MULTIPLE_CHOICE = 'MC', 'Multiple Choice'
        TRUE_FALSE = 'TF', 'True/False'
        FILL_BLANK = 'FB', 'Fill-in-the-Blank'
        SHORT_ANSWER = 'SA', 'Short Answer'
        ESSAY = 'ES', 'Essay'

    question_text = models.TextField()
    type = models.CharField(max_length=4, choices=Type.choices)
    bank = models.ForeignKey(
        QuestionBank, 
        on_delete=models.CASCADE, 
        related_name='questions'
    )
    learning_objective = models.CharField(max_length=300, blank=True)
    points = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=1.00,
        validators=[MinValueValidator(0.01)]
    )
    estimated_time = models.PositiveIntegerField(
        help_text="Estimated seconds to complete", 
        default=60
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='created_questions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['type', 'is_active']),
            models.Index(fields=['bank', 'is_active']),
            models.Index(fields=['created_by', 'is_active']),
        ]

    def __str__(self):
        return f"{self.get_type_display()}: {self.question_text[:100]}..."

    def clean(self):
        """Validate question data."""
        if self.bank.institution != self.created_by.institution:
            raise ValidationError("Question bank and creator must belong to the same institution.")

class Exam(models.Model):
    """Exam definition and configuration."""
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        LIVE = 'LIVE', 'Live'
        COMPLETED = 'COMPLETED', 'Completed'
        ARCHIVED = 'ARCHIVED', 'Archived'

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    instructions = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    duration = models.PositiveIntegerField(
        help_text="Duration in minutes",
        validators=[MinValueValidator(1)]
    )
    max_attempts = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)]
    )
    pass_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=35.00,  # Reduced from 60.00 to 35.00
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Exam Password Field
    exam_password = models.CharField(
        max_length=100,
        blank=True,
        help_text="Password required for students to start the exam. Leave blank for no password."
    )
    
    # Scheduling
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    time_zone = models.CharField(max_length=50, default='UTC')
    
    # Security Settings
    shuffle_questions = models.BooleanField(default=False)
    shuffle_answers = models.BooleanField(default=False)
    disable_copy_paste = models.BooleanField(default=True)
    full_screen_required = models.BooleanField(default=False)
    require_webcam = models.BooleanField(default=False)
    allow_backtracking = models.BooleanField(default=True)
    enable_auto_save = models.BooleanField(default=True)
    
    created_by = models.ForeignKey(
        User, 
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        on_delete=models.CASCADE, 
        related_name='created_exams'
    )
    sections = models.ManyToManyField(Section, related_name='exams')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_by']),
            models.Index(fields=['start_date', 'end_date']),
        ]

    def __str__(self):
        return self.title

    @property
    def is_active(self):
        """Check if exam is currently active based on schedule."""
        now = timezone.now()
        return (self.status == self.Status.LIVE and 
                self.start_date <= now <= self.end_date)

    @property
    def requires_password(self):
        """Check if exam requires a password to start."""
        return bool(self.exam_password.strip())

    def validate_password(self, password_attempt):
        """Validate the provided exam password."""
        if not self.requires_password:
            return True
        return self.exam_password == password_attempt

    def clean(self):
        """Validate exam scheduling and configuration."""
        if self.start_date >= self.end_date:
            raise ValidationError("End date must be after start date.")
        
        if self.pass_percentage > 100:
            raise ValidationError("Pass percentage cannot exceed 100%.")

class ExamQuestion(models.Model):
    """Through model for exam questions with ordering and point overrides."""
    exam = models.ForeignKey(
        Exam, 
        on_delete=models.CASCADE, 
        related_name='exam_questions'
    )
    question = models.ForeignKey(
        Question, 
        on_delete=models.CASCADE, 
        related_name='exam_usage'
    )
    order = models.PositiveIntegerField(default=0)
    points = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )

    class Meta:
        ordering = ['order']
        unique_together = ['exam', 'question']
        indexes = [
            models.Index(fields=['exam', 'order']),
        ]

    def __str__(self):
        return f"{self.exam.title} - Q{self.order}"

    def clean(self):
        """Validate question points."""
        if self.points <= 0:
            raise ValidationError("Points must be greater than zero.")

class ExamAttempt(models.Model):
    """Tracks student attempts at exams with device concurrency control."""
    class Status(models.TextChoices):
        NOT_STARTED = 'NOT_STARTED', 'Not Started'
        PASSWORD_REQUIRED = 'PASSWORD_REQUIRED', 'Password Required'  # New status
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        SUBMITTED = 'SUBMITTED', 'Submitted'
        AUTO_SUBMITTED = 'AUTO_SUBMITTED', 'Auto-Submitted'
        TERMINATED = 'TERMINATED', 'Terminated'

    exam = models.ForeignKey(
        Exam, 
        on_delete=models.CASCADE, 
        related_name='attempts'
    )
    student = models.ForeignKey(
        User, 
        limit_choices_to={'role': User.Role.STUDENT},
        on_delete=models.CASCADE, 
        related_name='exam_attempts'
    )
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    technical_notes = models.JSONField(default=dict)
    
    # Device session tracking
    device_session = models.ForeignKey(
        'core.UserDeviceSession', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='exam_attempts',
        help_text="Device session used for this attempt"
    )
    session_token = models.UUIDField(null=True, blank=True)
    termination_reason = models.CharField(max_length=200, blank=True)
    
    # Auto-save metadata
    last_auto_save = models.DateTimeField(null=True, blank=True)
    auto_save_count = models.PositiveIntegerField(default=0)

    # Password attempt tracking
    password_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Number of incorrect password attempts"
    )
    last_password_attempt = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['exam', 'student']
        ordering = ['-start_time']
        indexes = [
            models.Index(fields=['exam', 'student', 'status']),
            models.Index(fields=['student', 'status']),
            models.Index(fields=['device_session']),
            models.Index(fields=['session_token']),
        ]

    def __str__(self):
        return f"{self.student.email} - {self.exam.title}"

    def clean(self):
        """Validate that the user doesn't have an active session on another device."""
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
                    f"You already have an active exam session started at "
                    f"{other_session.started_at.strftime('%Y-%m-%d %H:%M')} "
                    f"from another device."
                )

    def start_exam(self, device_session, password_attempt=None):
        """Start the exam with password validation."""
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
        """Terminate this attempt due to policy violation."""
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
        """Check if this attempt can be accessed from the given device."""
        if not self.device_session:
            return True
            
        return (self.status != self.Status.IN_PROGRESS or 
                self.device_session.device_hash == device_hash)

    @property
    def duration(self):
        """Calculate attempt duration in minutes."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() / 60
        return None

    @property
    def time_remaining(self):
        """Calculate remaining time for in-progress attempts."""
        if self.status == self.Status.IN_PROGRESS and self.start_time:
            elapsed = (timezone.now() - self.start_time).total_seconds()
            remaining = (self.exam.duration * 60) - elapsed
            return max(0, remaining)
        return 0

    @property
    def requires_password_input(self):
        """Check if this attempt requires password input."""
        return (self.status == self.Status.PASSWORD_REQUIRED or 
                (self.status == self.Status.NOT_STARTED and self.exam.requires_password))

class QuestionResponse(models.Model):
    """Stores student responses with real-time auto-save capability."""
    attempt = models.ForeignKey(
        ExamAttempt, 
        on_delete=models.CASCADE, 
        related_name='responses'
    )
    question = models.ForeignKey(
        Question, 
        on_delete=models.CASCADE
    )
    student_answer = models.JSONField(null=True, blank=True)
    draft_answer = models.JSONField(
        null=True, 
        blank=True, 
        help_text="Temporary answer storage for auto-save"
    )
    points_awarded = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        null=True, 
        blank=True
    )
    auto_save_count = models.PositiveIntegerField(default=0)
    last_auto_save = models.DateTimeField(null=True, blank=True)
    is_submitted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['attempt', 'question']
        indexes = [
            models.Index(fields=['attempt', 'question']),
            models.Index(fields=['last_auto_save']),
        ]
        ordering = ['created_at']

    def __str__(self):
        return f"Response for {self.question} by {self.attempt.student}"

    def save_draft(self, answer_data):
        """Save a draft answer with auto-save metadata."""
        self.draft_answer = answer_data
        self.auto_save_count += 1
        self.last_auto_save = timezone.now()
        self.save(update_fields=['draft_answer', 'auto_save_count', 'last_auto_save', 'updated_at'])

    def finalize_answer(self, answer_data):
        """Finalize the answer and clear draft."""
        self.student_answer = answer_data
        self.draft_answer = None
        self.is_submitted = True
        self.save(update_fields=['student_answer', 'draft_answer', 'is_submitted', 'updated_at'])

class MonitoringEvent(models.Model):
    """Tracks monitoring events for exam security."""
    class EventType(models.TextChoices):
        TAB_SWITCH = 'TAB_SWITCH', 'Tab Switch Detected'
        COPY_PASTE = 'COPY_PASTE', 'Copy/Paste Detected'
        FULLSCREEN_EXIT = 'FULLSCREEN_EXIT', 'Fullscreen Exit'
        MULTIPLE_FACES = 'MULTIPLE_FACES', 'Multiple Faces Detected'
        NO_FACE = 'NO_FACE', 'No Face Detected'
        VOICE_DETECTED = 'VOICE_DETECTED', 'Voice Detected'
        MANUAL_FLAG = 'MANUAL_FLAG', 'Manually Flagged'
        DEVICE_MISMATCH = 'DEVICE_MISMATCH', 'Device Mismatch'
        PASSWORD_BRUTE_FORCE = 'PASSWORD_BRUTE_FORCE', 'Multiple Password Attempts'  # New event type

    class ReviewedStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending Review'
        REVIEWING = 'REVIEWING', 'Under Review'
        APPROVED = 'APPROVED', 'Approved - No Issue'
        VIOLATION = 'VIOLATION', 'Violation Confirmed'
        FALSE_ALARM = 'FALSE_ALARM', 'False Alarm'

    attempt = models.ForeignKey(
        ExamAttempt, 
        on_delete=models.CASCADE, 
        related_name='monitoring_events'
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    timestamp = models.DateTimeField(auto_now_add=True)
    severity = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    evidence = models.JSONField(default=dict)
    description = models.TextField(blank=True)
    reviewed_status = models.CharField(
        max_length=12, 
        choices=ReviewedStatus.choices, 
        default=ReviewedStatus.PENDING
    )
    reviewed_by = models.ForeignKey(
        User, 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL,
        limit_choices_to={'role__in': [User.Role.ADMIN, User.Role.INSTRUCTOR]}
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    action_taken = models.TextField(blank=True, help_text="Actions taken based on this event")

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['attempt', 'event_type', 'reviewed_status']),
            models.Index(fields=['timestamp']),
            models.Index(fields=['reviewed_status']),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.attempt}"

    def assign_for_review(self, assigned_to):
        """Assign this event for review to an admin or instructor."""
        self.reviewed_status = self.ReviewedStatus.REVIEWING
        self.reviewed_by = assigned_to
        self.save(update_fields=['reviewed_status', 'reviewed_by'])

    def complete_review(self, status, notes="", action_taken=""):
        """Complete the review of this monitoring event."""
        self.reviewed_status = status
        self.review_notes = notes
        self.action_taken = action_taken
        self.reviewed_at = timezone.now()
        self.save(update_fields=['reviewed_status', 'review_notes', 'action_taken', 'reviewed_at'])

# Signal handlers for concurrency control
@receiver(pre_save, sender=ExamAttempt)
def validate_single_device_access(sender, instance, **kwargs):
    """Prevent multiple device access for the same exam."""
    if instance.status == ExamAttempt.Status.IN_PROGRESS:
        instance.clean()

@receiver(post_save, sender=ExamAttempt)
def manage_active_sessions(sender, instance, created, **kwargs):
    """Manage active exam sessions when attempt status changes."""
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