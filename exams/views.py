from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.utils.decorators import method_decorator
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count, Sum, Avg, F, ExpressionWrapper, DurationField,Max, Min
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms import modelformset_factory
from django.conf import settings
import json
import csv
from datetime import timedelta

from core.models import User, Institution, AcademicDepartment, Course, Section, Enrollment, UserDeviceSession
from .models import (
    Exam, Question, QuestionBank, ExamAttempt, ExamSession, 
    QuestionResponse, ExamConfiguration, ProctoringEvent
)

from .forms import (
    ExamForm, QuestionForm, QuestionBankForm, ExamConfigurationForm,
    BulkQuestionUploadForm, ExamAttemptReviewForm, ProctoringSettingsForm
)

# Utility functions (same as core)
def is_superadmin(user):
    return user.is_authenticated and user.role == User.Role.SUPERADMIN

def is_admin(user):
    return user.is_authenticated and user.role == User.Role.ADMIN

def is_instructor(user):
    return user.is_authenticated and user.role == User.Role.INSTRUCTOR

def is_student(user):
    return user.is_authenticated and user.role == User.Role.STUDENT

def instructor_required(view_func):
    decorated_view_func = login_required(user_passes_test(
        lambda u: is_instructor(u) or is_admin(u) or is_superadmin(u),
        login_url='login',
        redirect_field_name=None
    )(view_func))
    return decorated_view_func

def student_required(view_func):
    decorated_view_func = login_required(user_passes_test(
        is_student,
        login_url='login',
        redirect_field_name=None
    )(view_func))
    return decorated_view_func

# Exam Views
@method_decorator(login_required, name='dispatch')
class ExamListView(ListView):
    model = Exam
    template_name = 'exams/exam_list.html'
    context_object_name = 'exams'
    paginate_by = 20
    
    def get_queryset(self):
        if self.request.user.is_superadmin:
            queryset = Exam.objects.select_related('course', 'created_by')
        elif self.request.user.is_admin or self.request.user.is_instructor:
            queryset = Exam.objects.filter(
                course__department__institution=self.request.user.institution
            ).select_related('course', 'created_by')
        else:  # Student
            queryset = Exam.objects.filter(
                course__sections__enrollments__student=self.request.user,
                course__sections__enrollments__is_active=True,
                is_published=True
            ).select_related('course', 'created_by').distinct()
        
        # Filtering
        course_id = self.request.GET.get('course')
        status = self.request.GET.get('status')
        
        if course_id:
            queryset = queryset.filter(course_id=course_id)
        if status:
            if status == 'active':
                queryset = queryset.filter(is_published=True, start_time__lte=timezone.now(), end_time__gte=timezone.now())
            elif status == 'upcoming':
                queryset = queryset.filter(is_published=True, start_time__gt=timezone.now())
            elif status == 'completed':
                queryset = queryset.filter(end_time__lt=timezone.now())
            elif status == 'draft':
                queryset = queryset.filter(is_published=False)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        if self.request.user.is_educator:
            if self.request.user.is_superadmin:
                context['courses'] = Course.objects.all()
            else:
                context['courses'] = Course.objects.filter(
                    department__institution=self.request.user.institution
                )
        
        return context

@method_decorator(instructor_required, name='dispatch')
class ExamCreateView(CreateView):
    model = Exam
    form_class = ExamForm
    template_name = 'exams/exam_form.html'
    
    def get_success_url(self):
        return reverse('exams:exam_detail', kwargs={'pk': self.object.pk})
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Exam created successfully.')
        return super().form_valid(form)

