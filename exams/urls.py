# exams/urls.py
from django.urls import path
from . import views

app_name = 'exams'

urlpatterns = [
    # Exam management URLs
    path('', views.exam_list, name='exam_list'),
    path('create/', views.exam_create, name='exam_create'),
    path('<int:exam_id>/', views.exam_detail, name='exam_detail'),
    path('<int:exam_id>/edit/', views.exam_edit, name='exam_edit'),
    path('<int:exam_id>/questions/', views.exam_questions, name='exam_questions'),
    path('<int:exam_id>/questions/remove/<int:question_id>/', views.exam_question_remove, name='exam_question_remove'),
    path('<int:exam_id>/questions/reorder/', views.exam_question_reorder, name='exam_question_reorder'),
    path('<int:exam_id>/monitoring/', views.monitoring_events, name='monitoring_events'),
    
    # Exam taking URLs
    path('<int:exam_id>/start/', views.exam_attempt_start, name='exam_attempt_start'),
    path('attempt/<int:attempt_id>/password/', views.exam_password, name='exam_password'),
    path('attempt/<int:attempt_id>/take/', views.exam_take, name='exam_take'),
    path('attempt/<int:attempt_id>/review/', views.exam_review, name='exam_review'),
    path('attempt/<int:attempt_id>/submit/', views.exam_submit, name='exam_submit'),
    path('attempt/<int:attempt_id>/results/', views.exam_results, name='exam_results'),
    
    # AJAX URLs
    path('attempt/auto-save/', views.exam_auto_save, name='exam_auto_save'),
    path('attempt/log-event/', views.log_monitoring_event, name='log_monitoring_event'),
]