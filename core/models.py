import uuid
import hashlib
import json
import pandas as pd
from io import BytesIO
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import MinLengthValidator, RegexValidator, EmailValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings
from django.core.files.base import ContentFile


class Institution(models.Model):
    """
    Educational institution or organization entity.
    Serves as the primary organizational unit for users and academic resources.
    """
    
    name = models.CharField(
        max_length=255, 
        unique=True,
        help_text="Official name of the educational institution"
    )
    domain = models.CharField(
        max_length=255, 
        unique=True,
        validators=[RegexValidator(regex=r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')],
        help_text="Primary email domain for institutional authentication"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether the institution is currently active"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['domain', 'is_active']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Institution"
        verbose_name_plural = "Institutions"

    def __str__(self):
        return self.name

    def clean(self):
        """Normalize domain to lowercase and validate institutional data."""
        if self.domain and not self.domain.startswith('.'):
            self.domain = self.domain.lower()
        super().clean()

    @property
    def user_count(self):
        """Return the total number of active users in the institution."""
        return self.users.filter(is_active=True).count()


class User(AbstractUser):
    """
    Custom user model with role-based access control and institutional affiliation.
    Extends Django's AbstractUser with enhanced educational platform features.
    """
    
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'System Administrator'
        INSTRUCTOR = 'INSTR', 'Instructor'
        STUDENT = 'STUD', 'Student'

    role = models.CharField(
        max_length=5, 
        choices=Role.choices,
        help_text="User's role within the educational platform"
    )
    institution = models.ForeignKey(
        Institution, 
        on_delete=models.CASCADE, 
        related_name='users',
        help_text="Educational institution the user belongs to"
    )
    title = models.CharField(
        max_length=100, 
        blank=True,
        help_text="Professional or academic title"
    )
    department = models.CharField(
        max_length=100, 
        blank=True,
        help_text="Academic or organizational department"
    )
    email_verified = models.BooleanField(
        default=False,
        help_text="Designates whether the user's email has been verified"
    )
    mfa_enabled = models.BooleanField(
        default=False,
        help_text="Designates whether multi-factor authentication is enabled"
    )
    last_activity = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of the user's last platform activity"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['institution', 'role', 'is_active']),
            models.Index(fields=['email']),
            models.Index(fields=['last_activity']),
            models.Index(fields=['created_at']),
        ]
        unique_together = ['institution', 'email']
        ordering = ['last_name', 'first_name']
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.get_full_name()} ({self.email}) - {self.get_role_display()}"

    def save(self, *args, **kwargs):
        """Ensure data validation before saving and use email as username."""
        self.clean()
        if not self.username:
            self.username = self.email
        super().save(*args, **kwargs)

    def get_full_name(self):
        """Return the user's full name with proper formatting."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_educator(self):
        """Check if user has educator privileges (Admin or Instructor)."""
        return self.role in [User.Role.ADMIN, User.Role.INSTRUCTOR]

    @property
    def is_student(self):
        """Check if user has student role."""
        return self.role == User.Role.STUDENT

    def clean(self):
        """Validate user data and ensure institutional consistency."""
        if self.email:
            self.email = self.email.lower()
        super().clean()


class BulkUserImport(models.Model):
    """
    Manages bulk user import operations from spreadsheet files.
    Provides tracking and auditing for administrative user management.
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
        related_name='user_imports',
        limit_choices_to={'role': User.Role.ADMIN},
        help_text="Administrator who initiated the import operation"
    )
    import_file = models.FileField(
        upload_to='user_imports/%Y/%m/%d/',
        help_text='Excel spreadsheet containing user data for import'
    )
    status = models.CharField(
        max_length=12, 
        choices=Status.choices, 
        default=Status.PENDING,
        help_text="Current processing status of the import operation"
    )
    total_records = models.PositiveIntegerField(
        default=0,
        help_text="Total number of records identified in the import file"
    )
    successful_imports = models.PositiveIntegerField(
        default=0,
        help_text="Number of user records successfully created"
    )
    failed_imports = models.PositiveIntegerField(
        default=0,
        help_text="Number of user records that failed to import"
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
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Bulk User Import"
        verbose_name_plural = "Bulk User Imports"

    def __str__(self):
        return f"Import #{self.id} by {self.uploaded_by.email} - {self.get_status_display()}"

    def process_import(self):
        """
        Execute the bulk user import process from the uploaded spreadsheet.
        Handles file parsing, validation, and user creation with comprehensive error handling.
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
                    self._create_user_from_row(row)
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

    def _create_user_from_row(self, row):
        """
        Create a user record from a single row of import data.
        
        Args:
            row (pandas.Series): Data row containing user information
            
        Raises:
            ValidationError: If required data is missing or invalid
        """
        email = str(row.get('email', '')).strip().lower()
        if not email:
            raise ValidationError("Email address is required for user creation")
        
        # Check for existing user within the same institution
        if User.objects.filter(email=email, institution=self.uploaded_by.institution).exists():
            raise ValidationError(f"User with email {email} already exists in this institution")
        
        # Generate secure temporary password
        password = User.objects.make_random_password()
        
        user = User(
            email=email,
            username=email,
            first_name=str(row.get('first_name', '')).strip(),
            last_name=str(row.get('last_name', '')).strip(),
            role=str(row.get('role', User.Role.STUDENT)).strip().upper(),
            institution=self.uploaded_by.institution,
            title=str(row.get('title', '')).strip(),
            department=str(row.get('department', '')).strip(),
            is_active=bool(row.get('is_active', True))
        )
        
        user.set_password(password)
        user.full_clean()
        user.save()
        
        return user

    @property
    def success_rate(self):
        """Calculate the percentage of successfully imported records."""
        if self.total_records > 0:
            return (self.successful_imports / self.total_records) * 100
        return 0


class UserDeviceSession(models.Model):
    """
    Tracks user device sessions for security and concurrency control.
    Enforces single-device exam access and provides device fingerprinting.
    """
    
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='device_sessions',
        help_text="User associated with this device session"
    )
    device_hash = models.CharField(
        max_length=255,
        help_text="Cryptographic hash of device fingerprint for anonymous identification"
    )
    browser_name = models.CharField(
        max_length=100, 
        blank=True,
        help_text="Name of the web browser used"
    )
    browser_version = models.CharField(
        max_length=50, 
        blank=True,
        help_text="Version of the web browser"
    )
    os_name = models.CharField(
        max_length=100, 
        blank=True,
        help_text="Operating system name"
    )
    ip_address = models.GenericIPAddressField(
        blank=True, 
        null=True,
        help_text="IP address from which the session was initiated"
    )
    first_seen = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the device was first recognized"
    )
    last_activity = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of the most recent activity from this device"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this device session is currently active"
    )
    user_agent = models.TextField(
        blank=True,
        help_text="Raw HTTP user agent string"
    )

    class Meta:
        unique_together = ['user', 'device_hash']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['last_activity']),
            models.Index(fields=['device_hash']),
            models.Index(fields=['first_seen']),
        ]
        ordering = ['-last_activity']
        verbose_name = "User Device Session"
        verbose_name_plural = "User Device Sessions"

    def __str__(self):
        return f"{self.user.email} - Device {self.device_hash[:12]}"

    @property
    def should_timeout(self):
        """Determine if session should timeout due to inactivity."""
        return (timezone.now() - self.last_activity).total_seconds() > 3600  # 1 hour

    def refresh_activity(self):
        """Update the last activity timestamp to extend session validity."""
        self.last_activity = timezone.now()
        self.save(update_fields=['last_activity'])

    def deactivate(self):
        """Deactivate this device session while preserving historical data."""
        self.is_active = False
        self.save(update_fields=['is_active', 'last_activity'])

    @classmethod
    def create_from_request(cls, user, request):
        """
        Create or update a device session based on HTTP request data.
        
        Args:
            user (User): The authenticated user
            request (HttpRequest): The HTTP request object
            
        Returns:
            UserDeviceSession: The created or updated device session
        """
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
        """
        Generate anonymous device fingerprint hash for identification.
        
        Args:
            request (HttpRequest): The HTTP request object
            
        Returns:
            str: SHA-256 hash of device characteristics
        """
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
        """
        Extract client IP address from request headers.
        
        Args:
            request (HttpRequest): The HTTP request object
            
        Returns:
            str: Client IP address or None if unavailable
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')


class ActiveExamSession(models.Model):
    """
    Manages active exam sessions with concurrency control and device validation.
    Ensures single active exam session per user with device fingerprinting.
    """
    
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='active_exam_sessions',
        help_text="User participating in the exam session"
    )
    exam = models.ForeignKey(
        'exams.Exam', 
        on_delete=models.CASCADE, 
        related_name='active_sessions',
        help_text="Exam associated with this active session"
    )
    device_session = models.ForeignKey(
        UserDeviceSession, 
        on_delete=models.CASCADE, 
        related_name='exam_sessions',
        help_text="Device session used for this exam attempt"
    )
    attempt = models.OneToOneField(
        'exams.ExamAttempt', 
        on_delete=models.CASCADE, 
        related_name='active_session',
        help_text="Specific exam attempt associated with this session"
    )
    session_token = models.UUIDField(
        default=uuid.uuid4, 
        unique=True,
        help_text="Unique identifier for this exam session"
    )
    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the exam session commenced"
    )
    last_activity = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of the most recent activity during this session"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this exam session is currently active"
    )

    class Meta:
        unique_together = ['user', 'exam']
        indexes = [
            models.Index(fields=['session_token']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['last_activity']),
            models.Index(fields=['device_session']),
            models.Index(fields=['started_at']),
        ]
        verbose_name = "Active Exam Session"
        verbose_name_plural = "Active Exam Sessions"

    def __str__(self):
        return f"{self.user.email} - {self.exam.title} - {self.session_token[:8]}"

    def is_valid(self, current_device_hash):
        """
        Validate session authenticity and activity status.
        
        Args:
            current_device_hash (str): Device hash from current request
            
        Returns:
            bool: True if session is valid and active
        """
        return (self.is_active and 
                self.device_session.device_hash == current_device_hash and
                (timezone.now() - self.last_activity).total_seconds() < 300)

    def refresh_activity(self):
        """Update the last activity timestamp to maintain session validity."""
        self.last_activity = timezone.now()
        self.save(update_fields=['last_activity'])

    def terminate(self, reason="Session terminated by system"):
        """
        Terminate the exam session and associated attempt.
        
        Args:
            reason (str): Explanation for session termination
        """
        self.is_active = False
        self.save(update_fields=['is_active', 'last_activity'])
        
        if self.attempt:
            self.attempt.terminate_session(reason)

    @property
    def duration_minutes(self):
        """Calculate the total duration of the exam session in minutes."""
        if self.started_at and self.last_activity:
            return (self.last_activity - self.started_at).total_seconds() / 60
        return 0


