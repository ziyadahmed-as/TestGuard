from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count, Sum
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import (
    BulkQuestionImport, QuestionBank, Question, Exam, 
    ExamQuestion, ExamAttempt, QuestionResponse, MonitoringEvent, UserDeviceSession
)
from .forms import (
    BulkQuestionImportForm, QuestionBankForm, QuestionForm, ExamForm,
    ExamQuestionForm, ExamAttemptStartForm, QuestionResponseForm,
    MonitoringEventReviewForm, ExamSearchForm, QuestionFilterForm
)
from core.models import User, Section, Institution
import json
import csv

# Helper functions for role checking
def is_instructor(user):
    return user.is_authenticated and user.role == User.Role.INSTRUCTOR

def is_student(user):
    return user.is_authenticated and user.role == User.Role.STUDENT

def is_admin_or_instructor(user):
    return user.is_authenticated and (user.role == User.Role.ADMIN or user.role == User.Role.INSTRUCTOR)

# Dashboard View
@login_required
def dashboard(request):
    """Dashboard view with statistics and recent activities"""
    context = {}
    
    # Common stats for all users
    context['stats'] = {
        'total_exams': Exam.objects.count(),
        'active_attempts': ExamAttempt.objects.filter(status=ExamAttempt.Status.IN_PROGRESS).count(),
        'completed_attempts': ExamAttempt.objects.filter(
            status__in=[ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.AUTO_SUBMITTED]
        ).count(),
        'pending_reviews': MonitoringEvent.objects.filter(reviewed_status=MonitoringEvent.ReviewedStatus.PENDING).count(),
    }
    
    # Upcoming exams (next 7 days)
    context['upcoming_exams'] = Exam.objects.filter(
        start_date__gte=timezone.now(),
        start_date__lte=timezone.now() + timezone.timedelta(days=7)
    ).order_by('start_date')[:5]
    
    # Recent exam attempts
    if request.user.role in [User.Role.ADMIN, User.Role.INSTRUCTOR]:
        context['recent_attempts'] = ExamAttempt.objects.select_related(
            'student', 'exam'
        ).order_by('-start_time')[:5]
    else:
        context['recent_attempts'] = ExamAttempt.objects.filter(
            student=request.user
        ).select_related('exam').order_by('-start_time')[:5]
    
    # Monitoring events
    if request.user.role in [User.Role.ADMIN, User.Role.INSTRUCTOR]:
        if request.user.role == User.Role.ADMIN:
            context['monitoring_events'] = MonitoringEvent.objects.select_related(
                'attempt', 'attempt__student', 'attempt__exam'
            ).order_by('-timestamp')[:5]
        else:
            # Instructors only see events for their exams
            instructor_exams = Exam.objects.filter(created_by=request.user)
            context['monitoring_events'] = MonitoringEvent.objects.filter(
                attempt__exam__in=instructor_exams
            ).select_related('attempt', 'attempt__student', 'attempt__exam').order_by('-timestamp')[:5]
    else:
        context['monitoring_events'] = MonitoringEvent.objects.filter(
            attempt__student=request.user
        ).select_related('attempt', 'attempt__exam').order_by('-timestamp')[:5]
    
    # Student-specific stats
    if request.user.role == User.Role.STUDENT:
        student_attempts = ExamAttempt.objects.filter(student=request.user)
        completed_attempts = student_attempts.filter(
            status__in=[ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.AUTO_SUBMITTED]
        )
        
        # Calculate average score
        scores = [attempt.score for attempt in completed_attempts if attempt.score is not None]
        average_score = sum(scores) / len(scores) if scores else 0
        
        context['student_stats'] = {
            'upcoming_exams': Exam.objects.filter(
                sections__students=request.user,
                start_date__gte=timezone.now()
            ).distinct().count(),
            'completed_exams': completed_attempts.count(),
            'average_score': round(average_score, 1),
        }
    
    return render(request, 'exams/dashboard.html', context)

# Exam Views
@login_required
def exam_list(request):
    """List exams based on user role"""
    form = ExamSearchForm(request.GET or None)
    
    if request.user.role == User.Role.ADMIN:
        exams = Exam.objects.all()
    elif request.user.role == User.Role.INSTRUCTOR:
        exams = Exam.objects.filter(created_by=request.user)
    elif request.user.role == User.Role.STUDENT:
        # Get exams for sections the student is enrolled in
        exams = Exam.objects.filter(
            sections__students=request.user,
            status=Exam.Status.LIVE
        ).distinct()
    else:
        exams = Exam.objects.none()
    
    # Apply filters
    if form.is_valid():
        if form.cleaned_data.get('title'):
            exams = exams.filter(title__icontains=form.cleaned_data['title'])
        if form.cleaned_data.get('status'):
            exams = exams.filter(status=form.cleaned_data['status'])
        if form.cleaned_data.get('date_from'):
            exams = exams.filter(start_date__gte=form.cleaned_data['date_from'])
        if form.cleaned_data.get('date_to'):
            exams = exams.filter(end_date__lte=form.cleaned_data['date_to'])
    
    paginator = Paginator(exams, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'exams/exam_list.html', {
        'page_obj': page_obj,
        'form': form,
        'status_choices': Exam.Status.choices
    })

