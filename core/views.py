from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.utils.decorators import method_decorator
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from django.contrib.auth.views import LoginView

from .models import (
    Institution, User, AdminUserCreationLog, UserImportTemplate, 
    UserDeviceSession, AcademicDepartment, Course, Section, Enrollment, Profile
)
from .forms import (
    InstitutionForm, UserForm, BulkUserUploadForm, AdminUserCreationLogForm,
    UserImportTemplateForm, UserDeviceSessionForm, AcademicDepartmentForm, 
    CourseForm, SectionForm, EnrollmentForm, UserFilterForm, InstitutionFilterForm,
    ProfileForm, AdminProfileUpdateForm  # Use the correct form name
)

# Custom Login View to handle redirects properly
class CustomLoginView(LoginView):
    template_name = 'registration/login.html'
    
    def get_success_url(self):
        # Redirect to dashboard after successful login
        return reverse('dashboard')

# Utility functions
def is_superadmin(user):
    return user.is_authenticated and user.role == User.Role.SUPERADMIN

def is_admin(user):
    return user.is_authenticated and user.role == User.Role.ADMIN

def is_instructor(user):
    return user.is_authenticated and user.role == User.Role.INSTRUCTOR

def is_student(user):
    return user.is_authenticated and user.role == User.Role.STUDENT

def superadmin_required(view_func):
    decorated_view_func = login_required(user_passes_test(
        is_superadmin, 
        login_url='login',
        redirect_field_name=None
    )(view_func))
    return decorated_view_func

def admin_required(view_func):
    decorated_view_func = login_required(user_passes_test(
        lambda u: is_admin(u) or is_superadmin(u),
        login_url='login',
        redirect_field_name=None
    )(view_func))
    return decorated_view_func

def instructor_required(view_func):
    decorated_view_func = login_required(user_passes_test(
        lambda u: is_instructor(u) or is_admin(u) or is_superadmin(u),
        login_url='login',
        redirect_field_name=None
    )(view_func))
    return decorated_view_func

# Dashboard View - This is the main entry point after login
@login_required
def dashboard(request):
    context = {}
    
    if request.user.is_superadmin:
        # Superadmin dashboard - show all institutions
        context['institutions'] = Institution.objects.all()
        context['user_count'] = User.objects.filter(is_active=True).count()
        context['student_count'] = User.objects.filter(
            role=User.Role.STUDENT,
            is_active=True
        ).count()
        context['instructor_count'] = User.objects.filter(
            role__in=[User.Role.INSTRUCTOR, User.Role.ADMIN],
            is_active=True
        ).count()
        context['institution_count'] = Institution.objects.filter(is_active=True).count()
        
    elif request.user.is_admin:
        # Admin dashboard - show only their institution
        context['institution'] = request.user.institution
        context['user_count'] = User.objects.filter(
            institution=request.user.institution, 
            is_active=True
        ).count()
        context['student_count'] = User.objects.filter(
            institution=request.user.institution, 
            role=User.Role.STUDENT,
            is_active=True
        ).count()
        context['instructor_count'] = User.objects.filter(
            institution=request.user.institution, 
            role__in=[User.Role.INSTRUCTOR, User.Role.ADMIN],
            is_active=True
        ).count()
        context['department_count'] = AcademicDepartment.objects.filter(
            institution=request.user.institution,
            is_active=True
        ).count()
        context['course_count'] = Course.objects.filter(
            department__institution=request.user.institution,
            is_active=True
        ).count()
        
    elif request.user.is_instructor:
        # Instructor dashboard
        context['teaching_sections'] = Section.objects.filter(
            instructor=request.user,
            is_active=True
        ).select_related('course')
        context['student_count'] = Enrollment.objects.filter(
            section__instructor=request.user,
            is_active=True
        ).count()
        
    elif request.user.is_student:
        # Student dashboard
        context['enrollments'] = Enrollment.objects.filter(
            student=request.user,
            is_active=True
        ).select_related('section__course', 'section__instructor')
    
    # Add this line to use the correct template path
    return render(request, 'core/dashboard.html', context)

# Profile Views
@method_decorator(login_required, name='dispatch')
class ProfileUpdateView(UpdateView):
    model = Profile
    form_class = ProfileForm
    template_name = 'profile_form.html'
    
    def get_object(self):
        # Users can only edit their own profile
        return self.request.user.profile
    
    def get_success_url(self):
        messages.success(self.request, 'Profile updated successfully.')
        return reverse('profile_detail')

