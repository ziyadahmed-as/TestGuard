# core/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'core'

urlpatterns = [
    # Authentication URLs (using custom templates)
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='registration/logout.html'), name='logout'),
    path('password-change/', auth_views.PasswordChangeView.as_view(template_name='registration/password_change_form.html'), name='password_change'),
    path('password-change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name='password_change_done'),
    path('password-reset/', auth_views.PasswordResetView.as_view(template_name='registration/password_reset_form.html'), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'), name='password_reset_complete'),
    
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Profile
    path('profile/', views.profile, name='profile'),
    
    # Institution URLs
    path('institutions/', views.institution_list, name='institution_list'),
    path('institutions/create/', views.institution_create, name='institution_create'),
    path('institutions/<int:pk>/', views.institution_detail, name='institution_detail'),
    path('institutions/<int:pk>/edit/', views.institution_update, name='institution_update'),
    
    # User URLs
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:pk>/', views.user_detail, name='user_detail'),
    path('users/<int:pk>/edit/', views.user_update, name='user_update'),
    path('users/bulk-upload/', views.bulk_user_upload, name='bulk_user_upload'),
    path('users/creation-logs/', views.user_creation_logs, name='user_creation_logs'),
    
    # Department URLs
    path('departments/', views.department_list, name='department_list'),
    path('departments/create/', views.department_create, name='department_create'),
    path('departments/<int:pk>/', views.department_detail, name='department_detail'),
    path('departments/<int:pk>/edit/', views.department_update, name='department_update'),
    
    # Course URLs
    path('courses/', views.course_list, name='course_list'),
    path('courses/create/', views.course_create, name='course_create'),
    path('courses/<int:pk>/edit/', views.course_update, name='course_update'),
    
    # Section URLs
    path('sections/', views.section_list, name='section_list'),
    path('sections/create/', views.section_create, name='section_create'),
    path('sections/<int:pk>/edit/', views.section_update, name='section_update'),
    
    # Enrollment URLs
    path('enrollments/', views.enrollment_list, name='enrollment_list'),
    path('enrollments/create/', views.enrollment_create, name='enrollment_create'),
    path('enrollments/<int:pk>/edit/', views.enrollment_update, name='enrollment_update'),
    
    # API Endpoints
    path('api/institutions/<int:institution_id>/departments/', views.get_institution_departments, name='api_institution_departments'),
    path('api/departments/<int:department_id>/courses/', views.get_department_courses, name='api_department_courses'),
    path('api/courses/<int:course_id>/sections/', views.get_course_sections, name='api_course_sections'),
    
    # Export URLs
    path('export/users/csv/', views.export_users_csv, name='export_users_csv'),
    path('export/institutions/csv/', views.export_institutions_csv, name='export_institutions_csv'),
]