@login_required
@user_passes_test(is_admin_or_instructor)
def exam_create(request):
    """Create a new exam"""
    if request.method == 'POST':
        form = ExamForm(request.POST, user=request.user)
        if form.is_valid():
            exam = form.save(commit=False)
            exam.created_by = request.user
            exam.save()
            form.save_m2m()  # Save sections
            messages.success(request, f'Exam "{exam.title}" created successfully.')
            return redirect('exam_detail', pk=exam.pk)
    else:
        form = ExamForm(user=request.user)
    
    return render(request, 'exams/exam_form.html', {
        'form': form,
        'title': 'Create Exam',
        'submit_text': 'Create Exam'
    })

@login_required
@user_passes_test(is_admin_or_instructor)
def exam_update(request, pk):
    """Update an existing exam"""
    exam = get_object_or_404(Exam, pk=pk)
    
    # Check permission
    if request.user.role == User.Role.INSTRUCTOR and exam.created_by != request.user:
        raise PermissionDenied("You don't have permission to edit this exam.")
    
    if request.method == 'POST':
        form = ExamForm(request.POST, instance=exam, user=request.user)
        if form.is_valid():
            exam = form.save()
            messages.success(request, f'Exam "{exam.title}" updated successfully.')
            return redirect('exam_detail', pk=exam.pk)
    else:
        form = ExamForm(instance=exam, user=request.user)
    
    return render(request, 'exams/exam_form.html', {
        'form': form,
        'title': f'Update {exam.title}',
        'submit_text': 'Update Exam'
    })

@login_required
def exam_detail(request, pk):
    """View exam details"""
    exam = get_object_or_404(Exam, pk=pk)
    
    # Check permission based on role
    if request.user.role == User.Role.INSTRUCTOR and exam.created_by != request.user:
        raise PermissionDenied("You don't have permission to view this exam.")
    elif request.user.role == User.Role.STUDENT:
        # Check if student has access to this exam
        if not exam.sections.filter(students=request.user).exists():
            raise PermissionDenied("You don't have access to this exam.")
    
    # Get exam questions
    exam_questions = exam.exam_questions.select_related('question').order_by('order')
    
    # Get statistics for instructors/admins
    stats = None
    if request.user.role in [User.Role.INSTRUCTOR, User.Role.ADMIN]:
        stats = {
            'total_attempts': exam.attempts.count(),
            'completed_attempts': exam.attempts.filter(
                status__in=[ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.AUTO_SUBMITTED]
            ).count(),
            'average_score': exam.attempts.filter(
                status__in=[ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.AUTO_SUBMITTED]
            ).aggregate(avg_score=Sum('score'))['avg_score'],
            'in_progress': exam.attempts.filter(status=ExamAttempt.Status.IN_PROGRESS).count(),
        }
    
    return render(request, 'exams/exam_detail.html', {
        'exam': exam,
        'exam_questions': exam_questions,
        'stats': stats,
        'is_instructor': request.user.role in [User.Role.INSTRUCTOR, User.Role.ADMIN]
    })

@login_required
@user_passes_test(is_admin_or_instructor)
def exam_delete(request, pk):
    """Delete an exam"""
    exam = get_object_or_404(Exam, pk=pk)
    
    # Check permission
    if request.user.role == User.Role.INSTRUCTOR and exam.created_by != request.user:
        raise PermissionDenied("You don't have permission to delete this exam.")
    
    if request.method == 'POST':
        exam_title = exam.title
        exam.delete()
        messages.success(request, f'Exam "{exam_title}" deleted successfully.')
        return redirect('exam_list')
    
    return render(request, 'exams/exam_confirm_delete.html', {'exam': exam})

