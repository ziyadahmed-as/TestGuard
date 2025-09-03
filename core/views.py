from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone
from django import forms
from django.core.exceptions import PermissionDenied
from .models import (
    Institution, User, AdminUserCreationLog, UserImportTemplate,
    UserDeviceSession, AcademicDepartment, Course, Section, Enrollment
)
from .forms import (
    InstitutionForm, UserForm, BulkUserUploadForm, AdminUserCreationLogForm,
    UserImportTemplateForm, UserDeviceSessionForm, AcademicDepartmentForm,
    CourseForm, SectionForm, EnrollmentForm, UserFilterForm, InstitutionFilterForm
)
import json
import csv
from io import StringIO

# Helper function to check if user is admin
def is_admin(user):
    return user.is_authenticated and user.role == User.Role.ADMIN

def is_instructor(user):
    return user.is_authenticated and user.role == User.Role.INSTRUCTOR

def is_student(user):
    return user.is_authenticated and user.role == User.Role.STUDENT

def check_role_access(user, required_role):
    """Helper to check if user has the required role"""
    if not user.is_authenticated:
        return False
    if required_role == 'admin':
        return user.role == User.Role.ADMIN
    elif required_role == 'instructor':
        return user.role == User.Role.INSTRUCTOR
    elif required_role == 'student':
        return user.role == User.Role.STUDENT
    return False

# Global Dashboard View
@login_required
def global_dashboard(request):
    """Global dashboard that redirects to appropriate dashboard based on user role"""
    if request.user.role in [User.Role.ADMIN, User.Role.INSTRUCTOR]:
        return redirect('exams:dashboard')
    else:
        # For students, show the core dashboard
        return core_dashboard(request)

# Core Dashboard View
@login_required
def core_dashboard(request):
    """Core module dashboard"""
    # Get statistics
    student_count = User.objects.filter(role=User.Role.STUDENT).count()
    instructor_count = User.objects.filter(role=User.Role.INSTRUCTOR).count()
    course_count = Course.objects.count()
    
    # Import Exam model if available
    try:
        from exams.models import Exam
        exam_count = Exam.objects.count()
    except ImportError:
        exam_count = 0
    
    # Get recent activity (placeholder - you'll need to implement this)
    recent_activity = []
    
    context = {
        'student_count': student_count,
        'instructor_count': instructor_count,
        'course_count': course_count,
        'exam_count': exam_count,
        'recent_activity': recent_activity,
    }
    
    return render(request, 'core/dashboard.html', context)

# Profile View
@login_required
def profile(request):
    """User profile view"""
    user = request.user
    
    if request.method == 'POST':
        # Handle profile updates here if needed
        pass
    
    return render(request, 'profile.html', {'user': user})

# Institution Views
@login_required
@user_passes_test(is_admin)
def institution_list(request):
    form = InstitutionFilterForm(request.GET or None)
    institutions = Institution.objects.all()
    
    if form.is_valid():
        if form.cleaned_data.get('is_active') is not None:
            institutions = institutions.filter(is_active=form.cleaned_data['is_active'])
        if form.cleaned_data.get('name'):
            institutions = institutions.filter(name__icontains=form.cleaned_data['name'])
    
    paginator = Paginator(institutions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'institution_list.html', {
        'page_obj': page_obj,
        'form': form
    })

@login_required
@user_passes_test(is_admin)
def institution_create(request):
    if request.method == 'POST':
        form = InstitutionForm(request.POST)
        if form.is_valid():
            institution = form.save()
            messages.success(request, f'Institution "{institution.name}" created successfully.')
            return redirect('institution_list')
    else:
        form = InstitutionForm()
    
    return render(request, 'form_template.html', {
        'form': form, 
        'title': 'Create Institution',
        'submit_text': 'Create Institution',
        'cancel_url': 'institution_list'
    })

@login_required
@user_passes_test(is_admin)
def institution_update(request, pk):
    institution = get_object_or_404(Institution, pk=pk)
    
    if request.method == 'POST':
        form = InstitutionForm(request.POST, instance=institution)
        if form.is_valid():
            institution = form.save()
            messages.success(request, f'Institution "{institution.name}" updated successfully.')
            return redirect('institution_list')
    else:
        form = InstitutionForm(instance=institution)
    
    return render(request, 'form_template.html', {
        'form': form,
        'title': f'Update {institution.name}',
        'submit_text': 'Update Institution',
        'cancel_url': 'institution_list'
    })