@method_decorator(login_required, name='dispatch')
class ProfileDetailView(DetailView):
    model = Profile
    template_name = 'profile_detail.html'
    context_object_name = 'profile'
    
    def get_object(self):
        # Users can only view their own profile unless they're admins
        if 'pk' in self.kwargs and (self.request.user.is_admin or self.request.user.is_superadmin):
            return get_object_or_404(Profile, pk=self.kwargs['pk'])
        return self.request.user.profile
    
    def dispatch(self, request, *args, **kwargs):
        # Admins can view any profile in their institution
        if 'pk' in kwargs:
            profile = get_object_or_404(Profile, pk=kwargs['pk'])
            if not (request.user.is_superadmin or 
                   (request.user.is_admin and profile.user.institution == request.user.institution)):
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

@method_decorator(admin_required, name='dispatch')
class ProfileAdminUpdateView(UpdateView):
    model = Profile
    form_class = AdminProfileUpdateForm
    template_name = 'profile_admin_form.html'
    
    def get_success_url(self):
        messages.success(self.request, 'Profile updated successfully.')
        return reverse('profile_admin_detail', kwargs={'pk': self.object.pk})
    
    def dispatch(self, request, *args, **kwargs):
        # Admins can only edit profiles in their institution unless they're superadmins
        obj = self.get_object()
        if not request.user.is_superadmin and obj.user.institution != request.user.institution:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

@method_decorator(admin_required, name='dispatch')
class ProfileAdminDetailView(DetailView):
    model = Profile
    template_name = 'profile_admin_detail.html'
    context_object_name = 'profile'
    
    def dispatch(self, request, *args, **kwargs):
        # Admins can only view profiles in their institution unless they're superadmins
        obj = self.get_object()
        if not request.user.is_superadmin and obj.user.institution != request.user.institution:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

@admin_required
def profile_verify(request, pk):
    profile = get_object_or_404(Profile, pk=pk)
    
    # Check if admin has permission to verify this profile
    if not request.user.is_superadmin and profile.user.institution != request.user.institution:
        raise PermissionDenied
    
    profile.is_verified = True
    profile.verified_at = timezone.now()
    profile.save()
    
    messages.success(request, 'Profile verified successfully.')
    return redirect('profile_admin_detail', pk=profile.pk)

@admin_required
def profile_unverify(request, pk):
    profile = get_object_or_404(Profile, pk=pk)
    
    # Check if admin has permission to unverify this profile
    if not request.user.is_superadmin and profile.user.institution != request.user.institution:
        raise PermissionDenied
    
    profile.is_verified = False
    profile.verified_at = None
    profile.save()
    
    messages.success(request, 'Profile verification removed successfully.')
    return redirect('profile_admin_detail', pk=profile.pk)

# Institution Views
@method_decorator(superadmin_required, name='dispatch')
class InstitutionListView(ListView):
    model = Institution
    template_name = 'institution_list.html'
    context_object_name = 'institutions'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = Institution.objects.all()
        form = InstitutionFilterForm(self.request.GET)
        
        if form.is_valid():
            if form.cleaned_data.get('is_active'):
                queryset = queryset.filter(is_active=True)
            if form.cleaned_data.get('name'):
                queryset = queryset.filter(name__icontains=form.cleaned_data['name'])
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = InstitutionFilterForm(self.request.GET)
        return context

@method_decorator(superadmin_required, name='dispatch')
class InstitutionCreateView(CreateView):
    model = Institution
    form_class = InstitutionForm
    template_name = 'institution_form.html'
    success_url = reverse_lazy('institution_list')
    
    def form_valid(self, form):
        messages.success(self.request, 'Institution created successfully.')
        return super().form_valid(form)

@method_decorator(superadmin_required, name='dispatch')
class InstitutionUpdateView(UpdateView):
    model = Institution
    form_class = InstitutionForm
    template_name = 'institution_form.html'
    success_url = reverse_lazy('institution_list')
    
    def form_valid(self, form):
        messages.success(self.request, 'Institution updated successfully.')
        return super().form_valid(form)