# Exam Question Management
@login_required
@user_passes_test(is_admin_or_instructor)
def exam_question_manage(request, exam_pk):
    """Manage questions for an exam"""
    exam = get_object_or_404(Exam, pk=exam_pk)
    
    # Check permission
    if request.user.role == User.Role.INSTRUCTOR and exam.created_by != request.user:
        raise PermissionDenied("You don't have permission to manage questions for this exam.")
    
    if request.method == 'POST':
        form = ExamQuestionForm(request.POST, exam=exam)
        if form.is_valid():
            exam_question = form.save(commit=False)
            exam_question.exam = exam
            exam_question.save()
            messages.success(request, 'Question added to exam successfully.')
            return redirect('exam_question_manage', exam_pk=exam.pk)
    else:
        form = ExamQuestionForm(exam=exam)
    
    # Get existing exam questions
    exam_questions = exam.exam_questions.select_related('question').order_by('order')
    
    return render(request, 'exams/exam_question_manage.html', {
        'exam': exam,
        'form': form,
        'exam_questions': exam_questions
    })

@login_required
@user_passes_test(is_admin_or_instructor)
def exam_question_remove(request, exam_pk, question_pk):
    """Remove a question from an exam"""
    exam_question = get_object_or_404(ExamQuestion, exam_id=exam_pk, pk=question_pk)
    exam = exam_question.exam
    
    # Check permission
    if request.user.role == User.Role.INSTRUCTOR and exam.created_by != request.user:
        raise PermissionDenied("You don't have permission to manage questions for this exam.")
    
    if request.method == 'POST':
        exam_question.delete()
        messages.success(request, 'Question removed from exam successfully.')
    
    return redirect('exam_question_manage', exam_pk=exam.pk)

# Exam Attempt Views
@login_required
@user_passes_test(is_student)
def exam_start(request, exam_pk):
    """Start an exam attempt"""
    exam = get_object_or_404(Exam, pk=exam_pk)
    
    # Check if student has access to this exam
    if not exam.sections.filter(students=request.user).exists():
        raise PermissionDenied("You don't have access to this exam.")
    
    # Check if exam is available
    if not exam.is_active:
        messages.error(request, "This exam is not currently available.")
        return redirect('exam_list')
    
    # Check if student has remaining attempts
    attempt_count = ExamAttempt.objects.filter(exam=exam, student=request.user).count()
    if attempt_count >= exam.max_attempts:
        messages.error(request, "You have reached the maximum number of attempts for this exam.")
        return redirect('exam_list')
    
    # Handle password authentication if required
    if exam.requires_password and request.method == 'POST':
        form = ExamAttemptStartForm(request.POST, exam=exam)
        if form.is_valid():
            # Password is validated in form clean method
            return _create_exam_attempt(request, exam)
    else:
        form = ExamAttemptStartForm(exam=exam)
    
    return render(request, 'exams/exam_start.html', {
        'exam': exam,
        'form': form,
        'requires_password': exam.requires_password
    })

def _create_exam_attempt(request, exam):
    """Helper function to create exam attempt"""
    # Create device session (simplified - in real app, use proper device fingerprinting)
    device_session, created = UserDeviceSession.objects.get_or_create(
        user=request.user,
        defaults={
            'device_hash': f"web_{request.META.get('REMOTE_ADDR', 'unknown')}",
            'browser_name': request.META.get('HTTP_USER_AGENT', '')[:100],
            'ip_address': request.META.get('REMOTE_ADDR', ''),
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:500],
        }
    )
    
    # Create exam attempt
    attempt = ExamAttempt.objects.create(
        exam=exam,
        student=request.user,
        device_session=device_session,
        ip_address=request.META.get('REMOTE_ADDR', ''),
        status=ExamAttempt.Status.IN_PROGRESS,
        start_time=timezone.now()
    )
    
    # Create empty responses for all questions
    for exam_question in exam.exam_questions.all():
        QuestionResponse.objects.create(
            attempt=attempt,
            question=exam_question.question,
            points_awarded=0
        )
    
    return redirect('exam_take', attempt_pk=attempt.pk)

