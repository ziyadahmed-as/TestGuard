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
from django.db import transaction


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

    def create_multiple_users(self, user_data_list, created_by):
        """
        Create multiple users at once with transactional integrity.
        
        Args:
            user_data_list (list): List of dictionaries containing user data
            created_by (User): Admin user who is creating these users
            
        Returns:
            dict: Results with success count, failures, and details
        """
        results = {
            'success_count': 0,
            'failure_count': 0,
            'errors': [],
            'created_users': [],
            'failed_entries': []
        }
        
        try:
            with transaction.atomic():
                for index, user_data in enumerate(user_data_list):
                    try:
                        user = self._create_single_user(user_data, created_by)
                        results['success_count'] += 1
                        results['created_users'].append({
                            'email': user.email,
                            'name': user.get_full_name(),
                            'role': user.get_role_display()
                        })
                    except Exception as e:
                        results['failure_count'] += 1
                        results['errors'].append(f"Entry {index + 1}: {str(e)}")
                        results['failed_entries'].append({
                            'data': user_data,
                            'error': str(e)
                        })
            
            return results
            
        except Exception as e:
            raise ValidationError(f"Bulk user creation failed: {str(e)}")

    def _create_single_user(self, user_data, created_by):
        """Create a single user with validation."""
        email = user_data.get('email', '').strip().lower()
        if not email:
            raise ValidationError("Email is required")
        
        if User.objects.filter(email=email, institution=self).exists():
            raise ValidationError(f"User with email {email} already exists")
        
        user = User(
            email=email,
            username=email,
            first_name=user_data.get('first_name', '').strip(),
            last_name=user_data.get('last_name', '').strip(),
            role=user_data.get('role', User.Role.STUDENT).strip().upper(),
            institution=self,
            title=user_data.get('title', '').strip(),
            department=user_data.get('department', '').strip(),
            is_active=user_data.get('is_active', True),
            created_by=created_by  # Track who created this user
        )
        
        # Set password (generate random if not provided)
        password = user_data.get('password') or User.objects.make_random_password()
        user.set_password(password)
        
        user.full_clean()
        user.save()
        
        return user


class User(AbstractUser):
    """
    Custom user model with role-based access control and institutional affiliation.
    Extends Django's AbstractUser with enhanced educational platform features.
    """
    
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'System Administrator'
        INSTRUCTOR = 'INSTR', 'Instructor'
        STUDENT = 'STUD', 'Student'

    # Override the groups field to resolve reverse accessor clash
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name='core_user_groups',
        related_query_name='core_user_group',
    )
    
    # Override the user_permissions field to resolve reverse accessor clash
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='core_user_permissions',
        related_query_name='core_user_permission',
    )

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
    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users',
        help_text="Admin user who created this account"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['institution', 'role', 'is_active']),
            models.Index(fields=['email']),
            models.Index(fields=['last_activity']),
            models.Index(fields=['created_at']),
            models.Index(fields=['created_by']),
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

    @classmethod
    def create_multiple(cls, user_data_list, institution, created_by):
        """
        Class method to create multiple users at once.
        
        Args:
            user_data_list (list): List of user data dictionaries
            institution (Institution): Target institution
            created_by (User): Admin user creating these accounts
            
        Returns:
            dict: Creation results with statistics
        """
        return institution.create_multiple_users(user_data_list, created_by)

    def clean(self):
        """Validate user data and ensure institutional consistency."""
        if self.email:
            self.email = self.email.lower()
        
        if self.role == User.Role.ADMIN and self.created_by and not self.created_by.is_superuser:
            raise ValidationError("Only superusers can create admin accounts.")
        
        super().clean()

    def send_welcome_email(self, password=None):
        """
        Send welcome email to new user with login credentials.
        
        Args:
            password (str): Optional password to include in welcome email
        """
        # Implementation would send actual email
        print(f"Welcome email sent to {self.email}")
        if password:
            print(f"Temporary password: {password}")


