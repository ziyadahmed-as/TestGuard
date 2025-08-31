import uuid
import hashlib
import json
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import MinLengthValidator, RegexValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings

class Institution(models.Model):
    """Represents an educational institution or organization."""
    name = models.CharField(max_length=255, unique=True)
    domain = models.CharField(
        max_length=255, 
        unique=True, 
        help_text="Primary email domain for the institution",
        validators=[RegexValidator(regex=r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')]
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['domain', 'is_active']),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """Validate institution data."""
        if self.domain and not self.domain.startswith('.'):
            self.domain = self.domain.lower()
        super().clean()

class User(AbstractUser):
    """Custom user model with role-based access control."""
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'System Administrator'
        INSTRUCTOR = 'INSTR', 'Instructor'
        STUDENT = 'STUD', 'Student'
        PROCTOR = 'PROC', 'Proctor'
        SUPPORT = 'SUPP', 'Support Staff'

    role = models.CharField(max_length=5, choices=Role.choices)
    institution = models.ForeignKey(
        Institution, 
        on_delete=models.CASCADE, 
        related_name='users'
    )
    title = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True)
    email_verified = models.BooleanField(default=False)
    mfa_enabled = models.BooleanField(default=False)
    last_activity = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['institution', 'role', 'is_active']),
            models.Index(fields=['email']),
            models.Index(fields=['last_activity']),
        ]
        unique_together = ['institution', 'email']
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

