# exams/urls.py
from django.urls import path
from . import views

app_name = 'exams'

urlpatterns = [
    # Exam URLs
    path('', views.ExamListView.as_view(), name='exam_list'),
    path('create/', views.ExamCreateView.as_view(), name='exam_create'),
    path('<int:pk>/', views.ExamDetailView.as_view(), name='exam_detail'),
    path('<int:pk>/update/', views.ExamUpdateView.as_view(), name='exam_update'),
    path('<int:pk>/delete/', views.ExamDeleteView.as_view(), name='exam_delete'),
    path('<int:pk>/toggle-status/', views.exam_toggle_status, name='exam_toggle_status'),
    path('<int:exam_id>/report/', views.exam_report, name='exam_report'),
    path('<int:exam_id>/export-results/', views.export_exam_results, name='export_exam_results'),
    
    # Question Bank URLs
    path('question-banks/', views.QuestionBankListView.as_view(), name='question_bank_list'),
    path('question-banks/create/', views.QuestionBankCreateView.as_view(), name='question_bank_create'),
    path('question-banks/<int:pk>/', views.QuestionBankDetailView.as_view(), name='question_bank_detail'),
    path('question-banks/<int:pk>/update/', views.QuestionBankUpdateView.as_view(), name='question_bank_update'),
    path('question-banks/<int:pk>/delete/', views.QuestionBankDeleteView.as_view(), name='question_bank_delete'),
    path('question-banks/<int:question_bank_id>/bulk-upload/', views.bulk_question_upload, name='bulk_question_upload'),
    
    # Question URLs
    path('questions/create/', views.QuestionCreateView.as_view(), name='question_create'),
    path('questions/<int:pk>/update/', views.QuestionUpdateView.as_view(), name='question_update'),
    path('questions/<int:pk>/delete/', views.QuestionDeleteView.as_view(), name='question_delete'),
    
    # Exam Attempt URLs
    path('attempts/', views.ExamAttemptListView.as_view(), name='exam_attempt_list'),
    path('attempts/<int:pk>/', views.ExamAttemptDetailView.as_view(), name='exam_attempt_detail'),
    path('attempts/<int:pk>/review/', views.ExamAttemptDetailView.as_view(), name='exam_attempt_review'),
    
    # Exam Taking URLs
    path('<int:exam_id>/start/', views.start_exam, name='start_exam'),
    path('attempts/<int:attempt_id>/take/', views.take_exam, name='take_exam'),
    path('attempts/<int:attempt_id>/password/', views.exam_password, name='exam_password'),
    path('attempts/<int:attempt_id>/submit/', views.submit_exam, name='submit_exam'),
    
    # Monitoring URLs
    path('monitoring/', views.monitoring_dashboard, name='monitoring_dashboard'),
    path('monitoring/<int:exam_id>/', views.monitoring_dashboard, name='monitoring_exam'),
    path('monitoring/attempts/<int:attempt_id>/', views.monitoring_detail, name='monitoring_detail'),
    path('webhook/proctoring/<int:attempt_id>/', views.proctoring_webhook, name='proctoring_webhook'),
    
    # API URLs
    path('api/exams/<int:exam_id>/questions/', views.api_exam_questions, name='api_exam_questions'),
    path('api/attempts/<int:attempt_id>/questions/<int:question_id>/save/', views.api_save_response, name='api_save_response'),
]

# Error handlers (if you want to keep them specific to the exams app)
handler404 = 'exams.views.handler404'
handler500 = 'exams.views.handler500'