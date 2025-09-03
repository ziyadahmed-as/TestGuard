from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from .models import (
    Institution, User, AdminUserCreationLog, UserImportTemplate, 
    UserDeviceSession, ActiveExamSession, AcademicDepartment, 
    Course, Section, Enrollment
)
import csv
from io import StringIO

# Base form styling classes for consistency
INPUT_CLASSES = 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
SELECT_CLASSES = 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
TEXTAREA_CLASSES = 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
CHECKBOX_CLASSES = 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'

class InstitutionForm(forms.ModelForm):
    class Meta:
        model = Institution
        fields = ['name', 'domain', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Enter institution name'
            }),
            'domain': forms.TextInput(attrs={
                'class': INPUT_CLASSES, 
                'placeholder': 'example.edu'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
        }
        help_texts = {
            'domain': 'Primary email domain for institutional authentication (e.g., example.edu)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field.help_text:
                field.widget.attrs['class'] += ' has-help-text'

    def clean_domain(self):
        domain = self.cleaned_data.get('domain', '').lower().strip()
        if domain and not domain.startswith('.'):
            return domain
        raise ValidationError("Please enter a valid domain without the @ symbol")


class UserForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASSES,
            'placeholder': 'Enter password'
        }),
        required=False,
        help_text="Leave blank to generate a random password"
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASSES,
            'placeholder': 'Confirm password'
        }),
        required=False,
        label="Confirm Password"
    )
    
    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'email', 'role', 'institution', 
            'title', 'department', 'is_active', 'email_verified', 'mfa_enabled'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'First name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Last name'
            }),
            'email': forms.EmailInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'user@example.com'
            }),
            'role': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'institution': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'title': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Job title or position'
            }),
            'department': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Department name'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
            'email_verified': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
            'mfa_enabled': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
        }

    def __init__(self, *args, **kwargs):
        self.created_by = kwargs.pop('created_by', None)
        super().__init__(*args, **kwargs)
        
        # For existing users, don't require password fields
        if self.instance and self.instance.pk:
            self.fields['password'].required = False
            self.fields['confirm_password'].required = False

    def clean_email(self):
        email = self.cleaned_data.get('email', '').lower().strip()
        if not email:
            raise ValidationError("Email is required")
        
        # Check for duplicate email within the same institution
        institution = self.cleaned_data.get('institution')
        if institution:
            existing_user = User.objects.filter(
                email=email, 
                institution=institution
            ).exclude(pk=self.instance.pk if self.instance else None).first()
            
            if existing_user:
                raise ValidationError(f"User with email {email} already exists in this institution")
        
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match")
        
        # Validate admin creation permissions
        role = cleaned_data.get('role')
        if role == User.Role.ADMIN and self.created_by and not self.created_by.is_superuser:
            raise ValidationError("Only superusers can create admin accounts.")
        
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        
        # Set created_by if this is a new user
        if not user.pk and self.created_by:
            user.created_by = self.created_by
        
        # Set password if provided
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        elif not user.pk:  # New user without password
            user.set_password(User.objects.make_random_password())
        
        if commit:
            user.save()
        
        return user


class BulkUserUploadForm(forms.Form):
    csv_file = forms.FileField(
        label="CSV File",
        widget=forms.FileInput(attrs={
            'class': 'block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100'
        }),
        help_text="Upload a CSV file with user data. Required columns: email, first_name, last_name, role"
    )
    institution = forms.ModelChoiceField(
        queryset=Institution.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            'class': SELECT_CLASSES
        })
    )
    
    def clean_csv_file(self):
        csv_file = self.cleaned_data.get('csv_file')
        if not csv_file:
            raise ValidationError("Please upload a CSV file")
        
        if not csv_file.name.endswith('.csv'):
            raise ValidationError("File must be a CSV file")
        
        # Read and validate CSV content
        try:
            decoded_file = csv_file.read().decode('utf-8')
            csv_data = csv.DictReader(StringIO(decoded_file))
            
            # Check required columns
            required_columns = ['email', 'first_name', 'last_name', 'role']
            if not csv_data.fieldnames or not all(col in csv_data.fieldnames for col in required_columns):
                raise ValidationError(
                    f"CSV must contain these columns: {', '.join(required_columns)}"
                )
            
            # Validate each row
            user_data_list = []
            for i, row in enumerate(csv_data, start=2):  # Start at 2 to account for header row
                if not row.get('email') or not row.get('email').strip():
                    raise ValidationError(f"Row {i}: Email is required")
                
                user_data = {
                    'email': row['email'].strip().lower(),
                    'first_name': row['first_name'].strip(),
                    'last_name': row['last_name'].strip(),
                    'role': row['role'].strip().upper(),
                    'title': row.get('title', '').strip(),
                    'department': row.get('department', '').strip(),
                    'is_active': row.get('is_active', 'true').lower() in ('true', 'yes', '1'),
                }
                
                user_data_list.append(user_data)
            
            return user_data_list
            
        except Exception as e:
            raise ValidationError(f"Error processing CSV file: {str(e)}")