# core/views.py (add to your global_dashboard view)
@login_required
def global_dashboard(request):
    context = {}
    
    # Common user info
    context['user'] = request.user
    
    # Role-specific data
    if request.user.role == User.Role.STUDENT:
        # Get student enrollments
        enrollments = Enrollment.objects.filter(
            student=request.user, is_active=True
        ).select_related('section', 'section__course', 'section__instructor')
        context['enrollments'] = enrollments
        
        # Get student exam stats
        student_attempts = ExamAttempt.objects.filter(student=request.user)
        completed_attempts = student_attempts.filter(
            status__in=[ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.AUTO_SUBMITTED]
        )
        
        # Calculate average score
        scores = [attempt.score for attempt in completed_attempts if attempt.score is not None]
        average_score = sum(scores) / len(scores) if scores else 0
        
        context['completed_exams'] = completed_attempts.count()
        context['average_score'] = round(average_score, 1)
        
        # Get upcoming exams for student's sections
        enrolled_sections = enrollments.values_list('section_id', flat=True)
        context['upcoming_exams'] = Exam.objects.filter(
            sections__in=enrolled_sections, 
            start_date__gte=timezone.now()
        ).order_by('start_date')[:5]
        
    elif request.user.role == User.Role.INSTRUCTOR:
        # Get teaching sections
        teaching_sections = Section.objects.filter(
            instructor=request.user, is_active=True
        )
        context['teaching_sections'] = teaching_sections
        
        # Get student count
        context['total_students'] = Enrollment.objects.filter(
            section__in=teaching_sections, is_active=True
        ).count()
        
        # Get exam stats
        context['created_exams'] = Exam.objects.filter(created_by=request.user).count()
        context['pending_reviews'] = MonitoringEvent.objects.filter(
            reviewed_status=MonitoringEvent.ReviewedStatus.PENDING,
            attempt__exam__created_by=request.user
        ).count()
        
        # Get upcoming exams
        context['upcoming_exams'] = Exam.objects.filter(
            created_by=request.user,
            start_date__gte=timezone.now()
        ).order_by('start_date')[:5]
        
    else:  # Admin
        # Get system stats
        context['institution_count'] = Institution.objects.count()
        context['user_count'] = User.objects.count()
        context['active_user_count'] = User.objects.filter(is_active=True).count()
        
        # Get exam count (if exams app is available)
        try:
            from exams.models import Exam
            context['exam_count'] = Exam.objects.count()
        except ImportError:
            context['exam_count'] = 0
            
        # Get recent users and logs
        context['recent_users'] = User.objects.order_by('-date_joined')[:5]
        context['recent_logs'] = AdminUserCreationLog.objects.select_related(
            'created_by', 'institution'
        ).order_by('-created_at')[:5]
        
        # Get upcoming exams
        context['upcoming_exams'] = Exam.objects.filter(
            start_date__gte=timezone.now()
        ).order_by('start_date')[:5]
    
    # Add recent activity (placeholder - you'll need to implement this)
    context['recent_activity'] = []
    
    return render(request, 'core/global_dashboard.html', context)

@login_required
@user_passes_test(is_admin)
def institution_detail(request, pk):
    institution = get_object_or_404(Institution, pk=pk)
    users = institution.users.all().select_related('institution')
    departments = institution.departments.all()
    
    # Get user statistics
    user_stats = users.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(is_active=True)),
        admins=Count('id', filter=Q(role=User.Role.ADMIN, is_active=True)),
        instructors=Count('id', filter=Q(role=User.Role.INSTRUCTOR, is_active=True)),
        students=Count('id', filter=Q(role=User.Role.STUDENT, is_active=True))
    )
    
    return render(request, 'institution_detail.html', {
        'institution': institution,
        'user_stats': user_stats,
        'departments': departments[:5],
        'recent_users': users.order_by('-date_joined')[:10]
    })