@method_decorator(admin_required, name='dispatch')
class InstitutionDetailView(DetailView):
    model = Institution
    template_name = 'institution_detail.html'
    context_object_name = 'institution'
    
    def dispatch(self, request, *args, **kwargs):
        # Admins can only view their own institution unless they're superadmins
        obj = self.get_object()
        if not request.user.is_superadmin and obj != request.user.institution:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_count'] = self.object.user_count
        context['departments'] = self.object.departments.filter(is_active=True)
        return context

@superadmin_required
def institution_toggle_active(request, pk):
    institution = get_object_or_404(Institution, pk=pk)
    institution.is_active = not institution.is_active
    institution.save()
    
    action = "activated" if institution.is_active else "deactivated"
    messages.success(request, f'Institution {action} successfully.')
    
    return redirect('institution_list')

# User Views
@method_decorator(admin_required, name='dispatch')
class UserListView(ListView):
    model = User
    template_name = 'user_list.html'
    context_object_name = 'users'
    paginate_by = 20
    
    def get_queryset(self):
        if self.request.user.is_superadmin:
            queryset = User.objects.select_related('institution')
        else:
            queryset = User.objects.filter(institution=self.request.user.institution).select_related('institution')
            
        form = UserFilterForm(self.request.GET)
        
        if form.is_valid():
            if form.cleaned_data.get('role'):
                queryset = queryset.filter(role=form.cleaned_data['role'])
            if form.cleaned_data.get('institution') and self.request.user.is_superadmin:
                queryset = queryset.filter(institution=form.cleaned_data['institution'])
            if form.cleaned_data.get('is_active') is not None:
                queryset = queryset.filter(is_active=form.cleaned_data['is_active'])
            if form.cleaned_data.get('department'):
                queryset = queryset.filter(department__icontains=form.cleaned_data['department'])
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = UserFilterForm(self.request.GET)
        # For non-superadmins, remove the institution filter
        if not self.request.user.is_superadmin:
            context['filter_form'].fields.pop('institution')
        return context