class UserDeviceSession(models.Model):
    """
    Tracks active device sessions for exam concurrency control.
    Created dynamically when users access exams from devices.
    """
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='device_sessions'
    )
    device_hash = models.CharField(
        max_length=255,
        help_text="Hash of device fingerprint for anonymous identification"
    )
    browser_name = models.CharField(max_length=100, blank=True)
    browser_version = models.CharField(max_length=50, blank=True)
    os_name = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this device session is currently active"
    )
    user_agent = models.TextField(blank=True)

    class Meta:
        unique_together = ['user', 'device_hash']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['last_activity']),
            models.Index(fields=['device_hash']),
        ]
        ordering = ['-last_activity']

    def __str__(self):
        return f"{self.user.email} - {self.device_hash[:8]}"

    @property
    def should_timeout(self):
        """Check if session should timeout due to inactivity."""
        return (timezone.now() - self.last_activity).seconds > 3600  # 1 hour

    def refresh_activity(self):
        """Update the last activity timestamp."""
        self.last_activity = timezone.now()
        self.save(update_fields=['last_activity'])

    def deactivate(self):
        """Deactivate this device session."""
        self.is_active = False
        self.save(update_fields=['is_active', 'last_activity'])

    @classmethod
    def create_from_request(cls, user, request):
        """Create a device session from HTTP request data."""
        device_hash = cls.generate_device_hash(request)
        
        device_session, created = cls.objects.get_or_create(
            user=user,
            device_hash=device_hash,
            defaults={
                'browser_name': request.META.get('HTTP_SEC_CH_UA', ''),
                'browser_version': request.META.get('HTTP_SEC_CH_UA_VERSION', ''),
                'os_name': request.META.get('HTTP_SEC_CH_UA_PLATFORM', ''),
                'ip_address': cls.get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT', '')
            }
        )
        
        if not created:
            device_session.refresh_activity()
            
        return device_session

    @staticmethod
    def generate_device_hash(request):
        """Generate anonymous device fingerprint hash."""
        device_data = {
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'accept_language': request.META.get('HTTP_ACCEPT_LANGUAGE', ''),
            'sec_ch_ua': request.META.get('HTTP_SEC_CH_UA', ''),
            'sec_ch_ua_platform': request.META.get('HTTP_SEC_CH_UA_PLATFORM', ''),
        }
        
        device_json = json.dumps(device_data, sort_keys=True)
        return hashlib.sha256(
            f"{device_json}{settings.SECRET_KEY}".encode()
        ).hexdigest()

    @staticmethod
    def get_client_ip(request):
        """Extract client IP address from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')

class ActiveExamSession(models.Model):
    """
    Tracks currently active exam sessions for concurrency control.
    Ensures one active exam session per user per exam.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='active_exam_sessions')
    exam = models.ForeignKey('exams.Exam', on_delete=models.CASCADE, related_name='active_sessions')
    device_session = models.ForeignKey(UserDeviceSession, on_delete=models.CASCADE, related_name='exam_sessions')
    attempt = models.OneToOneField('exams.ExamAttempt', on_delete=models.CASCADE, related_name='active_session')
    session_token = models.UUIDField(default=uuid.uuid4, unique=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['user', 'exam']  # One active exam per user
        indexes = [
            models.Index(fields=['session_token']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['last_activity']),
            models.Index(fields=['device_session']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.exam.title}"

    def is_valid(self, current_device_hash):
        """Check if session is valid for the current device."""
        return (self.is_active and 
                self.device_session.device_hash == current_device_hash and
                (timezone.now() - self.last_activity).seconds < 300)  # 5-minute activity window

    def refresh_activity(self):
        """Update the last activity timestamp."""
        self.last_activity = timezone.now()
        self.save(update_fields=['last_activity'])

    def terminate(self, reason="Session terminated"):
        """Terminate this exam session."""
        self.is_active = False
        self.save(update_fields=['is_active', 'last_activity'])
        
        # Also terminate the associated attempt
        if self.attempt:
            self.attempt.terminate_session(reason)

# ... [AcademicDepartment, Course, Section, Enrollment models remain unchanged] ...
class AcademicDepartment(models.Model):
    """Represents an academic department within an institution."""
    institution = models.ForeignKey(
        Institution, 
        on_delete=models.CASCADE, 
        related_name='departments'
    )
    code = models.CharField(
        max_length=20,
        validators=[RegexValidator(regex=r'^[A-Z0-9_-]+$')]
    )
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['institution', 'code']
        ordering = ['code']
        indexes = [
            models.Index(fields=['institution', 'is_active']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

class Course(models.Model):
    """Represents a course offered by a department."""
    department = models.ForeignKey(
        AcademicDepartment, 
        on_delete=models.CASCADE, 
        related_name='courses'
    )
    code = models.CharField(
        max_length=20,
        validators=[RegexValidator(regex=r'^[A-Z0-9_-]+$')]
    )
    name = models.CharField(max_length=200)
    credits = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['department', 'code']
        ordering = ['code']
        indexes = [
            models.Index(fields=['department', 'is_active']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

class Section(models.Model):
    """Represents a specific section of a course in a given term."""
    course = models.ForeignKey(
        Course, 
        on_delete=models.CASCADE, 
        related_name='sections'
    )
    section_code = models.CharField(max_length=10)
    term = models.CharField(max_length=20)
    year = models.PositiveIntegerField()
    instructor = models.ForeignKey(
        User, 
        limit_choices_to={'role': User.Role.INSTRUCTOR}, 
        on_delete=models.CASCADE, 
        related_name='teaching_sections'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['course', 'section_code', 'term', 'year']
        ordering = ['-year', 'term', 'section_code']
        indexes = [
            models.Index(fields=['course', 'is_active']),
            models.Index(fields=['instructor', 'is_active']),
        ]

    def __str__(self):
        return f"{self.course.code} - {self.section_code} ({self.term} {self.year})"

class Enrollment(models.Model):
    """Tracks student enrollment in course sections."""
    student = models.ForeignKey(
        User, 
        limit_choices_to={'role': User.Role.STUDENT},
        on_delete=models.CASCADE, 
        related_name='enrollments'
    )
    section = models.ForeignKey(
        Section, 
        on_delete=models.CASCADE, 
        related_name='enrollments'
    )
    enrolled_on = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['student', 'section']
        indexes = [
            models.Index(fields=['student', 'is_active']),
            models.Index(fields=['section', 'is_active']),
        ]
        ordering = ['-enrolled_on']

    def __str__(self):
        return f"{self.student.email} in {self.section}"

    def clean(self):
        """Ensure student belongs to the same institution as the section."""
        if (self.student.institution != self.section.course.department.institution):
            raise ValidationError("Student and section must belong to the same institution.")