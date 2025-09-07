from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import views

app_name = 'core'

urlpatterns = [
    # Authentication URLs
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # Dashboard and Profile
    path('', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
    
    # Institution URLs
    path('institutions/', views.InstitutionListView.as_view(), name='institution_list'),
    path('institutions/create/', views.InstitutionCreateView.as_view(), name='institution_create'),
    path('institutions/<int:pk>/', views.InstitutionDetailView.as_view(), name='institution_detail'),
    path('institutions/<int:pk>/update/', views.InstitutionUpdateView.as_view(), name='institution_update'),
    path('institutions/<int:pk>/toggle-active/', views.institution_toggle_active, name='institution_toggle_active'),
    
    # User URLs
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/', views.UserDetailView.as_view(), name='user_detail'),
    path('users/<int:pk>/update/', views.UserUpdateView.as_view(), name='user_update'),
    path('users/<int:pk>/toggle-active/', views.user_toggle_active, name='user_toggle_active'),
    path('users/bulk-upload/', views.bulk_user_upload, name='bulk_user_upload'),
    path('users/download-template/', views.download_import_template, name='download_import_template'),
    path('users/download-template/<int:template_id>/', views.download_import_template, name='download_specific_template'),
    
    # Admin User Creation Log URLs
    path('user-creation-logs/', views.AdminUserCreationLogListView.as_view(), name='admin_user_creation_log_list'),
    path('user-creation-logs/<int:pk>/', views.AdminUserCreationLogDetailView.as_view(), name='admin_user_creation_log_detail'),
    
    # User Import Template URLs
    path('user-templates/', views.UserImportTemplateListView.as_view(), name='user_import_template_list'),
    path('user-templates/create/', views.UserImportTemplateCreateView.as_view(), name='user_import_template_create'),
    path('user-templates/<int:pk>/update/', views.UserImportTemplateUpdateView.as_view(), name='user_import_template_update'),
    path('user-templates/<int:pk>/delete/', views.user_import_template_delete, name='user_import_template_delete'),
    
    # Academic Department URLs
    path('departments/', views.AcademicDepartmentListView.as_view(), name='academic_department_list'),
    path('departments/create/', views.AcademicDepartmentCreateView.as_view(), name='academic_department_create'),
    path('departments/<int:pk>/update/', views.AcademicDepartmentUpdateView.as_view(), name='academic_department_update'),
    path('departments/<int:pk>/toggle-active/', views.academic_department_toggle_active, name='academic_department_toggle_active'),
    
    # Course URLs
    path('courses/', views.CourseListView.as_view(), name='course_list'),
    path('courses/create/', views.CourseCreateView.as_view(), name='course_create'),
    path('courses/<int:pk>/update/', views.CourseUpdateView.as_view(), name='course_update'),
    path('courses/<int:pk>/toggle-active/', views.course_toggle_active, name='course_toggle_active'),
    
    # Section URLs
    path('sections/', views.SectionListView.as_view(), name='section_list'),
    path('sections/create/', views.SectionCreateView.as_view(), name='section_create'),
    path('sections/<int:pk>/update/', views.SectionUpdateView.as_view(), name='section_update'),
    path('sections/<int:pk>/toggle-active/', views.section_toggle_active, name='section_toggle_active'),
    
    # Enrollment URLs
    path('enrollments/', views.EnrollmentListView.as_view(), name='enrollment_list'),
    path('enrollments/create/', views.EnrollmentCreateView.as_view(), name='enrollment_create'),
    path('enrollments/<int:pk>/update/', views.EnrollmentUpdateView.as_view(), name='enrollment_update'),
    path('enrollments/<int:pk>/toggle-active/', views.enrollment_toggle_active, name='enrollment_toggle_active'),
    
    # Device Session URLs
    path('device-sessions/', views.device_sessions, name='device_sessions'),
    path('device-sessions/<int:pk>/deactivate/', views.deactivate_device_session, name='deactivate_device_session'),
    
    # Exam Session URLs
    path('exam-sessions/', views.active_exam_sessions, name='active_exam_sessions'),
    path('exam-sessions/<int:pk>/terminate/', views.terminate_exam_session, name='terminate_exam_session'),
    
    # API URLs for AJAX calls
    path('api/institution/<int:institution_id>/departments/', views.get_institution_departments, name='api_institution_departments'),
    path('api/department/<int:department_id>/courses/', views.get_department_courses, name='api_department_courses'),
    path('api/course/<int:course_id>/sections/', views.get_course_sections, name='api_course_sections'),
]

# Password reset URLs (if needed)
urlpatterns += [
    path('password-reset/', 
         auth_views.PasswordResetView.as_view(
             template_name='registration/password_reset.html',
             email_template_name='registration/password_reset_email.html',
             subject_template_name='registration/password_reset_subject.txt'
         ),
         name='password_reset'),
    path('password-reset/done/', 
         auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'),
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'),
         name='password_reset_confirm'),
    path('password-reset-complete/', 
         auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'),
         name='password_reset_complete'),
]