@method_decorator(login_required, name='dispatch')
class ExamDetailView(DetailView):
    model = Exam
    template_name = 'exams/exam_detail.html'
    context_object_name = 'exam'
    
    def dispatch(self, request, *args, **kwargs):
        exam = self.get_object()
        
        # Check permissions
        if request.user.is_student and (not exam.is_published or exam.end_time < timezone.now()):
            raise PermissionDenied("You don't have permission to view this exam.")
        
        if request.user.is_educator and not request.user.is_superadmin:
            if exam.course.department.institution != request.user.institution:
                raise PermissionDenied("You don't have permission to view this exam.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        if self.request.user.is_educator:
            # Add statistics for instructors
            attempts = ExamAttempt.objects.filter(exam=self.object)
            context['attempt_count'] = attempts.count()
            context['completed_count'] = attempts.filter(status='completed').count()
            context['in_progress_count'] = attempts.filter(status='in_progress').count()
            
            if context['completed_count'] > 0:
                context['avg_score'] = attempts.filter(status='completed').aggregate(
                    avg_score=Avg('score')
                )['avg_score']
            
            # Add question statistics
            context['question_stats'] = []
            for question in self.object.questions.all():
                responses = QuestionResponse.objects.filter(
                    question=question, 
                    attempt__exam=self.object,
                    attempt__status='completed'
                )
                correct_count = responses.filter(is_correct=True).count()
                total_count = responses.count()
                
                if total_count > 0:
                    accuracy = (correct_count / total_count) * 100
                else:
                    accuracy = 0
                
                context['question_stats'].append({
                    'question': question,
                    'total_responses': total_count,
                    'correct_responses': correct_count,
                    'accuracy': accuracy
                })
        
        return context

@method_decorator(instructor_required, name='dispatch')
class ExamUpdateView(UpdateView):
    model = Exam
    form_class = ExamForm
    template_name = 'exams/exam_form.html'
    
    def get_success_url(self):
        return reverse('exams:exam_detail', kwargs={'pk': self.object.pk})
    
    def dispatch(self, request, *args, **kwargs):
        exam = self.get_object()
        
        # Check permissions
        if not request.user.is_superadmin and exam.course.department.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to edit this exam.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        messages.success(self.request, 'Exam updated successfully.')
        return super().form_valid(form)

@method_decorator(instructor_required, name='dispatch')
class ExamDeleteView(DeleteView):
    model = Exam
    template_name = 'exams/exam_confirm_delete.html'
    success_url = reverse_lazy('exams:exam_list')
    
    def dispatch(self, request, *args, **kwargs):
        exam = self.get_object()
        
        # Check permissions
        if not request.user.is_superadmin and exam.course.department.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to delete this exam.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Exam deleted successfully.')
        return super().delete(request, *args, **kwargs)

@instructor_required
def exam_toggle_publish(request, pk):
    exam = get_object_or_404(Exam, pk=pk)
    
    # Check permissions
    if not request.user.is_superadmin and exam.course.department.institution != request.user.institution:
        raise PermissionDenied("You don't have permission to modify this exam.")
    
    exam.is_published = not exam.is_published
    exam.save()
    
    action = "published" if exam.is_published else "unpublished"
    messages.success(request, f'Exam {action} successfully.')
    
    return redirect('exams:exam_detail', pk=exam.pk)

# Question Bank Views
@method_decorator(instructor_required, name='dispatch')
class QuestionBankListView(ListView):
    model = QuestionBank
    template_name = 'exams/question_bank_list.html'
    context_object_name = 'question_banks'
    paginate_by = 20
    
    def get_queryset(self):
        if self.request.user.is_superadmin:
            return QuestionBank.objects.select_related('course', 'created_by')
        else:
            return QuestionBank.objects.filter(
                course__department__institution=self.request.user.institution
            ).select_related('course', 'created_by')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        if self.request.user.is_superadmin:
            context['courses'] = Course.objects.all()
        else:
            context['courses'] = Course.objects.filter(
                department__institution=self.request.user.institution
            )
        
        return context

@method_decorator(instructor_required, name='dispatch')
class QuestionBankCreateView(CreateView):
    model = QuestionBank
    form_class = QuestionBankForm
    template_name = 'exams/question_bank_form.html'
    success_url = reverse_lazy('exams:question_bank_list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Question bank created successfully.')
        return super().form_valid(form)

@method_decorator(instructor_required, name='dispatch')
class QuestionBankDetailView(DetailView):
    model = QuestionBank
    template_name = 'exams/question_bank_detail.html'
    context_object_name = 'question_bank'
    
    def dispatch(self, request, *args, **kwargs):
        question_bank = self.get_object()
        
        # Check permissions
        if not request.user.is_superadmin and question_bank.course.department.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to view this question bank.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['questions'] = self.object.questions.all()
        return context

@method_decorator(instructor_required, name='dispatch')
class QuestionBankUpdateView(UpdateView):
    model = QuestionBank
    form_class = QuestionBankForm
    template_name = 'exams/question_bank_form.html'
    
    def get_success_url(self):
        return reverse('exams:question_bank_detail', kwargs={'pk': self.object.pk})
    
    def dispatch(self, request, *args, **kwargs):
        question_bank = self.get_object()
        
        # Check permissions
        if not request.user.is_superadmin and question_bank.course.department.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to edit this question bank.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        messages.success(self.request, 'Question bank updated successfully.')
        return super().form_valid(form)

@method_decorator(instructor_required, name='dispatch')
class QuestionBankDeleteView(DeleteView):
    model = QuestionBank
    template_name = 'exams/question_bank_confirm_delete.html'
    success_url = reverse_lazy('exams:question_bank_list')
    
    def dispatch(self, request, *args, **kwargs):
        question_bank = self.get_object()
        
        # Check permissions
        if not request.user.is_superadmin and question_bank.course.department.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to delete this question bank.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Question bank deleted successfully.')
        return super().delete(request, *args, **kwargs)

# Question Views
@method_decorator(instructor_required, name='dispatch')
class QuestionCreateView(CreateView):
    model = Question
    form_class = QuestionForm
    template_name = 'exams/question_form.html'
    
    def get_success_url(self):
        return reverse('exams:question_bank_detail', kwargs={'pk': self.object.question_bank.pk})
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def get_initial(self):
        initial = super().get_initial()
        question_bank_id = self.request.GET.get('question_bank')
        if question_bank_id:
            initial['question_bank'] = get_object_or_404(QuestionBank, pk=question_bank_id)
        return initial
    
    def form_valid(self, form):
        messages.success(self.request, 'Question created successfully.')
        return super().form_valid(form)

@method_decorator(instructor_required, name='dispatch')
class QuestionUpdateView(UpdateView):
    model = Question
    form_class = QuestionForm
    template_name = 'exams/question_form.html'
    
    def get_success_url(self):
        return reverse('exams:question_bank_detail', kwargs={'pk': self.object.question_bank.pk})
    
    def dispatch(self, request, *args, **kwargs):
        question = self.get_object()
        
        # Check permissions
        if not request.user.is_superadmin and question.question_bank.course.department.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to edit this question.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        messages.success(self.request, 'Question updated successfully.')
        return super().form_valid(form)

@method_decorator(instructor_required, name='dispatch')
class QuestionDeleteView(DeleteView):
    model = Question
    template_name = 'exams/question_confirm_delete.html'
    
    def get_success_url(self):
        return reverse('exams:question_bank_detail', kwargs={'pk': self.object.question_bank.pk})
    
    def dispatch(self, request, *args, **kwargs):
        question = self.get_object()
        
        # Check permissions
        if not request.user.is_superadmin and question.question_bank.course.department.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to delete this question.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Question deleted successfully.')
        return super().delete(request, *args, **kwargs)

@instructor_required
def bulk_question_upload(request, question_bank_id):
    question_bank = get_object_or_404(QuestionBank, pk=question_bank_id)
    
    # Check permissions
    if not request.user.is_superadmin and question_bank.course.department.institution != request.user.institution:
        raise PermissionDenied("You don't have permission to upload questions to this question bank.")
    
    if request.method == 'POST':
        form = BulkQuestionUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                csv_file = form.cleaned_data['csv_file']
                # Process CSV file and create questions
                decoded_file = csv_file.read().decode('utf-8').splitlines()
                reader = csv.DictReader(decoded_file)
                
                created_count = 0
                error_count = 0
                errors = []
                
                for row_num, row in enumerate(reader, start=2):  # Start at 2 to account for header
                    try:
                        question = Question(
                            question_bank=question_bank,
                            question_text=row['question_text'],
                            question_type=row.get('question_type', 'multiple_choice'),
                            points=int(row.get('points', 1)),
                            option_a=row.get('option_a', ''),
                            option_b=row.get('option_b', ''),
                            option_c=row.get('option_c', ''),
                            option_d=row.get('option_d', ''),
                            option_e=row.get('option_e', ''),
                            correct_answer=row['correct_answer'],
                            explanation=row.get('explanation', '')
                        )
                        question.full_clean()
                        question.save()
                        created_count += 1
                    except Exception as e:
                        error_count += 1
                        errors.append(f"Row {row_num}: {str(e)}")
                
                messages.success(
                    request, 
                    f"Successfully created {created_count} questions. {error_count} errors occurred."
                )
                
                if errors:
                    request.session['bulk_upload_errors'] = errors
                
                return redirect('exams:question_bank_detail', pk=question_bank_id)
                
            except Exception as e:
                messages.error(request, f'Error processing upload: {str(e)}')
    else:
        form = BulkQuestionUploadForm()
    
    return render(request, 'exams/bulk_question_upload.html', {
        'form': form,
        'question_bank': question_bank
    })

# Exam Attempt Views
@method_decorator(login_required, name='dispatch')
class ExamAttemptListView(ListView):
    model = ExamAttempt
    template_name = 'exams/exam_attempt_list.html'
    context_object_name = 'attempts'
    paginate_by = 20
    
    def get_queryset(self):
        if self.request.user.is_student:
            return ExamAttempt.objects.filter(
                student=self.request.user
            ).select_related('exam', 'exam__course')
        else:
            # For educators, show attempts for their exams
            return ExamAttempt.objects.filter(
                exam__course__department__institution=self.request.user.institution
            ).select_related('exam', 'exam__course', 'student')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        if self.request.user.is_educator:
            # Add filter options for educators
            exam_id = self.request.GET.get('exam')
            student_id = self.request.GET.get('student')
            status = self.request.GET.get('status')
            
            if self.request.user.is_superadmin:
                context['exams'] = Exam.objects.all()
                context['students'] = User.objects.filter(role=User.Role.STUDENT)
            else:
                context['exams'] = Exam.objects.filter(
                    course__department__institution=self.request.user.institution
                )
                context['students'] = User.objects.filter(
                    institution=self.request.user.institution,
                    role=User.Role.STUDENT
                )
        
        return context

@method_decorator(student_required, name='dispatch')
class ExamAttemptDetailView(DetailView):
    model = ExamAttempt
    template_name = 'exams/exam_attempt_detail.html'
    context_object_name = 'attempt'
    
    def dispatch(self, request, *args, **kwargs):
        attempt = self.get_object()
        
        # Students can only view their own attempts
        if request.user.is_student and attempt.student != request.user:
            raise PermissionDenied("You don't have permission to view this attempt.")
        
        # Educators can view attempts for their institution
        if request.user.is_educator and not request.user.is_superadmin:
            if attempt.exam.course.department.institution != request.user.institution:
                raise PermissionDenied("You don't have permission to view this attempt.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['responses'] = self.object.responses.select_related('question')
        return context

@method_decorator(instructor_required, name='dispatch')
class ExamAttemptReviewView(UpdateView):
    model = ExamAttempt
    form_class = ExamAttemptReviewForm
    template_name = 'exams/exam_attempt_review.html'
    
    def get_success_url(self):
        return reverse('exams:exam_attempt_detail', kwargs={'pk': self.object.pk})
    
    def dispatch(self, request, *args, **kwargs):
        attempt = self.get_object()
        
        # Check permissions
        if not request.user.is_superadmin and attempt.exam.course.department.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to review this attempt.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, 'Exam attempt reviewed successfully.')
        return super().form_valid(form)

# Exam Taking Views
@student_required
def start_exam(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id, is_published=True)
    
    # Check if exam is available
    now = timezone.now()
    if now < exam.start_time:
        messages.error(request, 'This exam has not started yet.')
        return redirect('exams:exam_list')
    
    if now > exam.end_time:
        messages.error(request, 'This exam has already ended.')
        return redirect('exams:exam_list')
    
    # Check if student is enrolled in the course
    if not Enrollment.objects.filter(
        student=request.user,
        section__course=exam.course,
        is_active=True
    ).exists():
        messages.error(request, 'You are not enrolled in this course.')
        return redirect('exams:exam_list')
    
    # Check for existing active attempt
    existing_attempt = ExamAttempt.objects.filter(
        exam=exam,
        student=request.user,
        status__in=['not_started', 'in_progress']
    ).first()
    
    if existing_attempt:
        return redirect('exams:take_exam', attempt_id=existing_attempt.pk)
    
    # Create new attempt
    attempt = ExamAttempt.objects.create(
        exam=exam,
        student=request.user,
        start_time=timezone.now(),
        status='not_started'
    )
    
    # Create exam session
    ExamSession.objects.create(
        attempt=attempt,
        user=request.user,
        exam=exam,
        device_session=UserDeviceSession.create_from_request(request.user, request),
        session_token=ExamSession.generate_session_token(),
        is_active=True
    )
    
    return redirect('exams:take_exam', attempt_id=attempt.pk)

@student_required
def take_exam(request, attempt_id):
    attempt = get_object_or_404(ExamAttempt, pk=attempt_id, student=request.user)
    
    # Check if attempt is valid
    if attempt.status == 'completed':
        messages.info(request, 'You have already completed this exam.')
        return redirect('exams:exam_attempt_detail', pk=attempt_id)
    
    if attempt.status == 'not_started':
        attempt.status = 'in_progress'
        attempt.start_time = timezone.now()
        attempt.save()
    
    # Check time limit
    time_elapsed = timezone.now() - attempt.start_time
    time_remaining = attempt.exam.duration - time_elapsed
    
    if time_remaining.total_seconds() <= 0:
        attempt.status = 'completed'
        attempt.end_time = attempt.start_time + attempt.exam.duration
        attempt.save()
        messages.info(request, 'Time is up! Your exam has been automatically submitted.')
        return redirect('exams:exam_attempt_detail', pk=attempt_id)
    
    # Get current question
    current_question_index = int(request.GET.get('question', 0))
    questions = list(attempt.exam.questions.all())
    
    if current_question_index >= len(questions):
        # Exam completed
        attempt.status = 'completed'
        attempt.end_time = timezone.now()
        attempt.save()
        messages.success(request, 'Exam completed successfully!')
        return redirect('exams:exam_attempt_detail', pk=attempt_id)
    
    current_question = questions[current_question_index]
    
    # Handle form submission
    if request.method == 'POST':
        selected_answer = request.POST.get('answer')
        
        # Save response
        response, created = QuestionResponse.objects.get_or_create(
            attempt=attempt,
            question=current_question,
            defaults={'selected_answer': selected_answer}
        )
        
        if not created:
            response.selected_answer = selected_answer
            response.save()
        
        # Move to next question
        next_question_index = current_question_index + 1
        if next_question_index < len(questions):
            return redirect(f'{reverse("exams:take_exam", kwargs={"attempt_id": attempt_id})}?question={next_question_index}')
        else:
            # Exam completed
            attempt.status = 'completed'
            attempt.end_time = timezone.now()
            attempt.save()
            messages.success(request, 'Exam completed successfully!')
            return redirect('exams:exam_attempt_detail', pk=attempt_id)
    
    # Get existing response for this question
    existing_response = QuestionResponse.objects.filter(
        attempt=attempt,
        question=current_question
    ).first()
    
    context = {
        'attempt': attempt,
        'question': current_question,
        'question_index': current_question_index,
        'total_questions': len(questions),
        'time_remaining': time_remaining.total_seconds(),
        'existing_response': existing_response,
    }
    
    return render(request, 'exams/take_exam.html', context)

@student_required
def submit_exam(request, attempt_id):
    attempt = get_object_or_404(ExamAttempt, pk=attempt_id, student=request.user)
    
    if attempt.status != 'completed':
        attempt.status = 'completed'
        attempt.end_time = timezone.now()
        attempt.save()
        
        # Calculate score
        calculate_exam_score(attempt)
        
        messages.success(request, 'Exam submitted successfully!')
    
    return redirect('exams:exam_attempt_detail', pk=attempt_id)

def calculate_exam_score(attempt):
    responses = QuestionResponse.objects.filter(attempt=attempt)
    total_score = 0
    max_score = 0
    
    for response in responses:
        max_score += response.question.points
        if response.selected_answer == response.question.correct_answer:
            total_score += response.question.points
            response.is_correct = True
            response.save()
    
    attempt.score = total_score
    attempt.max_score = max_score
    attempt.percentage = (total_score / max_score * 100) if max_score > 0 else 0
    attempt.save()

# Monitoring Views
@instructor_required
def monitoring_dashboard(request, exam_id=None):
    if exam_id:
        exam = get_object_or_404(Exam, pk=exam_id)
        
        # Check permissions
        if not request.user.is_superadmin and exam.course.department.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to monitor this exam.")
        
        active_attempts = ExamAttempt.objects.filter(
            exam=exam,
            status='in_progress'
        ).select_related('student')
        
        context = {
            'exam': exam,
            'active_attempts': active_attempts,
        }
        
        return render(request, 'exams/monitoring_dashboard.html', context)
    else:
        # Show list of exams that can be monitored
        if request.user.is_superadmin:
            exams = Exam.objects.filter(
                is_published=True,
                start_time__lte=timezone.now(),
                end_time__gte=timezone.now()
            )
        else:
            exams = Exam.objects.filter(
                course__department__institution=request.user.institution,
                is_published=True,
                start_time__lte=timezone.now(),
                end_time__gte=timezone.now()
            )
        
        context = {
            'exams': exams,
        }
        
        return render(request, 'exams/monitoring_exam_list.html', context)

@instructor_required
def monitoring_detail(request, attempt_id):
    attempt = get_object_or_404(ExamAttempt, pk=attempt_id)
    
    # Check permissions
    if not request.user.is_superadmin and attempt.exam.course.department.institution != request.user.institution:
        raise PermissionDenied("You don't have permission to monitor this attempt.")
    
    # Get proctoring events for this attempt
    proctoring_events = ProctoringEvent.objects.filter(
        attempt=attempt
    ).order_by('-timestamp')
    
    context = {
        'attempt': attempt,
        'proctoring_events': proctoring_events,
    }
    
    return render(request, 'exams/monitoring_detail.html', context)

@csrf_exempt
@require_POST
def proctoring_webhook(request, attempt_id):
    # This endpoint would receive events from the proctoring software
    attempt = get_object_or_404(ExamAttempt, pk=attempt_id)
    
    try:
        data = json.loads(request.body)
        event_type = data.get('event_type')
        event_data = data.get('event_data', {})
        timestamp = data.get('timestamp', timezone.now())
        
        ProctoringEvent.objects.create(
            attempt=attempt,
            event_type=event_type,
            event_data=event_data,
            timestamp=timestamp
        )
        
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

# API Views
@login_required
def api_exam_questions(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    
    # Check permissions
    if request.user.is_student:
        if not exam.is_published or exam.end_time < timezone.now():
            return JsonResponse({'error': 'Access denied'}, status=403)
    
    questions = []
    for question in exam.questions.all():
        questions.append({
            'id': question.id,
            'question_text': question.question_text,
            'question_type': question.question_type,
            'points': question.points,
            'options': {
                'A': question.option_a,
                'B': question.option_b,
                'C': question.option_c,
                'D': question.option_d,
                'E': question.option_e,
            }
        })
    
    return JsonResponse({'questions': questions})

@login_required
def api_save_response(request, attempt_id, question_id):
    attempt = get_object_or_404(ExamAttempt, pk=attempt_id)
    question = get_object_or_404(Question, pk=question_id)
    
    # Check permissions
    if request.user.is_student and attempt.student != request.user:
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            selected_answer = data.get('selected_answer')
            
            response, created = QuestionResponse.objects.get_or_create(
                attempt=attempt,
                question=question,
                defaults={'selected_answer': selected_answer}
            )
            
            if not created:
                response.selected_answer = selected_answer
                response.save()
            
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    
    return JsonResponse({'error': 'Invalid method'}, status=405)

# Report Views
@instructor_required
def exam_report(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    
    # Check permissions
    if not request.user.is_superadmin and exam.course.department.institution != request.user.institution:
        raise PermissionDenied("You don't have permission to view this report.")
    
    attempts = ExamAttempt.objects.filter(
        exam=exam,
        status='completed'
    ).select_related('student')
    
    # Calculate statistics
    stats = attempts.aggregate(
        avg_score=Avg('percentage'),
        max_score=Max('percentage'),
        min_score=Min('percentage'),
        pass_count=Count('id', filter=Q(percentage__gte=exam.pass_percentage)),
        fail_count=Count('id', filter=Q(percentage__lt=exam.pass_percentage))
    )
    
    context = {
        'exam': exam,
        'attempts': attempts,
        'stats': stats,
    }
    
    return render(request, 'exams/exam_report.html', context)

@instructor_required
def export_exam_results(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    
    # Check permissions
    if not request.user.is_superadmin and exam.course.department.institution != request.user.institution:
        raise PermissionDenied("You don't have permission to export these results.")
    
    attempts = ExamAttempt.objects.filter(
        exam=exam,
        status='completed'
    ).select_related('student')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{exam.title}_results.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Student ID', 'Student Name', 'Score', 'Max Score', 'Percentage', 'Passed', 'Start Time', 'End Time'])
    
    for attempt in attempts:
        writer.writerow([
            attempt.student.username,
            attempt.student.get_full_name(),
            attempt.score,
            attempt.max_score,
            f"{attempt.percentage:.2f}%",
            'Yes' if attempt.percentage >= exam.pass_percentage else 'No',
            attempt.start_time,
            attempt.end_time
        ])
    
    return response
# Error handling
def handler404(request, exception):
    return render(request, 'exams/404.html', status=404)

def handler500(request):
    return render(request, 'exams/500.html', status=500)