@method_decorator(admin_required, name='dispatch')
class UserCreateView(CreateView):
    model = User
    form_class = UserForm
    template_name = 'user_form.html'
    success_url = reverse_lazy('user_list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['created_by'] = self.request.user
        # For non-superadmins, limit institution to their own
        if not self.request.user.is_superadmin:
            kwargs['initial'] = {'institution': self.request.user.institution}
        return kwargs
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # For non-superadmins, limit institution choices to their own
        if not self.request.user.is_superadmin:
            form.fields['institution'].queryset = Institution.objects.filter(id=self.request.user.institution.id)
            form.fields['institution'].disabled = True
        return form
    
    def form_valid(self, form):
        # For non-superadmins, force the institution to be their own
        if not self.request.user.is_superadmin:
            form.instance.institution = self.request.user.institution
            
        response = super().form_valid(form)
        messages.success(self.request, 'User created successfully.')
        
        # Send welcome email with password if it's a new user
        if form.cleaned_data.get('password'):
            self.object.send_welcome_email(form.cleaned_data['password'])
        else:
            # If no password was set, the form generates a random one
            self.object.send_welcome_email()
        
        return response

@method_decorator(login_required, name='dispatch')
class UserUpdateView(UpdateView):
    model = User
    form_class = UserForm
    template_name = 'user_form.html'
    
    def get_success_url(self):
        return reverse('user_detail', kwargs={'pk': self.object.pk})
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Only pass created_by for new users, not for updates
        if not self.object.pk:
            kwargs['created_by'] = self.request.user
        return kwargs
    
    def dispatch(self, request, *args, **kwargs):
        # Users can only edit their own profile unless they're admins
        obj = self.get_object()
        if not (request.user.is_admin or request.user == obj):
            raise PermissionDenied
            
        # Admins can only edit users in their institution unless they're superadmins
        if request.user.is_admin and not request.user.is_superadmin and obj.institution != request.user.institution:
            raise PermissionDenied
            
        return super().dispatch(request, *args, **kwargs)
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # For non-superadmins, limit institution choices to their own and disable the field
        if not self.request.user.is_superadmin:
            form.fields['institution'].queryset = Institution.objects.filter(id=self.request.user.institution.id)
            form.fields['institution'].disabled = True
        return form
    
    def form_valid(self, form):
        # For non-superadmins, force the institution to be their own
        if not self.request.user.is_superadmin:
            form.instance.institution = self.request.user.institution
            
        messages.success(self.request, 'User updated successfully.')
        return super().form_valid(form)

@method_decorator(login_required, name='dispatch')
class UserDetailView(DetailView):
    model = User
    template_name = 'user_detail.html'
    context_object_name = 'user_profile'
    
    def dispatch(self, request, *args, **kwargs):
        # Users can only view their own profile unless they're admins
        obj = self.get_object()
        if not (request.user.is_admin or request.user == obj):
            raise PermissionDenied
            
        # Admins can only view users in their institution unless they're superadmins
        if request.user.is_admin and not request.user.is_superadmin and obj.institution != request.user.institution:
            raise PermissionDenied
            
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.is_student:
            context['enrollments'] = self.object.enrollments.filter(is_active=True).select_related('section__course')
        elif self.object.is_educator:
            context['teaching_sections'] = self.object.teaching_sections.filter(is_active=True).select_related('course')
        return context

@admin_required
def user_toggle_active(request, pk):
    user = get_object_or_404(User, pk=pk)
    
    # Check if admin has permission to modify this user
    if not request.user.is_superadmin and user.institution != request.user.institution:
        raise PermissionDenied
    
    # Prevent users from deactivating themselves
    if request.user == user:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('user_list')
    
    user.is_active = not user.is_active
    user.save()
    
    action = "activated" if user.is_active else "deactivated"
    messages.success(request, f'User {action} successfully.')
    
    return redirect('user_list')

@admin_required
def bulk_user_upload(request):
    if request.method == 'POST':
        form = BulkUserUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # For non-superadmins, force the institution to be their own
                if not request.user.is_admin or request.user.is_superadmin:
                    institution = request.user.institution
                else:
                    institution = form.cleaned_data['institution']
                    
                user_data_list = form.cleaned_data['csv_file']
                
                # Create users using the institution's method
                results = institution.create_multiple_users(user_data_list, request.user)
                
                # Log the creation operation
                AdminUserCreationLog.log_creation(
                    created_by=request.user,
                    institution=institution,
                    method=AdminUserCreationLog.CreationMethod.CSV_IMPORT,
                    results=results
                )
                
                # Prepare success message with results
                success_msg = (
                    f"Successfully created {results['success_count']} users. "
                    f"{results['failure_count']} failures."
                )
                messages.success(request, success_msg)
                
                # If there were failures, store them in session to display
                if results['failure_count'] > 0:
                    request.session['bulk_upload_errors'] = results['errors']
                
                return redirect('user_list')
                
            except Exception as e:
                messages.error(request, f'Error processing upload: {str(e)}')
    else:
        form = BulkUserUploadForm()
        
        # For non-superadmins, set the initial institution to their own
        if not request.user.is_superadmin:
            form.fields['institution'].initial = request.user.institution
            form.fields['institution'].disabled = True
    
    return render(request, 'bulk_user_upload.html', {'form': form})

@admin_required
def download_import_template(request, template_id=None):
    if template_id:
        template = get_object_or_404(UserImportTemplate, id=template_id, is_active=True)
        csv_file = template.generate_template_csv()
    else:
        # Create a default template if none specified
        default_template = UserImportTemplate(
            name="Default User Import Template",
            required_fields=['email', 'first_name', 'last_name', 'role'],
            optional_fields=['title', 'department', 'is_active'],
            field_descriptions={
                'email': 'User email address (must be unique within institution)',
                'first_name': 'User first name',
                'last_name': 'User last name',
                'role': 'User role (ADMIN, INSTR, or STUD)',
                'title': 'Professional title (optional)',
                'department': 'Department name (optional)',
                'is_active': 'Account status (true/false, defaults to true)'
            }
        )
        csv_file = default_template.generate_template_csv()
    
    response = HttpResponse(csv_file, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="user_import_template.csv"'
    return response

# AdminUserCreationLog Views
@method_decorator(admin_required, name='dispatch')
class AdminUserCreationLogListView(ListView):
    model = AdminUserCreationLog
    template_name = 'admin_user_creation_log_list.html'
    context_object_name = 'creation_logs'
    paginate_by = 20
    
    def get_queryset(self):
        # Admins can only see logs for their own institution unless they're superusers
        if self.request.user.is_superadmin:
            return AdminUserCreationLog.objects.select_related('created_by', 'institution')
        else:
            return AdminUserCreationLog.objects.filter(
                institution=self.request.user.institution
            ).select_related('created_by', 'institution')

@method_decorator(admin_required, name='dispatch')
class AdminUserCreationLogDetailView(DetailView):
    model = AdminUserCreationLog
    template_name = 'admin_user_creation_log_detail.html'
    context_object_name = 'creation_log'
    
    def dispatch(self, request, *args, **kwargs):
        # Admins can only view logs for their own institution unless they're superadmins
        obj = self.get_object()
        if not request.user.is_superadmin and obj.institution != request.user.institution:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

# UserImportTemplate Views
@method_decorator(admin_required, name='dispatch')
class UserImportTemplateListView(ListView):
    model = UserImportTemplate
    template_name = 'user_import_template_list.html'
    context_object_name = 'templates'
    paginate_by = 20
    
    def get_queryset(self):
        # Admins can only see templates for their own institution unless they're superadmins
        if self.request.user.is_superadmin:
            return UserImportTemplate.objects.filter(is_active=True)
        else:
            return UserImportTemplate.objects.filter(
                created_by__institution=self.request.user.institution,
                is_active=True
            )

@method_decorator(admin_required, name='dispatch')
class UserImportTemplateCreateView(CreateView):
    model = UserImportTemplate
    form_class = UserImportTemplateForm
    template_name = 'user_import_template_form.html'
    success_url = reverse_lazy('user_import_template_list')
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Template created successfully.')
        return super().form_valid(form)

@method_decorator(admin_required, name='dispatch')
class UserImportTemplateUpdateView(UpdateView):
    model = UserImportTemplate
    form_class = UserImportTemplateForm
    template_name = 'user_import_template_form.html'
    success_url = reverse_lazy('user_import_template_list')
    
    def dispatch(self, request, *args, **kwargs):
        # Admins can only edit templates for their own institution unless they're superadmins
        obj = self.get_object()
        if not request.user.is_superadmin and obj.created_by.institution != request.user.institution:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, 'Template updated successfully.')
        return super().form_valid(form)

@admin_required
def user_import_template_delete(request, pk):
    template = get_object_or_404(UserImportTemplate, pk=pk)
    
    # Check if admin has permission to delete this template
    if not request.user.is_superadmin and template.created_by.institution != request.user.institution:
        raise PermissionDenied
    
    template.is_active = False
    template.save()
    messages.success(request, 'Template deleted successfully.')
    return redirect('user_import_template_list')

# Academic Department Views
@method_decorator(admin_required, name='dispatch')
class AcademicDepartmentListView(ListView):
    model = AcademicDepartment
    template_name = 'academic_department_list.html'
    context_object_name = 'departments'
    paginate_by = 20
    
    def get_queryset(self):
        # Superadmins can see all departments, others only see departments in their institution
        if self.request.user.is_superadmin:
            return AcademicDepartment.objects.select_related('institution')
        else:
            return AcademicDepartment.objects.filter(
                institution=self.request.user.institution
            ).select_related('institution')

@method_decorator(admin_required, name='dispatch')
class AcademicDepartmentCreateView(CreateView):
    model = AcademicDepartment
    form_class = AcademicDepartmentForm
    template_name = 'academic_department_form.html'
    success_url = reverse_lazy('academic_department_list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # For non-superadmins, set the institution to their own
        if not self.request.user.is_superadmin:
            kwargs['initial'] = {'institution': self.request.user.institution}
        return kwargs
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # For non-superadmins, limit institution choices to their own and disable the field
        if not self.request.user.is_superadmin:
            form.fields['institution'].queryset = Institution.objects.filter(id=self.request.user.institution.id)
            form.fields['institution'].disabled = True
        return form
    
    def form_valid(self, form):
        # For non-superadmins, force the institution to be their own
        if not self.request.user.is_superadmin:
            form.instance.institution = self.request.user.institution
        
        messages.success(self.request, 'Department created successfully.')
        return super().form_valid(form)

@method_decorator(admin_required, name='dispatch')
class AcademicDepartmentUpdateView(UpdateView):
    model = AcademicDepartment
    form_class = AcademicDepartmentForm
    template_name = 'academic_department_form.html'
    success_url = reverse_lazy('academic_department_list')
    
    def dispatch(self, request, *args, **kwargs):
        # Admins can only edit departments in their institution unless they're superadmins
        obj = self.get_object()
        if not request.user.is_superadmin and obj.institution != request.user.institution:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # For non-superadmins, limit institution choices to their own and disable the field
        if not self.request.user.is_superadmin:
            form.fields['institution'].queryset = Institution.objects.filter(id=self.request.user.institution.id)
            form.fields['institution'].disabled = True
        return form
    
    def form_valid(self, form):
        # For non-superadmins, force the institution to be their own
        if not self.request.user.is_superadmin:
            form.instance.institution = self.request.user.institution
            
        messages.success(self.request, 'Department updated successfully.')
        return super().form_valid(form)

@admin_required
def academic_department_toggle_active(request, pk):
    department = get_object_or_404(AcademicDepartment, pk=pk)
    
    # Check permission
    if not request.user.is_superadmin and department.institution != request.user.institution:
        raise PermissionDenied
    
    department.is_active = not department.is_active
    department.save()
    
    action = "activated" if department.is_active else "deactivated"
    messages.success(request, f'Department {action} successfully.')
    
    return redirect('academic_department_list')

# Course Views
@method_decorator(login_required, name='dispatch')
class CourseListView(ListView):
    model = Course
    template_name = 'course_list.html'
    context_object_name = 'courses'
    paginate_by = 20
    
    def get_queryset(self):
        # Users can only see courses in their institution
        if self.request.user.is_superadmin:
            queryset = Course.objects.select_related('department')
        else:
            queryset = Course.objects.filter(
                department__institution=self.request.user.institution
            ).select_related('department')
        
        # Add filtering if needed
        department_id = self.request.GET.get('department')
        if department_id:
            queryset = queryset.filter(department_id=department_id)
            
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add departments for filtering
        if self.request.user.is_superadmin:
            context['departments'] = AcademicDepartment.objects.filter(is_active=True)
        else:
            context['departments'] = AcademicDepartment.objects.filter(
                institution=self.request.user.institution,
                is_active=True
            )
        return context

@method_decorator(instructor_required, name='dispatch')
class CourseCreateView(CreateView):
    model = Course
    form_class = CourseForm
    template_name = 'course_form.html'
    success_url = reverse_lazy('course_list')
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Filter departments to only those in the user's institution
        if not self.request.user.is_superadmin:
            form.fields['department'].queryset = AcademicDepartment.objects.filter(
                institution=self.request.user.institution,
                is_active=True
            )
        return form
    
    def form_valid(self, form):
        # For non-superadmins, ensure the department belongs to their institution
        if not self.request.user.is_superadmin and form.instance.department.institution != self.request.user.institution:
            raise PermissionDenied
            
        messages.success(self.request, 'Course created successfully.')
        return super().form_valid(form)

@method_decorator(instructor_required, name='dispatch')
class CourseUpdateView(UpdateView):
    model = Course
    form_class = CourseForm
    template_name = 'course_form.html'
    success_url = reverse_lazy('course_list')
    
    def dispatch(self, request, *args, **kwargs):
        # Users can only edit courses in their institution unless they're superadmins
        obj = self.get_object()
        if not request.user.is_superadmin and obj.department.institution != request.user.institution:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Filter departments to only those in the user's institution
        if not self.request.user.is_superadmin:
            form.fields['department'].queryset = AcademicDepartment.objects.filter(
                institution=self.request.user.institution,
                is_active=True
            )
        return form
    
    def form_valid(self, form):
        messages.success(self.request, 'Course updated successfully.')
        return super().form_valid(form)

@instructor_required
def course_toggle_active(request, pk):
    course = get_object_or_404(Course, pk=pk)
    
    # Check permission
    if not request.user.is_superadmin and course.department.institution != request.user.institution:
        raise PermissionDenied
    
    course.is_active = not course.is_active
    course.save()
    
    action = "activated" if course.is_active else "deactivated"
    messages.success(request, f'Course {action} successfully.')
    
    return redirect('course_list')

# Section Views
@method_decorator(login_required, name='dispatch')
class SectionListView(ListView):
    model = Section
    template_name = 'section_list.html'
    context_object_name = 'sections'
    paginate_by = 20
    
    def get_queryset(self):
        # Users can only see sections in their institution
        if self.request.user.is_superadmin:
            queryset = Section.objects.select_related('course', 'instructor')
        else:
            queryset = Section.objects.filter(
                course__department__institution=self.request.user.institution
            ).select_related('course', 'instructor')
        
        # Add filtering if needed
        course_id = self.request.GET.get('course')
        if course_id:
            queryset = queryset.filter(course_id=course_id)
            
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add courses for filtering
        if self.request.user.is_superadmin:
            context['courses'] = Course.objects.filter(is_active=True)
        else:
            context['courses'] = Course.objects.filter(
                department__institution=self.request.user.institution,
                is_active=True
            )
        return context

@method_decorator(instructor_required, name='dispatch')
class SectionCreateView(CreateView):
    model = Section
    form_class = SectionForm
    template_name = 'section_form.html'
    success_url = reverse_lazy('section_list')
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Filter courses to only those in the user's institution
        if not self.request.user.is_superadmin:
            form.fields['course'].queryset = Course.objects.filter(
                department__institution=self.request.user.institution,
                is_active=True
            )
            # Filter instructors to only those in the user's institution
            form.fields['instructor'].queryset = User.objects.filter(
                institution=self.request.user.institution,
                role__in=[User.Role.INSTRUCTOR, User.Role.ADMIN],
                is_active=True
            )
        return form
    
    def form_valid(self, form):
        # For non-superadmins, ensure the course and instructor belong to their institution
        if not self.request.user.is_superadmin:
            if (form.instance.course.department.institution != self.request.user.institution or
                form.instance.instructor.institution != self.request.user.institution):
                raise PermissionDenied
                
        messages.success(self.request, 'Section created successfully.')
        return super().form_valid(form)

@method_decorator(instructor_required, name='dispatch')
class SectionUpdateView(UpdateView):
    model = Section
    form_class = SectionForm
    template_name = 'section_form.html'
    success_url = reverse_lazy('section_list')
    
    def dispatch(self, request, *args, **kwargs):
        # Users can only edit sections in their institution unless they're superadmins
        obj = self.get_object()
        if not request.user.is_superadmin and obj.course.department.institution != request.user.institution:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Filter courses to only those in the user's institution
        if not self.request.user.is_superadmin:
            form.fields['course'].queryset = Course.objects.filter(
                department__institution=self.request.user.institution,
                is_active=True
            )
            # Filter instructors to only those in the user's institution
            form.fields['instructor'].queryset = User.objects.filter(
                institution=self.request.user.institution,
                role__in=[User.Role.INSTRUCTOR, User.Role.ADMIN],
                is_active=True
            )
        return form
    
    def form_valid(self, form):
        messages.success(self.request, 'Section updated successfully.')
        return super().form_valid(form)

@instructor_required
def section_toggle_active(request, pk):
    section = get_object_or_404(Section, pk=pk)
    
    # Check permission
    if not request.user.is_superadmin and section.course.department.institution != request.user.institution:
        raise PermissionDenied
    
    section.is_active = not section.is_active
    section.save()
    
    action = "activated" if section.is_active else "deactivated"
    messages.success(request, f'Section {action} successfully.')
    
    return redirect('section_list')

# Enrollment Views
@method_decorator(login_required, name='dispatch')
class EnrollmentListView(ListView):
    model = Enrollment
    template_name = 'enrollment_list.html'
    context_object_name = 'enrollments'
    paginate_by = 20
    
    def get_queryset(self):
        # Users can only see enrollments in their institution
        if self.request.user.is_superadmin:
            queryset = Enrollment.objects.select_related('student', 'section__course')
        else:
            queryset = Enrollment.objects.filter(
                section__course__department__institution=self.request.user.institution
            ).select_related('student', 'section__course')
        
        # Add filtering if needed
        section_id = self.request.GET.get('section')
        if section_id:
            queryset = queryset.filter(section_id=section_id)
            
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add sections for filtering
        if self.request.user.is_superadmin:
            context['sections'] = Section.objects.filter(is_active=True)
        else:
            context['sections'] = Section.objects.filter(
                course__department__institution=self.request.user.institution,
                is_active=True
            )
        return context

@method_decorator(instructor_required, name='dispatch')
class EnrollmentCreateView(CreateView):
    model = Enrollment
    form_class = EnrollmentForm
    template_name = 'enrollment_form.html'
    success_url = reverse_lazy('enrollment_list')
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Filter students to only those in the user's institution
        if not self.request.user.is_superadmin:
            form.fields['student'].queryset = User.objects.filter(
                institution=self.request.user.institution,
                role=User.Role.STUDENT,
                is_active=True
            )
            # Filter sections to only those in the user's institution
            form.fields['section'].queryset = Section.objects.filter(
                course__department__institution=self.request.user.institution,
                is_active=True
            )
        return form
    
    def form_valid(self, form):
        # For non-superadmins, ensure the student and section belong to their institution
        if not self.request.user.is_superadmin:
            if (form.instance.student.institution != self.request.user.institution or
                form.instance.section.course.department.institution != self.request.user.institution):
                raise PermissionDenied
                
        messages.success(self.request, 'Enrollment created successfully.')
        return super().form_valid(form)

@method_decorator(instructor_required, name='dispatch')
class EnrollmentUpdateView(UpdateView):
    model = Enrollment
    form_class = EnrollmentForm
    template_name = 'enrollment_form.html'
    success_url = reverse_lazy('enrollment_list')
    
    def dispatch(self, request, *args, **kwargs):
        # Users can only edit enrollments in their institution unless they're superadmins
        obj = self.get_object()
        if not request.user.is_superadmin and obj.section.course.department.institution != request.user.institution:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Filter students to only those in the user's institution
        if not self.request.user.is_superadmin:
            form.fields['student'].queryset = User.objects.filter(
                institution=self.request.user.institution,
                role=User.Role.STUDENT,
                is_active=True
            )
            # Filter sections to only those in the user's institution
            form.fields['section'].queryset = Section.objects.filter(
                course__department__institution=self.request.user.institution,
                is_active=True
            )
        return form
    
    def form_valid(self, form):
        messages.success(self.request, 'Enrollment updated successfully.')
        return super().form_valid(form)

@instructor_required
def enrollment_toggle_active(request, pk):
    enrollment = get_object_or_404(Enrollment, pk=pk)
    
    # Check permission
    if not request.user.is_superadmin and enrollment.section.course.department.institution != request.user.institution:
        raise PermissionDenied
    
    enrollment.is_active = not enrollment.is_active
    enrollment.save()
    action = "activated" if enrollment.is_active else "deactivated"
    messages.success(request, f'Enrollment {action} successfully.')
    
    return redirect('enrollment_list')

# Profile View
@login_required
def profile(request):
    if request.method == 'POST':
        form = UserForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('profile')
    else:
        form = UserForm(instance=request.user)
    
    return render(request, 'profile.html', {'form': form})

# Device Session Management
@login_required
def device_sessions(request):
    sessions = UserDeviceSession.objects.filter(
        user=request.user,
        is_active=True
    ).order_by('-last_activity')
    
    return render(request, 'device_sessions.html', {'sessions': sessions})

@login_required
def deactivate_device_session(request, pk):
    session = get_object_or_404(UserDeviceSession, pk=pk, user=request.user)
    session.deactivate()
    messages.success(request, 'Device session deactivated successfully.')
    return redirect('device_sessions')

# API Views for AJAX functionality
@login_required
def get_institution_departments(request, institution_id):
    # Check if user has permission to access this institution's data
    if not request.user.is_superadmin and int(institution_id) != request.user.institution.id:
        raise PermissionDenied
    
    departments = AcademicDepartment.objects.filter(
        institution_id=institution_id,
        is_active=True
    ).values('id', 'code', 'name')
    
    return JsonResponse(list(departments), safe=False)

@login_required
def get_department_courses(request, department_id):
    department = get_object_or_404(AcademicDepartment, id=department_id)
    
    # Check if user has permission to access this department's data
    if not request.user.is_superadmin and department.institution != request.user.institution:
        raise PermissionDenied
    
    courses = Course.objects.filter(
        department_id=department_id,
        is_active=True
    ).values('id', 'code', 'name')
    
    return JsonResponse(list(courses), safe=False)

@login_required
def get_course_sections(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    
    # Check if user has permission to access this course's data
    if not request.user.is_superadmin and course.department.institution != request.user.institution:
        raise PermissionDenied
    
    sections = Section.objects.filter(
        course_id=course_id,
        is_active=True
    ).values('id', 'section_code', 'term', 'year')
    
    return JsonResponse(list(sections), safe=False)
