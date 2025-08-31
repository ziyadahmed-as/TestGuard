import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from core.models import User, Section, Institution, UserDevice

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

class Tag(models.Model):
    """Taxonomy for categorizing questions."""
    name = models.CharField(max_length=100)
    institution = models.ForeignKey(
        Institution, 
        on_delete=models.CASCADE, 
        related_name='tags'
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['institution', 'name']
        ordering = ['name']
        indexes = [
            models.Index(fields=['institution', 'name']),
        ]

    def __str__(self):
        return f"{self.name}"

class Question(models.Model):
    """Base question model supporting multiple question types."""
    class Type(models.TextChoices):
        MULTIPLE_CHOICE = 'MC', 'Multiple Choice'
        TRUE_FALSE = 'TF', 'True/False'
        FILL_BLANK = 'FB', 'Fill-in-the-Blank'
        SHORT_ANSWER = 'SA', 'Short Answer'
        ESSAY = 'ES', 'Essay'
        CODE = 'CODE', 'Programming'

    class Difficulty(models.TextChoices):
        EASY = 'EASY', 'Easy'
        MEDIUM = 'MED', 'Medium'
        HARD = 'HARD', 'Hard'

    question_text = models.TextField()
    type = models.CharField(max_length=4, choices=Type.choices)
    difficulty = models.CharField(max_length=4, choices=Difficulty.choices)
    bank = models.ForeignKey(
        QuestionBank, 
        on_delete=models.CASCADE, 
        related_name='questions'
    )
    tags = models.ManyToManyField(Tag, related_name='questions', blank=True)
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
            models.Index(fields=['type', 'difficulty', 'is_active']),
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
        default=60.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
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
    
    # Device concurrency fields
    device = models.ForeignKey(
        UserDevice, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='exam_attempts'
    )
    session_token = models.UUIDField(null=True, blank=True)
    termination_reason = models.CharField(max_length=200, blank=True)
    
    # Auto-save metadata
    last_auto_save = models.DateTimeField(null=True, blank=True)
    auto_save_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ['exam', 'student']
        ordering = ['-start_time']
        indexes = [
            models.Index(fields=['exam', 'student', 'status']),
            models.Index(fields=['student', 'status']),
            models.Index(fields=['device']),
            models.Index(fields=['session_token']),
        ]

    def __str__(self):
        return f"{self.student.email} - {self.exam.title}"

    def clean(self):
        """Validate single-device access and attempt consistency."""
        if self.status == self.Status.IN_PROGRESS:
            # Check for existing active sessions on other devices
            from core.models import ActiveExamSession
            active_sessions = ActiveExamSession.objects.filter(
                user=self.student, 
                exam=self.exam, 
                is_active=True
            ).exclude(attempt=self)
            
            if active_sessions.exists():
                raise ValidationError("Student already has an active exam session on another device.")

    def terminate_session(self, reason="Multiple device access detected"):
        """Terminate this attempt due to policy violation."""
        self.status = self.Status.TERMINATED
        self.termination_reason = reason
        self.end_time = timezone.now()
        self.save()
        
        # Deactivate any active session
        from core.models import ActiveExamSession
        ActiveExamSession.objects.filter(
            user=self.student, 
            exam=self.exam, 
            is_active=True
        ).update(is_active=False)

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

class ProctoringEvent(models.Model):
    """Tracks proctoring events and security incidents."""
    class EventType(models.TextChoices):
        TAB_SWITCH = 'TAB_SWITCH', 'Tab Switch Detected'
        COPY_PASTE = 'COPY_PASTE', 'Copy/Paste Detected'
        FULLSCREEN_EXIT = 'FULLSCREEN_EXIT', 'Fullscreen Exit'
        MULTIPLE_FACES = 'MULTIPLE_FACES', 'Multiple Faces Detected'
        NO_FACE = 'NO_FACE', 'No Face Detected'
        VOICE_DETECTED = 'VOICE_DETECTED', 'Voice Detected'
        MANUAL_FLAG = 'MANUAL_FLAG', 'Manually Flagged'
        DEVICE_MISMATCH = 'DEVICE_MISMATCH', 'Device Mismatch'

    attempt = models.ForeignKey(
        ExamAttempt, 
        on_delete=models.CASCADE, 
        related_name='proctoring_events'
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    timestamp = models.DateTimeField(auto_now_add=True)
    severity = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    evidence = models.JSONField(default=dict)
    reviewed = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        User, 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['attempt', 'event_type', 'reviewed']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.attempt}"

# Signal handlers for concurrency control
@receiver(pre_save, sender=ExamAttempt)
def validate_single_device_access(sender, instance, **kwargs):
    """Prevent multiple device access for the same exam."""
    if instance.status == ExamAttempt.Status.IN_PROGRESS:
        instance.clean()

@receiver(post_save, sender=ExamAttempt)
def manage_active_sessions(sender, instance, created, **kwargs):
    """Manage active exam sessions when attempt status changes."""
    from core.models import ActiveExamSession
    
    if instance.status == ExamAttempt.Status.IN_PROGRESS and instance.device:
        # Create or update active session
        ActiveExamSession.objects.update_or_create(
            user=instance.student,
            exam=instance.exam,
            defaults={
                'device': instance.device,
                'attempt': instance,
                'session_token': instance.session_token,
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