class AcademicDepartment(models.Model):
    """
    Academic department within an educational institution.
    Organizes courses and faculty within the institutional hierarchy.
    """
    
    institution = models.ForeignKey(
        Institution, 
        on_delete=models.CASCADE, 
        related_name='departments',
        help_text="Institution that contains this academic department"
    )
    code = models.CharField(
        max_length=20,
        validators=[RegexValidator(regex=r'^[A-Z0-9_-]+$')],
        help_text="Unique department code within the institution"
    )
    name = models.CharField(
        max_length=100,
        help_text="Official name of the academic department"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether the department is currently active"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['institution', 'code']
        ordering = ['code']
        indexes = [
            models.Index(fields=['institution', 'is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = "Academic Department"
        verbose_name_plural = "Academic Departments"

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def active_courses_count(self):
        """Return the number of active courses in the department."""
        return self.courses.filter(is_active=True).count()


class Course(models.Model):
    """
    Academic course offered by a department.
    Represents a specific subject or field of study.
    """
    
    department = models.ForeignKey(
        AcademicDepartment, 
        on_delete=models.CASCADE, 
        related_name='courses',
        help_text="Academic department offering this course"
    )
    code = models.CharField(
        max_length=20,
        validators=[RegexValidator(regex=r'^[A-Z0-9_-]+$')],
        help_text="Unique course code within the department"
    )
    name = models.CharField(
        max_length=200,
        help_text="Official name of the course"
    )
    credits = models.PositiveIntegerField(
        help_text="Number of academic credits awarded for completing the course"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether the course is currently active"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['department', 'code']
        ordering = ['code']
        indexes = [
            models.Index(fields=['department', 'is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = "Course"
        verbose_name_plural = "Courses"

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def active_sections_count(self):
        """Return the number of active sections for this course."""
        return self.sections.filter(is_active=True).count()


class Section(models.Model):
    """
    Specific section of a course offered in a given term.
    Represents an instance of a course with assigned instructor and schedule.
    """
    
    course = models.ForeignKey(
        Course, 
        on_delete=models.CASCADE, 
        related_name='sections',
        help_text="Course that this section belongs to"
    )
    section_code = models.CharField(
        max_length=10,
        help_text="Unique identifier for this specific section"
    )
    term = models.CharField(
        max_length=20,
        help_text="Academic term when this section is offered"
    )
    year = models.PositiveIntegerField(
        help_text="Academic year when this section is offered"
    )
    instructor = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.INSTRUCTOR}, 
        related_name='teaching_sections',
        help_text="Instructor responsible for teaching this section"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this section is currently active"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['course', 'section_code', 'term', 'year']
        ordering = ['-year', 'term', 'section_code']
        indexes = [
            models.Index(fields=['course', 'is_active']),
            models.Index(fields=['instructor', 'is_active']),
            models.Index(fields=['term', 'year']),
        ]
        verbose_name = "Course Section"
        verbose_name_plural = "Course Sections"

    def __str__(self):
        return f"{self.course.code} - {self.section_code} ({self.term} {self.year})"

    @property
    def enrollment_count(self):
        """Return the number of active enrollments in this section."""
        return self.enrollments.filter(is_active=True).count()


class Enrollment(models.Model):
    """
    Student enrollment record for course sections.
    Tracks student participation and attendance in specific course offerings.
    """
    
    student = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.STUDENT},
        related_name='enrollments',
        help_text="Student enrolled in the course section"
    )
    section = models.ForeignKey(
        Section, 
        on_delete=models.CASCADE, 
        related_name='enrollments',
        help_text="Course section the student is enrolled in"
    )
    enrolled_on = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the enrollment was created"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this enrollment is currently active"
    )

    class Meta:
        unique_together = ['student', 'section']
        indexes = [
            models.Index(fields=['student', 'is_active']),
            models.Index(fields=['section', 'is_active']),
            models.Index(fields=['enrolled_on']),
        ]
        ordering = ['-enrolled_on']
        verbose_name = "Enrollment"
        verbose_name_plural = "Enrollments"

    def __str__(self):
        return f"{self.student.email} in {self.section}"

    def clean(self):
        """Validate institutional consistency between student and section."""
        if (self.student.institution != self.section.course.department.institution):
            raise ValidationError("Student and section must belong to the same institution.")

    @property
    def enrollment_duration(self):
        """Calculate the duration of the enrollment in days."""
        return (timezone.now() - self.enrolled_on).days