class AdminUserCreationLog(models.Model):
    """
    Tracks bulk user creation operations by administrators.
    Provides audit trail for user management activities.
    """
    
    class CreationMethod(models.TextChoices):
        MANUAL = 'MANUAL', 'Manual Creation'
        CSV_IMPORT = 'CSV_IMPORT', 'CSV Import'
        API = 'API', 'API Integration'
        SYSTEM = 'SYSTEM', 'System Generated'

    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='user_creation_logs',
        limit_choices_to={'role': User.Role.ADMIN},
        help_text="Administrator who performed the user creation"
    )
    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name='creation_logs',
        help_text="Institution where users were created"
    )
    creation_method = models.CharField(
        max_length=20,
        choices=CreationMethod.choices,
        default=CreationMethod.MANUAL,
        help_text="Method used for user creation"
    )
    users_created = models.PositiveIntegerField(
        default=0,
        help_text="Number of users successfully created"
    )
    users_failed = models.PositiveIntegerField(
        default=0,
        help_text="Number of users that failed to create"
    )
    details = models.JSONField(
        default=dict,
        help_text="Detailed information about the creation operation"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_by', 'created_at']),
            models.Index(fields=['institution', 'created_at']),
            models.Index(fields=['creation_method']),
        ]
        verbose_name = "User Creation Log"
        verbose_name_plural = "User Creation Logs"

    def __str__(self):
        return f"User creation by {self.created_by.email} - {self.get_creation_method_display()}"

    @classmethod
    def log_creation(cls, created_by, institution, method, results, details=None):
        """
        Create a log entry for user creation operation.
        
        Args:
            created_by (User): Admin who performed the operation
            institution (Institution): Target institution
            method (str): Creation method from CreationMethod choices
            results (dict): Results from create_multiple_users
            details (dict): Additional operation details
            
        Returns:
            AdminUserCreationLog: The created log entry
        """
        return cls.objects.create(
            created_by=created_by,
            institution=institution,
            creation_method=method,
            users_created=results.get('success_count', 0),
            users_failed=results.get('failure_count', 0),
            details={
                'results': results,
                'additional_details': details or {}
            }
        )


class UserImportTemplate(models.Model):
    """
    Provides templates and guidelines for bulk user creation.
    """
    
    name = models.CharField(
        max_length=100,
        help_text="Name of the import template"
    )
    description = models.TextField(
        help_text="Description and usage guidelines"
    )
    template_file = models.FileField(
        upload_to='user_templates/',
        help_text="Template file for user data import"
    )
    required_fields = models.JSONField(
        default=list,
        help_text="List of required field names"
    )
    optional_fields = models.JSONField(
        default=list,
        help_text="List of optional field names"
    )
    field_descriptions = models.JSONField(
        default=dict,
        help_text="Descriptions for each field"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this template is active"
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.ADMIN},
        help_text="Admin who created this template"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['created_by']),
        ]
        verbose_name = "User Import Template"
        verbose_name_plural = "User Import Templates"

    def __str__(self):
        return self.name

    def generate_template_csv(self):
        """Generate a CSV template file for user import."""
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        headers = self.required_fields + self.optional_fields
        writer.writerow(headers)
        
        # Write example row
        example_row = []
        for field in headers:
            if field == 'email':
                example_row.append('example@institution.edu')
            elif field == 'first_name':
                example_row.append('John')
            elif field == 'last_name':
                example_row.append('Doe')
            elif field == 'role':
                example_row.append('STUD')
            else:
                example_row.append('')
        
        writer.writerow(example_row)
        
        return ContentFile(output.getvalue().encode(), name=f'{self.name}_template.csv')
    
    
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
            models.Index(fields=['user', 'is_active']),  # FIXED: Changed [] to ()
            models.Index(fields=['last_activity']),
            models.Index(fields=['device_hash']),
            models.Index(fields=['first_seen']),
        ]
        ordering = ['-last_activity']
        verbose_name = "User Device Session"
        verbose_name_plural = "User Device Sessions"

    # ... rest of the UserDeviceSession methods ...
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