@login_required
@user_passes_test(is_student)
def exam_take(request, attempt_pk):
    """Take an exam - the main exam interface"""
    attempt = get_object_or_404(ExamAttempt, pk=attempt_pk, student=request.user)
    
    # Check if attempt is in progress
    if attempt.status != ExamAttempt.Status.IN_PROGRESS:
        messages.error(request, "This exam attempt is not in progress.")
        return redirect('exam_list')
    
    # Check time remaining
    time_remaining = attempt.time_remaining
    if time_remaining <= 0:
        attempt.status = ExamAttempt.Status.AUTO_SUBMITTED
        attempt.end_time = timezone.now()
        attempt.save()
        messages.error(request, "Exam time has expired.")
        return redirect('exam_list')
    
    # Get questions and responses
    responses = attempt.responses.select_related('question').order_by('question__examquestion__order')
    
    # Handle form submission
    if request.method == 'POST':
        question_id = request.POST.get('question_id')
        if question_id:
            response = get_object_or_404(QuestionResponse, attempt=attempt, question_id=question_id)
            form = QuestionResponseForm(request.POST, instance=response, question=response.question)
            if form.is_valid():
                if 'save_draft' in request.POST:
                    response.save_draft(form.cleaned_data['student_answer'])
                    messages.success(request, "Answer saved as draft.")
                else:
                    response.finalize_answer(form.cleaned_data['student_answer'])
                    messages.success(request, "Answer submitted.")
                
                # Check if all questions are answered
                unanswered = attempt.responses.filter(is_submitted=False).count()
                if unanswered == 0 and 'submit_exam' in request.POST:
                    attempt.status = ExamAttempt.Status.SUBMITTED
                    attempt.end_time = timezone.now()
                    attempt.save()
                    messages.success(request, "Exam submitted successfully!")
                    return redirect('exam_results', attempt_pk=attempt.pk)
                
                return redirect('exam_take', attempt_pk=attempt.pk)
        else:
            messages.error(request, "Invalid question.")
    
    # Get current question (first unanswered or specified question)
    current_question_id = request.GET.get('question')
    if current_question_id:
        current_response = get_object_or_404(QuestionResponse, attempt=attempt, question_id=current_question_id)
    else:
        # Find first unanswered question
        current_response = attempt.responses.filter(is_submitted=False).first()
        if not current_response:
            current_response = attempt.responses.first()
    
    form = QuestionResponseForm(instance=current_response, question=current_response.question)
    
    return render(request, 'exams/exam_take.html', {
        'attempt': attempt,
        'responses': responses,
        'current_response': current_response,
        'form': form,
        'time_remaining': time_remaining,
        'allow_backtracking': attempt.exam.allow_backtracking
    })

@login_required
@user_passes_test(is_student)
def exam_results(request, attempt_pk):
    """View exam results"""
    attempt = get_object_or_404(ExamAttempt, pk=attempt_pk, student=request.user)
    
    # Only show results for completed attempts
    if attempt.status not in [ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.AUTO_SUBMITTED]:
        messages.error(request, "Exam results are not available yet.")
        return redirect('exam_list')
    
    # Calculate score if not already calculated
    if attempt.score is None:
        total_points = sum(r.points_awarded or 0 for r in attempt.responses.all())
        max_points = sum(eq.points for eq in attempt.exam.exam_questions.all())
        attempt.score = (total_points / max_points * 100) if max_points > 0 else 0
        attempt.save()
    
    responses = attempt.responses.select_related('question').order_by('question__examquestion__order')
    
    return render(request, 'exams/exam_results.html', {
        'attempt': attempt,
        'responses': responses,
        'passed': attempt.score >= attempt.exam.pass_percentage
    })

# Question Bank Views
@login_required
@user_passes_test(is_admin_or_instructor)
def question_bank_list(request):
    """List question banks"""
    if request.user.role == User.Role.ADMIN:
        question_banks = QuestionBank.objects.all()
    else:
        question_banks = QuestionBank.objects.filter(
            Q(created_by=request.user) | Q(is_public=True) | Q(is_global=True)
        )
    
    return render(request, 'exams/question_bank_list.html', {
        'question_banks': question_banks
    })

@login_required
@user_passes_test(is_admin_or_instructor)
def question_bank_detail(request, pk):
    """View question bank details"""
    question_bank = get_object_or_404(QuestionBank, pk=pk)
    
    # Check permission
    if (request.user.role == User.Role.INSTRUCTOR and 
        question_bank.created_by != request.user and
        not question_bank.is_public and
        not question_bank.is_global):
        raise PermissionDenied("You don't have permission to view this question bank.")
    
    form = QuestionFilterForm(request.GET or None)
    questions = question_bank.questions.all()
    
    if form.is_valid():
        if form.cleaned_data.get('question_text'):
            questions = questions.filter(question_text__icontains=form.cleaned_data['question_text'])
        if form.cleaned_data.get('type'):
            questions = questions.filter(type=form.cleaned_data['type'])
        if form.cleaned_data.get('learning_objective'):
            questions = questions.filter(learning_objective__icontains=form.cleaned_data['learning_objective'])
        if form.cleaned_data.get('is_active') is not None:
            questions = questions.filter(is_active=form.cleaned_data['is_active'])
    
    paginator = Paginator(questions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'exams/question_bank_detail.html', {
        'question_bank': question_bank,
        'page_obj': page_obj,
        'form': form,
        'type_choices': Question.Type.choices
    })