# User Views
@login_required
@user_passes_test(is_admin)
def user_list(request):
    form = UserFilterForm(request.GET or None)
    users = User.objects.select_related('institution').all()
    
    if form.is_valid():
        if form.cleaned_data.get('role'):
            users = users.filter(role=form.cleaned_data['role'])
        if form.cleaned_data.get('institution'):
            users = users.filter(institution=form.cleaned_data['institution'])
        if form.cleaned_data.get('is_active') is not None:
            users = users.filter(is_active=form.cleaned_data['is_active'])
        if form.cleaned_data.get('department'):
            users = users.filter(department__icontains=form.cleaned_data['department'])
    
    paginator = Paginator(users, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'user_list.html', {
        'page_obj': page_obj,
        'form': form,
        'roles': User.Role.choices
    })

@login_required
@user_passes_test(is_admin)
def user_create(request):
    if request.method == 'POST':
        form = UserForm(request.POST, created_by=request.user)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'User "{user.get_full_name()}" created successfully.')
            return redirect('user_list')
    else:
        form = UserForm(created_by=request.user)
    
    return render(request, 'form_template.html', {
        'form': form, 
        'title': 'Create User',
        'submit_text': 'Create User',
        'cancel_url': 'user_list'
    })

@login_required
@user_passes_test(is_admin)
def user_update(request, pk):
    user = get_object_or_404(User, pk=pk)
    
    if request.method == 'POST':
        form = UserForm(request.POST, instance=user, created_by=request.user)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'User "{user.get_full_name()}" updated successfully.')
            return redirect('user_list')
    else:
        form = UserForm(instance=user, created_by=request.user)
    
    return render(request, 'form_template.html', {
        'form': form,
        'title': f'Update {user.get_full_name()}',
        'submit_text': 'Update User',
        'cancel_url': 'user_list'
    })

@login_required
@user_passes_test(is_admin)
def user_detail(request, pk):
    user = get_object_or_404(User, pk=pk)
    device_sessions = user.device_sessions.all().order_by('-last_activity')
    created_users = user.created_users.all() if user.role == User.Role.ADMIN else None
    
    return render(request, 'user_detail.html', {
        'user': user,
        'device_sessions': device_sessions,
        'created_users': created_users
    })

@login_required
@user_passes_test(is_admin)
def bulk_user_upload(request):
    if request.method == 'POST':
        form = BulkUserUploadForm(request.POST, request.FILES)
        if form.is_valid():
            institution = form.cleaned_data['institution']
            user_data_list = form.cleaned_data['csv_file']
            
            try:
                # Create users using the institution's method
                results = institution.create_multiple_users(user_data_list, request.user)
                
                # Log the creation operation
                AdminUserCreationLog.log_creation(
                    created_by=request.user,
                    institution=institution,
                    method=AdminUserCreationLog.CreationMethod.CSV_IMPORT,
                    results=results
                )
                
                if results['success_count'] > 0:
                    messages.success(
                        request, 
                        f"Successfully created {results['success_count']} users. "
                        f"{results['failure_count']} failed."
                    )
                
                if results['failure_count'] > 0:
                    messages.warning(
                        request,
                        f"{results['failure_count']} users failed to create. "
                        "Check the creation log for details."
                    )
                
                return redirect('user_list')
                
            except Exception as e:
                messages.error(request, f"Error creating users: {str(e)}")
    else:
        form = BulkUserUploadForm()
    
    return render(request, 'bulk_user_upload.html', {'form': form})

@login_required
@user_passes_test(is_admin)
def user_creation_logs(request):
    logs = AdminUserCreationLog.objects.select_related('created_by', 'institution').order_by('-created_at')
    
    paginator = Paginator(logs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'user_creation_logs.html', {'page_obj': page_obj})

# Academic Department Views
@login_required
def department_list(request):
    # Check if user has access to view departments
    if not (is_admin(request.user) or is_instructor(request.user) or is_student(request.user)):
        raise PermissionDenied
    
    departments = AcademicDepartment.objects.select_related('institution').filter(is_active=True)
    
    if not is_admin(request.user):
        departments = departments.filter(institution=request.user.institution)
    
    paginator = Paginator(departments, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'department_list.html', {'page_obj': page_obj})

