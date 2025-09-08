# exams/urls.py
from django.urls import path
from . import views

app_name = 'exams'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Exam URLs
    path('exams/', views.exam_list, name='exam_list'),
    path('exams/create/', views.exam_create, name='exam_create'),
    path('exams/<int:pk>/', views.exam_detail, name='exam_detail'),
    path('exams/<int:pk>/update/', views.exam_update, name='exam_update'),
    path('exams/<int:pk>/delete/', views.exam_delete, name='exam_delete'),
    
    # Exam Question Management
    path('exams/<int:exam_pk>/questions/', views.exam_question_manage, name='exam_question_manage'),
    path('exams/<int:exam_pk>/questions/<int:question_pk>/remove/', 
         views.exam_question_remove, name='exam_question_remove'),
    
    # Exam Attempt URLs
    path('exams/<int:exam_pk>/start/', views.exam_start, name='exam_start'),
    path('attempts/<int:attempt_pk>/take/', views.exam_take, name='exam_take'),
    path('attempts/<int:attempt_pk>/results/', views.exam_results, name='exam_results'),
    
    # Question Bank URLs
    path('question-banks/', views.question_bank_list, name='question_bank_list'),
    path('question-banks/create/', views.question_bank_create, name='question_bank_create'),
    path('question-banks/<int:pk>/', views.question_bank_detail, name='question_bank_detail'),
    
    # Bulk Import
    path('bulk-import/', views.bulk_question_import, name='bulk_question_import'),
    
    # Monitoring URLs
    path('monitoring/', views.monitoring_events, name='monitoring_events'),
    path('monitoring/<int:pk>/review/', views.monitoring_event_review, name='monitoring_event_review'),
    
    # API URLs
    path('api/save-draft/<int:attempt_pk>/<int:question_pk>/', 
         views.save_response_draft, name='save_response_draft'),
    path('api/time-remaining/<int:attempt_pk>/', 
         views.exam_time_remaining, name='exam_time_remaining'),
]

# Error handlers
handler404 = 'exams.views.handler404'
handler500 = 'exams.views.handler500'