@login_required
@user_passes_test(is_admin_or_instructor)
def question_bank_create(request):
    """Create a new question bank"""
    if request.method == 'POST':
        form = QuestionBankForm(request.POST, user=request.user)
        if form.is_valid():
            question_bank = form.save(commit=False)
            question_bank.created_by = request.user
            question_bank.save()
            messages.success(request, f'Question bank "{question_bank.name}" created successfully.')
            return redirect('question_bank_detail', pk=question_bank.pk)
    else:
        form = QuestionBankForm(user=request.user)
    
    return render(request, 'exams/question_bank_form.html', {
        'form': form,
        'title': 'Create Question Bank',
        'submit_text': 'Create Question Bank'
    })

# Bulk Question Import Views
@login_required
@user_passes_test(is_admin_or_instructor)
def bulk_question_import(request):
    """Bulk import questions from Excel"""
    if request.method == 'POST':
        form = BulkQuestionImportForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            import_obj = form.save(commit=False)
            import_obj.uploaded_by = request.user
            import_obj.save()
            
            # Process import in background (in real app, use Celery or similar)
            import_obj.process_import()
            
            messages.success(request, f'Import completed with {import_obj.successful_imports} successes and {import_obj.failed_imports} failures.')
            return redirect('question_bank_detail', pk=import_obj.question_bank.pk)
    else:
        form = BulkQuestionImportForm(user=request.user)
    
    return render(request, 'exams/bulk_question_import.html', {'form': form})

# Monitoring Views
@login_required
@user_passes_test(is_admin_or_instructor)
def monitoring_events(request):
    """List monitoring events for review"""
    if request.user.role == User.Role.ADMIN:
        events = MonitoringEvent.objects.all()
    else:
        # Instructors can only see events for their exams
        instructor_exams = Exam.objects.filter(created_by=request.user)
        events = MonitoringEvent.objects.filter(attempt__exam__in=instructor_exams)
    
    events = events.select_related('attempt', 'attempt__exam', 'attempt__student').order_by('-timestamp')
    
    paginator = Paginator(events, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'exams/monitoring_events.html', {
        'page_obj': page_obj,
        'review_status_choices': MonitoringEvent.ReviewedStatus.choices
    })

@login_required
@user_passes_test(is_admin_or_instructor)
def monitoring_event_review(request, pk):
    """Review a monitoring event"""
    event = get_object_or_404(MonitoringEvent, pk=pk)
    
    # Check permission
    if (request.user.role == User.Role.INSTRUCTOR and 
        event.attempt.exam.created_by != request.user):
        raise PermissionDenied("You don't have permission to review this event.")
    
    if request.method == 'POST':
        form = MonitoringEventReviewForm(request.POST, instance=event)
        if form.is_valid():
            event = form.save(commit=False)
            event.reviewed_by = request.user
            event.reviewed_at = timezone.now()
            event.save()
            messages.success(request, 'Event review completed.')
            return redirect('monitoring_events')
    else:
        form = MonitoringEventReviewForm(instance=event)
    
    return render(request, 'exams/monitoring_event_review.html', {
        'event': event,
        'form': form
    })

# API Views
@login_required
@csrf_exempt
@require_POST
def save_response_draft(request, attempt_pk, question_pk):
    """API endpoint to save response draft (for auto-save)"""
    attempt = get_object_or_404(ExamAttempt, pk=attempt_pk, student=request.user)
    
    if attempt.status != ExamAttempt.Status.IN_PROGRESS:
        return JsonResponse({'error': 'Exam attempt is not in progress'}, status=400)
    
    response = get_object_or_404(QuestionResponse, attempt=attempt, question_id=question_pk)
    
    try:
        data = json.loads(request.body)
        answer_data = data.get('answer')
        
        response.save_draft(answer_data)
        
        return JsonResponse({
            'success': True,
            'auto_save_count': response.auto_save_count,
            'last_auto_save': response.last_auto_save.isoformat() if response.last_auto_save else None
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@login_required
def exam_time_remaining(request, attempt_pk):
    """API endpoint to get time remaining"""
    attempt = get_object_or_404(ExamAttempt, pk=attempt_pk, student=request.user)
    
    if attempt.status != ExamAttempt.Status.IN_PROGRESS:
        return JsonResponse({'error': 'Exam attempt is not in progress'}, status=400)
    
    return JsonResponse({
        'time_remaining': attempt.time_remaining,
        'status': attempt.status
    })

# Error handling
def handler404(request, exception):
    return render(request, 'exams/404.html', status=404)

def handler500(request):
    return render(request, 'exams/500.html', status=500)