@login_required
def department_detail(request, pk):
    # Check if user has access to view department details
    if not (is_admin(request.user) or is_instructor(request.user) or is_student(request.user)):
        raise PermissionDenied
    
    department = get_object_or_404(AcademicDepartment, pk=pk)
    
    # Check if user has permission to view this department
    if not is_admin(request.user) and department.institution != request.user.institution:
        raise PermissionDenied
    
    # Get related courses and faculty
    courses = Course.objects.filter(department=department, is_active=True)
    faculty = User.objects.filter(
        department=department.name, 
        role=User.Role.INSTRUCTOR, 
        is_active=True
    )
    
    # Get department statistics
    course_count = courses.count()
    faculty_count = faculty.count()
    student_count = User.objects.filter(
        department=department.name, 
        role=User.Role.STUDENT, 
        is_active=True
    ).count()
    
    return render(request, 'department_detail.html', {
        'department': department,
        'courses': courses[:10],  # Show first 10 courses
        'faculty': faculty[:5],   # Show first 5 faculty members
        'course_count': course_count,
        'faculty_count': faculty_count,
        'student_count': student_count
    })

@login_required
@user_passes_test(is_admin)
def department_create(request):
    if request.method == 'POST':
        form = AcademicDepartmentForm(request.POST)
        if form.is_valid():
            department = form.save()
            messages.success(request, f'Department "{department.name}" created successfully.')
            return redirect('department_list')
    else:
        form = AcademicDepartmentForm()
        # Limit institution choices to user's institution if not superuser
        if not request.user.is_superuser:
            form.fields['institution'].queryset = Institution.objects.filter(pk=request.user.institution.pk)
    
    return render(request, 'form_template.html', {
        'form': form, 
        'title': 'Create Department',
        'submit_text': 'Create Department',
        'cancel_url': 'department_list'
    })

@login_required
@user_passes_test(is_admin)
def department_update(request, pk):
    department = get_object_or_404(AcademicDepartment, pk=pk)
    
    if request.method == 'POST':
        form = AcademicDepartmentForm(request.POST, instance=department)
        if form.is_valid():
            department = form.save()
            messages.success(request, f"Department '{department.name}' updated successfully.")
            return redirect('department_list')
    else:
        form = AcademicDepartmentForm(instance=department)
        # Limit institution choices to user's institution if not superuser
        if not request.user.is_superuser:
            form.fields['institution'].queryset = Institution.objects.filter(pk=request.user.institution.pk)
    
    return render(request, 'form_template.html', {
        'form': form,
        'title': f'Update {department.name}',
        'submit_text': 'Update Department',
        'cancel_url': 'department_list'
    })

# Course Views
@login_required
def course_list(request):
    # Check if user has access to view courses
    if not (is_admin(request.user) or is_instructor(request.user) or is_student(request.user)):
        raise PermissionDenied
    
    courses = Course.objects.select_related('department', 'department__institution').filter(is_active=True)
    
    if not is_admin(request.user):
        courses = courses.filter(department__institution=request.user.institution)
    
    paginator = Paginator(courses, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'course_list.html', {'page_obj': page_obj})

@login_required
@user_passes_test(is_admin)
def course_create(request):
    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            course = form.save()
            messages.success(request, f'Course "{course.name}" created successfully.')
            return redirect('course_list')
    else:
        form = CourseForm()
        # Limit department choices to user's institution
        if not request.user.is_superuser:
            form.fields['department'].queryset = AcademicDepartment.objects.filter(
                institution=request.user.institution
            )
    
    return render(request, 'form_template.html', {
        'form': form, 
        'title': 'Create Course',
        'submit_text': 'Create Course',
        'cancel_url': 'course_list'
    })

@login_required
@user_passes_test(is_admin)
def course_update(request, pk):
    course = get_object_or_404(Course, pk=pk)
    
    if request.method == 'POST':
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            course = form.save()
            messages.success(request, f'Course "{course.name}" updated successfully.')
            return redirect('course_list')
    else:
        form = CourseForm(instance=course)
        # Limit department choices to user's institution
        if not request.user.is_superuser:
            form.fields['department'].queryset = AcademicDepartment.objects.filter(
                institution=request.user.institution
            )
    
    return render(request, 'form_template.html', {
        'form': form,
        'title': f'Update {course.name}',
        'submit_text': 'Update Course',
        'cancel_url': 'course_list'
    })