class AdminUserCreationLogForm(forms.ModelForm):
    class Meta:
        model = AdminUserCreationLog
        fields = ['created_by', 'institution', 'creation_method', 'users_created', 'users_failed', 'details']
        widgets = {
            'created_by': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'institution': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'creation_method': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'users_created': forms.NumberInput(attrs={
                'class': INPUT_CLASSES
            }),
            'users_failed': forms.NumberInput(attrs={
                'class': INPUT_CLASSES
            }),
            'details': forms.Textarea(attrs={
                'class': TEXTAREA_CLASSES,
                'rows': 4,
                'placeholder': 'Enter details about the user creation process'
            }),
        }


class UserImportTemplateForm(forms.ModelForm):
    class Meta:
        model = UserImportTemplate
        fields = ['name', 'description', 'template_file', 'required_fields', 'optional_fields', 'field_descriptions', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Template name'
            }),
            'description': forms.Textarea(attrs={
                'class': TEXTAREA_CLASSES,
                'rows': 3,
                'placeholder': 'Describe this template'
            }),
            'template_file': forms.FileInput(attrs={
                'class': 'block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100'
            }),
            'required_fields': forms.Textarea(attrs={
                'class': TEXTAREA_CLASSES,
                'rows': 2,
                'placeholder': '["email", "first_name", "last_name", "role"]'
            }),
            'optional_fields': forms.Textarea(attrs={
                'class': TEXTAREA_CLASSES,
                'rows': 2,
                'placeholder': '["title", "department", "is_active"]'
            }),
            'field_descriptions': forms.Textarea(attrs={
                'class': TEXTAREA_CLASSES,
                'rows': 3,
                'placeholder': '{"email": "User email address", "first_name": "User first name"}'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
        }


class UserDeviceSessionForm(forms.ModelForm):
    class Meta:
        model = UserDeviceSession
        fields = ['user', 'device_hash', 'browser_name', 'browser_version', 'os_name', 'ip_address', 'is_active', 'user_agent']
        widgets = {
            'user': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'device_hash': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Device hash'
            }),
            'browser_name': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Browser name'
            }),
            'browser_version': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Browser version'
            }),
            'os_name': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Operating system'
            }),
            'ip_address': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'IP address'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
            'user_agent': forms.Textarea(attrs={
                'class': TEXTAREA_CLASSES,
                'rows': 2,
                'placeholder': 'User agent string'
            }),
        }


class ActiveExamSessionForm(forms.ModelForm):
    class Meta:
        model = ActiveExamSession
        fields = ['user', 'exam', 'device_session', 'attempt', 'session_token', 'is_active']
        widgets = {
            'user': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'exam': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'device_session': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'attempt': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'session_token': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Session token'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
        }


class AcademicDepartmentForm(forms.ModelForm):
    class Meta:
        model = AcademicDepartment
        fields = ['institution', 'code', 'name', 'is_active']
        widgets = {
            'institution': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'code': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Department code'
            }),
            'name': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Department name'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
        }


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['department', 'code', 'name', 'credits', 'is_active']
        widgets = {
            'department': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'code': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Course code'
            }),
            'name': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Course name'
            }),
            'credits': forms.NumberInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Credit hours'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
        }


class SectionForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ['course', 'section_code', 'term', 'year', 'instructor', 'is_active']
        widgets = {
            'course': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'section_code': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Section code'
            }),
            'term': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Term (e.g., Fall, Spring)'
            }),
            'year': forms.NumberInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Year'
            }),
            'instructor': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit instructor choices to users with INSTRUCTOR role
        self.fields['instructor'].queryset = User.objects.filter(role=User.Role.INSTRUCTOR)


class EnrollmentForm(forms.ModelForm):
    class Meta:
        model = Enrollment
        fields = ['student', 'section', 'is_active']
        widgets = {
            'student': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'section': forms.Select(attrs={
                'class': SELECT_CLASSES
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': CHECKBOX_CLASSES
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit student choices to users with STUDENT role
        self.fields['student'].queryset = User.objects.filter(role=User.Role.STUDENT)
    
    def clean(self):
        cleaned_data = super().clean()
        student = cleaned_data.get('student')
        section = cleaned_data.get('section')
        
        if student and section:
            # Check if student and section belong to the same institution
            if student.institution != section.course.department.institution:
                raise ValidationError("Student and section must belong to the same institution.")
        
        return cleaned_data


# Filter forms for listing views
class UserFilterForm(forms.Form):
    role = forms.ChoiceField(
        choices=[('', 'All Roles')] + list(User.Role.choices),
        required=False,
        widget=forms.Select(attrs={
            'class': SELECT_CLASSES
        })
    )
    institution = forms.ModelChoiceField(
        queryset=Institution.objects.all(),
        required=False,
        widget=forms.Select(attrs={
            'class': SELECT_CLASSES
        })
    )
    is_active = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': CHECKBOX_CLASSES
        })
    )
    department = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': INPUT_CLASSES,
            'placeholder': 'Department'
        })
    )


class InstitutionFilterForm(forms.Form):
    is_active = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': CHECKBOX_CLASSES
        })
    )
    name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': INPUT_CLASSES,
            'placeholder': 'Search by name'
        })
    )