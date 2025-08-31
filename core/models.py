import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import MinLengthValidator, RegexValidator
from django.utils import timezone
from django.core.exceptions import ValidationError

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

class UserDevice(models.Model):
    """Tracks and manages user devices for exam security and concurrency control."""
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='devices'
    )
    device_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    device_name = models.CharField(max_length=100, blank=True)
    browser_info = models.CharField(max_length=200, blank=True)
    os_info = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    is_trusted = models.BooleanField(default=False)
    last_used = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'device_id']
        indexes = [
            models.Index(fields=['user', 'is_trusted']),
            models.Index(fields=['device_id']),
        ]
        ordering = ['-last_used']

    def __str__(self):
        return f"{self.user.email} - {self.device_id}"

    @property
    def is_active(self):
        """Check if device has been used recently."""
        return (timezone.now() - self.last_used).days < 30

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