# Section Views
@login_required
def section_list(request):
    # Check if user has access to view sections
    if not (is_admin(request.user) or is_instructor(request.user) or is_student(request.user)):
        raise PermissionDenied
    
    sections = Section.objects.select_related('course', 'course__department', 'instructor').filter(is_active=True)
    
    if is_instructor(request.user):
        sections = sections.filter(instructor=request.user)
    elif is_student(request.user):
        # Get sections where student is enrolled
        enrolled_sections = Enrollment.objects.filter(
            student=request.user, is_active=True
        ).values_list('section_id', flat=True)
        sections = sections.filter(id__in=enrolled_sections)
    elif not is_admin(request.user):
        sections = sections.filter(course__department__institution=request.user.institution)
    
    paginator = Paginator(sections, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'section_list.html', {'page_obj': page_obj})

@login_required
def section_create(request):
    # Check if user has permission to create sections
    if not (is_admin(request.user) or is_instructor(request.user)):
        raise PermissionDenied
    
    if request.method == 'POST':
        form = SectionForm(request.POST)
        if form.is_valid():
            section = form.save()
            messages.success(request, f'Section "{section.section_code}" created successfully.')
            return redirect('section_list')
    else:
        form = SectionForm()
        # Limit choices based on user role
        if not request.user.is_superuser:
            if is_admin(request.user):
                form.fields['course'].queryset = Course.objects.filter(
                    department__institution=request.user.institution
                )
                form.fields['instructor'].queryset = User.objects.filter(
                    institution=request.user.institution, role=User.Role.INSTRUCTOR
                )
            elif is_instructor(request.user):
                form.fields['course'].queryset = Course.objects.filter(
                    department__institution=request.user.institution
                )
                form.fields['instructor'].initial = request.user
                form.fields['instructor'].widget = forms.HiddenInput()
    
    return render(request, 'form_template.html', {
        'form': form, 
        'title': 'Create Section',
        'submit_text': 'Create Section',
        'cancel_url': 'section_list'
    })

@login_required
def section_update(request, pk):
    section = get_object_or_404(Section, pk=pk)
    
    # Check if user has permission to update this section
    if not (is_admin(request.user) or (is_instructor(request.user) and section.instructor == request.user)):
        raise PermissionDenied
    
    if request.method == 'POST':
        form = SectionForm(request.POST, instance=section)
        if form.is_valid():
            section = form.save()
            messages.success(request, f'Section "{section.section_code}" updated successfully.')
            return redirect('section_list')
    else:
        form = SectionForm(instance=section)
        # Limit choices based on user role
        if not request.user.is_superuser:
            if is_admin(request.user):
                form.fields['course'].queryset = Course.objects.filter(
                    department__institution=request.user.institution
                )
                form.fields['instructor'].queryset = User.objects.filter(
                    institution=request.user.institution, role=User.Role.INSTRUCTOR
                )
            elif is_instructor(request.user):
                form.fields['course'].queryset = Course.objects.filter(
                    department__institution=request.user.institution
                )
                form.fields['instructor'].widget = forms.HiddenInput()
    
    return render(request, 'form_template.html', {
        'form': form,
        'title': f'Update {section.section_code}',
        'submit_text': 'Update Section',
        'cancel_url': 'section_list'
    })

# Enrollment Views
@login_required
def enrollment_list(request):
    # Check if user has access to view enrollments
    if not (is_admin(request.user) or is_instructor(request.user) or is_student(request.user)):
        raise PermissionDenied
    
    enrollments = Enrollment.objects.select_related('student', 'section', 'section__course').filter(is_active=True)
    
    if is_instructor(request.user):
        # Get enrollments for sections taught by this instructor
        enrollments = enrollments.filter(section__instructor=request.user)
    elif is_student(request.user):
        enrollments = enrollments.filter(student=request.user)
    elif not is_admin(request.user):
        enrollments = enrollments.filter(section__course__department__institution=request.user.institution)
    
    paginator = Paginator(enrollments, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'enrollment_list.html', {'page_obj': page_obj})

@login_required
def enrollment_create(request):
    # Check if user has permission to create enrollments
    if not (is_admin(request.user) or is_instructor(request.user)):
        raise PermissionDenied
    
    if request.method == 'POST':
        form = EnrollmentForm(request.POST)
        if form.is_valid():
            enrollment = form.save()
            messages.success(request, 'Enrollment created successfully.')
            return redirect('enrollment_list')
    else:
        form = EnrollmentForm()
        # Limit choices based on user role
        if not request.user.is_superuser:
            if is_admin(request.user):
                form.fields['student'].queryset = User.objects.filter(
                    institution=request.user.institution, role=User.Role.STUDENT
                )
                form.fields['section'].queryset = Section.objects.filter(
                    course__department__institution=request.user.institution
                )
            elif is_instructor(request.user):
                form.fields['student'].queryset = User.objects.filter(
                    institution=request.user.institution, role=User.Role.STUDENT
                )
                form.fields['section'].queryset = Section.objects.filter(
                    instructor=request.user
                )
    
    return render(request, 'form_template.html', {
        'form': form, 
        'title': 'Create Enrollment',
        'submit_text': 'Create Enrollment',
        'cancel_url': 'enrollment_list'
    })

@login_required
def enrollment_update(request, pk):
    enrollment = get_object_or_404(Enrollment, pk=pk)
    
    # Check if user has permission to update this enrollment
    if not (is_admin(request.user) or (is_instructor(request.user) and enrollment.section.instructor == request.user)):
        raise PermissionDenied
    
    if request.method == 'POST':
        form = EnrollmentForm(request.POST, instance=enrollment)
        if form.is_valid():
            enrollment = form.save()
            messages.success(request, 'Enrollment updated successfully.')
            return redirect('enrollment_list')
    else:
        form = EnrollmentForm(instance=enrollment)
        # Limit choices based on user role
        if not request.user.is_superuser:
            if is_admin(request.user):
                form.fields['student'].queryset = User.objects.filter(
                    institution=request.user.institution, role=User.Role.STUDENT
                )
                form.fields['section'].queryset = Section.objects.filter(
                    course__department__institution=request.user.institution
                )
            elif is_instructor(request.user):
                form.fields['student'].queryset = User.objects.filter(
                    institution=request.user.institution, role=User.Role.STUDENT
                )
                form.fields['section'].queryset = Section.objects.filter(
                    instructor=request.user
                )
    
    return render(request, 'form_template.html', {
        'form': form,
        'title': 'Update Enrollment',
        'submit_text': 'Update Enrollment',
        'cancel_url': 'enrollment_list'
    })

# API Views for AJAX calls
@login_required
def get_institution_departments(request, institution_id):
    if not is_admin(request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    departments = AcademicDepartment.objects.filter(
        institution_id=institution_id, is_active=True
    ).values('id', 'code', 'name')
    
    return JsonResponse(list(departments), safe=False)

@login_required
def get_department_courses(request, department_id):
    if not (is_admin(request.user) or is_instructor(request.user)):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    courses = Course.objects.filter(
        department_id=department_id, is_active=True
    ).values('id', 'code', 'name')
    
    return JsonResponse(list(courses), safe=False)

@login_required
def get_course_sections(request, course_id):
    if not (is_admin(request.user) or is_instructor(request.user)):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    current_year = timezone.now().year
    sections = Section.objects.filter(
        course_id=course_id, is_active=True, year__gte=current_year
    ).values('id', 'section_code', 'term', 'year')
    
    return JsonResponse(list(sections), safe=False)

# Export Views
@login_required
@user_passes_test(is_admin)
def export_users_csv(request):
    users = User.objects.select_related('institution').all()
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="users_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Email', 'First Name', 'Last Name', 'Role', 'Institution', 
        'Title', 'Department', 'Is Active', 'Email Verified', 'MFA Enabled'
    ])
    
    for user in users:
        writer.writerow([
            user.email, user.first_name, user.last_name, user.get_role_display(),
            user.institution.name, user.title, user.department, user.is_active,
            user.email_verified, user.mfa_enabled
        ])
    
    return response

@login_required
@user_passes_test(is_admin)
def export_institutions_csv(request):
    institutions = Institution.objects.all()
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="institutions_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Name', 'Domain', 'Is Active', 'User Count', 'Created At'])
    
    for institution in institutions:
        writer.writerow([
            institution.name, institution.domain, institution.is_active,
            institution.user_count, institution.created_at.strftime('%Y-%m-%d')
        ])
    return response