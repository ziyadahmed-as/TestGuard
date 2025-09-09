from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
from django.urls import reverse_lazy, reverse
from django.utils.decorators import method_decorator
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count, Sum, Avg, F, ExpressionWrapper, DurationField, Max, Min
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.forms import modelformset_factory
import json
import csv
from datetime import timedelta

from core.models import User, Institution, AcademicDepartment, Course, Section, Enrollment, UserDeviceSession
from .models import (
    Exam, Question, QuestionBank, ExamAttempt, ExamQuestion, 
    QuestionResponse, MonitoringEvent, BulkQuestionImport, ActiveExamSession
)

from .forms import (
    ExamForm, QuestionForm, QuestionBankForm, BulkQuestionUploadForm
)

# Utility functions
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
            queryset = Exam.objects.select_related('created_by')
        elif self.request.user.is_admin or self.request.user.is_instructor:
            # Get exams where user is creator or where sections belong to user's institution
            queryset = Exam.objects.filter(
                Q(created_by=self.request.user) | 
                Q(sections__course__department__institution=self.request.user.institution)
            ).distinct().select_related('created_by')
        else:  # Student
            # Get exams for sections where student is enrolled
            queryset = Exam.objects.filter(
                sections__enrollments__student=self.request.user,
                sections__enrollments__is_active=True,
                status=Exam.Status.LIVE,
                start_date__lte=timezone.now(),
                end_date__gte=timezone.now()
            ).select_related('created_by').distinct()
        
        # Filtering
        status = self.request.GET.get('status')
        
        if status:
            if status == 'active':
                queryset = queryset.filter(
                    status=Exam.Status.LIVE,
                    start_date__lte=timezone.now(),
                    end_date__gte=timezone.now()
                )
            elif status == 'upcoming':
                queryset = queryset.filter(
                    status=Exam.Status.LIVE,
                    start_date__gt=timezone.now()
                )
            elif status == 'completed':
                queryset = queryset.filter(end_date__lt=timezone.now())
            elif status == 'draft':
                queryset = queryset.filter(status=Exam.Status.DRAFT)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        if self.request.user.is_educator:
            # Add courses for filtering if needed
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
        if request.user.is_student:
            # Check if student is enrolled in any section that has this exam
            if not Enrollment.objects.filter(
                student=request.user,
                section__in=exam.sections.all(),
                is_active=True
            ).exists():
                raise PermissionDenied("You don't have permission to view this exam.")
            
            # Check if exam is active
            if not exam.is_active:
                raise PermissionDenied("This exam is not currently available.")
        
        elif request.user.is_educator and not request.user.is_superadmin:
            # Check if educator belongs to the same institution
            if not exam.sections.filter(
                course__department__institution=request.user.institution
            ).exists() and exam.created_by != request.user:
                raise PermissionDenied("You don't have permission to view this exam.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        if self.request.user.is_educator:
            # Add statistics for instructors
            attempts = ExamAttempt.objects.filter(exam=self.object)
            context['attempt_count'] = attempts.count()
            context['completed_count'] = attempts.filter(status=ExamAttempt.Status.SUBMITTED).count()
            context['in_progress_count'] = attempts.filter(status=ExamAttempt.Status.IN_PROGRESS).count()
            
            if context['completed_count'] > 0:
                context['avg_score'] = attempts.filter(status=ExamAttempt.Status.SUBMITTED).aggregate(
                    avg_score=Avg('score')
                )['avg_score']
            
            # Add question statistics
            context['question_stats'] = []
            for exam_question in self.object.exam_questions.select_related('question').all():
                responses = QuestionResponse.objects.filter(
                    question=exam_question.question, 
                    attempt__exam=self.object,
                    attempt__status=ExamAttempt.Status.SUBMITTED
                )
                total_count = responses.count()
                
                if total_count > 0:
                    # For multiple choice questions, check correctness
                    if exam_question.question.type == Question.Type.MULTIPLE_CHOICE:
                        # This would need to be adapted based on your question format
                        correct_count = 0  # Placeholder
                    else:
                        correct_count = 0  # Manual grading required
                    
                    accuracy = (correct_count / total_count) * 100 if total_count > 0 else 0
                else:
                    accuracy = 0
                
                context['question_stats'].append({
                    'question': exam_question.question,
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
        if not request.user.is_superadmin and exam.created_by != request.user:
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
        if not request.user.is_superadmin and exam.created_by != request.user:
            raise PermissionDenied("You don't have permission to delete this exam.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Exam deleted successfully.')
        return super().delete(request, *args, **kwargs)

@instructor_required
def exam_toggle_status(request, pk):
    exam = get_object_or_404(Exam, pk=pk)
    
    # Check permissions
    if not request.user.is_superadmin and exam.created_by != request.user:
        raise PermissionDenied("You don't have permission to modify this exam.")
    
    # Toggle between DRAFT and LIVE status
    if exam.status == Exam.Status.DRAFT:
        exam.status = Exam.Status.LIVE
        action = "published"
    else:
        exam.status = Exam.Status.DRAFT
        action = "unpublished"
    
    exam.save()
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
            return QuestionBank.objects.select_related('institution', 'created_by')
        else:
            return QuestionBank.objects.filter(
                institution=self.request.user.institution
            ).select_related('institution', 'created_by')

@method_decorator(instructor_required, name='dispatch')
class QuestionBankCreateView(CreateView):
    model = QuestionBank
    form_class = QuestionBankForm
    template_name = 'exams/question_bank_form.html'
    success_url = reverse_lazy('exams:question_bank_list')
    
    def form_valid(self, form):
        # For non-superadmins, set the institution to their own
        if not self.request.user.is_superadmin:
            form.instance.institution = self.request.user.institution
            
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
        if not request.user.is_superadmin and question_bank.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to view this question bank.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['questions'] = self.object.questions.filter(is_active=True)
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
        if not request.user.is_superadmin and question_bank.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to edit this question bank.")
        
        return super().dispatch(request, *args, **kwargs)
    
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
        if not request.user.is_superadmin and question_bank.institution != request.user.institution:
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
        return reverse('exams:question_bank_detail', kwargs={'pk': self.object.bank.pk})
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def get_initial(self):
        initial = super().get_initial()
        question_bank_id = self.request.GET.get('bank')
        if question_bank_id:
            bank = get_object_or_404(QuestionBank, pk=question_bank_id)
            # Check permission
            if not self.request.user.is_superadmin and bank.institution != self.request.user.institution:
                raise PermissionDenied("You don't have permission to add questions to this bank.")
            initial['bank'] = bank
        return initial
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Question created successfully.')
        return super().form_valid(form)

@method_decorator(instructor_required, name='dispatch')
class QuestionUpdateView(UpdateView):
    model = Question
    form_class = QuestionForm
    template_name = 'exams/question_form.html'
    
    def get_success_url(self):
        return reverse('exams:question_bank_detail', kwargs={'pk': self.object.bank.pk})
    
    def dispatch(self, request, *args, **kwargs):
        question = self.get_object()
        
        # Check permissions
        if not request.user.is_superadmin and question.bank.institution != request.user.institution:
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
        return reverse('exams:question_bank_detail', kwargs={'pk': self.object.bank.pk})
    
    def dispatch(self, request, *args, **kwargs):
        question = self.get_object()
        
        # Check permissions
        if not request.user.is_superadmin and question.bank.institution != request.user.institution:
            raise PermissionDenied("You don't have permission to delete this question.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Question deleted successfully.')
        return super().delete(request, *args, **kwargs)

@instructor_required
def bulk_question_upload(request, bank_id):
    question_bank = get_object_or_404(QuestionBank, pk=bank_id)
    
    # Check permissions
    if not request.user.is_superadmin and question_bank.institution != request.user.institution:
        raise PermissionDenied("You don't have permission to upload questions to this question bank.")
    
    if request.method == 'POST':
        form = BulkQuestionUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # Create a bulk import record
                bulk_import = BulkQuestionImport(
                    uploaded_by=request.user,
                    question_bank=question_bank,
                    import_file=form.cleaned_data['csv_file'],
                    status=BulkQuestionImport.Status.PENDING
                )
                bulk_import.save()
                
                # Process the import (in real app, this might be done async)
                bulk_import.process_import()
                
                messages.success(
                    request, 
                    f"Import completed. {bulk_import.successful_imports} questions created, {bulk_import.failed_imports} failed."
                )
                
                if bulk_import.failed_imports > 0:
                    messages.warning(request, "Some questions failed to import. Check the error log for details.")
                
                return redirect('exams:question_bank_detail', pk=bank_id)
                
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
            ).select_related('exam', 'device_session')
        else:
            # For educators, show attempts for exams they created or for their institution
            if self.request.user.is_superadmin:
                return ExamAttempt.objects.all().select_related('exam', 'student', 'device_session')
            else:
                return ExamAttempt.objects.filter(
                    Q(exam__created_by=self.request.user) |
                    Q(exam__sections__course__department__institution=self.request.user.institution)
                ).distinct().select_related('exam', 'student', 'device_session')
    
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
                    Q(created_by=self.request.user) |
                    Q(sections__course__department__institution=self.request.user.institution)
                ).distinct()
                context['students'] = User.objects.filter(
                    institution=self.request.user.institution,
                    role=User.Role.STUDENT
                )
        
        return context

@method_decorator(login_required, name='dispatch')
class ExamAttemptDetailView(DetailView):
    model = ExamAttempt
    template_name = 'exams/exam_attempt_detail.html'
    context_object_name = 'attempt'
    
    def dispatch(self, request, *args, **kwargs):
        attempt = self.get_object()
        
        # Students can only view their own attempts
        if request.user.is_student and attempt.student != request.user:
            raise PermissionDenied("You don't have permission to view this attempt.")
        
        # Educators can view attempts for their institution or their own exams
        if request.user.is_educator and not request.user.is_superadmin:
            if (attempt.exam.created_by != request.user and 
                not attempt.exam.sections.filter(
                    course__department__institution=request.user.institution
                ).exists()):
                raise PermissionDenied("You don't have permission to view this attempt.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['responses'] = QuestionResponse.objects.filter(
            attempt=self.object
        ).select_related('question')
        context['monitoring_events'] = MonitoringEvent.objects.filter(
            attempt=self.object
        ).order_by('-timestamp')
        return context

# Exam Taking Views
@student_required
def start_exam(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    
    # Check if exam is available
    if not exam.is_active:
        messages.error(request, 'This exam is not currently available.')
        return redirect('exams:exam_list')
    
    # Check if student is enrolled in any section that has this exam
    if not Enrollment.objects.filter(
        student=request.user,
        section__in=exam.sections.all(),
        is_active=True
    ).exists():
        messages.error(request, 'You are not enrolled in any section with access to this exam.')
        return redirect('exams:exam_list')
    
    # Check for existing active attempt
    existing_attempt = ExamAttempt.objects.filter(
        exam=exam,
        student=request.user,
        status__in=[ExamAttempt.Status.NOT_STARTED, ExamAttempt.Status.IN_PROGRESS]
    ).first()
    
    if existing_attempt:
        return redirect('exams:take_exam', attempt_id=existing_attempt.pk)
    
    # Create new attempt
    attempt = ExamAttempt.objects.create(
        exam=exam,
        student=request.user,
        status=ExamAttempt.Status.NOT_STARTED
    )
    
    return redirect('exams:take_exam', attempt_id=attempt.pk)

@student_required
def take_exam(request, attempt_id):
    attempt = get_object_or_404(ExamAttempt, pk=attempt_id, student=request.user)
    
    # Check if attempt is valid
    if attempt.status == ExamAttempt.Status.SUBMITTED:
        messages.info(request, 'You have already completed this exam.')
        return redirect('exams:exam_attempt_detail', pk=attempt_id)
    
    if attempt.status == ExamAttempt.Status.NOT_STARTED:
        # Check if password is required
        if attempt.requires_password_input:
            return redirect('exams:exam_password', attempt_id=attempt_id)
        
        # Start the exam
        device_session = UserDeviceSession.create_from_request(request)
        success, message = attempt.start_exam(device_session)
        
        if not success:
            messages.error(request, message)
            return redirect('exams:exam_list')
    
    # Check time limit
    time_remaining = attempt.time_remaining
    
    if time_remaining <= 0:
        attempt.status = ExamAttempt.Status.AUTO_SUBMITTED
        attempt.end_time = attempt.start_time + timedelta(minutes=attempt.exam.duration)
        attempt.save()
        messages.info(request, 'Time is up! Your exam has been automatically submitted.')
        return redirect('exams:exam_attempt_detail', pk=attempt_id)
    
    # Get questions for this exam
    exam_questions = attempt.exam.exam_questions.select_related('question').order_by('order')
    questions = [eq.question for eq in exam_questions]
    
    # Get current question index
    current_question_index = int(request.GET.get('question', 0))
    
    if current_question_index >= len(questions):
        # Exam completed
        attempt.status = ExamAttempt.Status.SUBMITTED
        attempt.end_time = timezone.now()
        attempt.save()
        messages.success(request, 'Exam completed successfully!')
        return redirect('exams:exam_attempt_detail', pk=attempt_id)
    
    current_question = questions[current_question_index]
    
    # Handle form submission
    if request.method == 'POST':
        # This would need to be adapted based on your question types
        # For now, we'll just save a generic response
        answer_data = {
            'answer': request.POST.get('answer'),
            'timestamp': timezone.now().isoformat()
        }
        
        # Save response
        response, created = QuestionResponse.objects.get_or_create(
            attempt=attempt,
            question=current_question,
            defaults={'student_answer': answer_data}
        )
        
        if not created:
            response.student_answer = answer_data
            response.save()
        
        # Move to next question or complete exam
        next_question_index = current_question_index + 1
        if next_question_index < len(questions):
            return redirect(f'{reverse("exams:take_exam", kwargs={"attempt_id": attempt_id})}?question={next_question_index}')
        else:
            # Exam completed
            attempt.status = ExamAttempt.Status.SUBMITTED
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
        'time_remaining': time_remaining,
        'existing_response': existing_response,
    }
    
    return render(request, 'exams/take_exam.html', context)

@student_required
def exam_password(request, attempt_id):
    attempt = get_object_or_404(ExamAttempt, pk=attempt_id, student=request.user)
    
    if attempt.status != ExamAttempt.Status.NOT_STARTED:
        return redirect('exams:take_exam', attempt_id=attempt_id)
    
    if request.method == 'POST':
        password = request.POST.get('password')
        device_session = UserDeviceSession.create_from_request(request)
        success, message = attempt.start_exam(device_session, password)
        
        if success:
            return redirect('exams:take_exam', attempt_id=attempt_id)
        else:
            messages.error(request, message)
    
    return render(request, 'exams/exam_password.html', {'attempt': attempt})

@student_required
def submit_exam(request, attempt_id):
    attempt = get_object_or_404(ExamAttempt, pk=attempt_id, student=request.user)
    
    if attempt.status != ExamAttempt.Status.SUBMITTED:
        attempt.status = ExamAttempt.Status.SUBMITTED
        attempt.end_time = timezone.now()
        attempt.save()
        
        # Calculate score (this would need to be implemented based on your grading logic)
        # calculate_exam_score(attempt)
        
        messages.success(request, 'Exam submitted successfully!')
    
    return redirect('exams:exam_attempt_detail', pk=attempt_id)

# Monitoring Views
@instructor_required
def monitoring_dashboard(request, exam_id=None):
    if exam_id:
        exam = get_object_or_404(Exam, pk=exam_id)
        
        # Check permissions
        if not request.user.is_superadmin and not exam.sections.filter(
            course__department__institution=request.user.institution
        ).exists() and exam.created_by != request.user:
            raise PermissionDenied("You don't have permission to monitor this exam.")
        
        active_attempts = ExamAttempt.objects.filter(
            exam=exam,
            status=ExamAttempt.Status.IN_PROGRESS
        ).select_related('student', 'device_session')
        
        # Calculate risk levels for each attempt
        for attempt in active_attempts:
            # This is a simplified example - you'd implement your own risk calculation
            violation_count = MonitoringEvent.objects.filter(
                attempt=attempt,
                event_type=MonitoringEvent.EventType.VIOLATION
            ).count()
            
            warning_count = MonitoringEvent.objects.filter(
                attempt=attempt,
                event_type=MonitoringEvent.EventType.WARNING
            ).count()
            
            if violation_count > 0:
                attempt.risk_level = 'high'
            elif warning_count > 1:
                attempt.risk_level = 'medium'
            else:
                attempt.risk_level = 'low'
        
        context = {
            'exam': exam,
            'active_attempts': active_attempts,
        }
        
        return render(request, 'exams/monitoring_dashboard.html', context)
    else:
        # Show list of exams that can be monitored
        if request.user.is_superadmin:
            exams = Exam.objects.filter(
                status=Exam.Status.LIVE,
                start_date__lte=timezone.now(),
                end_date__gte=timezone.now()
            )
        else:
            exams = Exam.objects.filter(
                Q(created_by=request.user) |
                Q(sections__course__department__institution=request.user.institution),
                status=Exam.Status.LIVE,
                start_date__lte=timezone.now(),
                end_date__gte=timezone.now()
            ).distinct()
        
        context = {
            'exams': exams,
        }
        
        return render(request, 'exams/monitoring_exam_list.html', context)

@instructor_required
def monitoring_detail(request, attempt_id):
    attempt = get_object_or_404(ExamAttempt, pk=attempt_id)
    
    # Check permissions
    if not request.user.is_superadmin and not attempt.exam.sections.filter(
        course__department__institution=request.user.institution
    ).exists() and attempt.exam.created_by != request.user:
        raise PermissionDenied("You don't have permission to monitor this attempt.")
    
    # Get monitoring events for this attempt
    monitoring_events = MonitoringEvent.objects.filter(
        attempt=attempt
    ).order_by('-timestamp')
    
    # Calculate risk level
    violation_count = monitoring_events.filter(
        event_type=MonitoringEvent.EventType.VIOLATION
    ).count()
    
    warning_count = monitoring_events.filter(
        event_type=MonitoringEvent.EventType.WARNING
    ).count()
    
    if violation_count > 0:
        risk_level = 'high'
    elif warning_count > 1:
        risk_level = 'medium'
    else:
        risk_level = 'low'
    
    context = {
        'attempt': attempt,
        'monitoring_events': monitoring_events,
        'risk_level': risk_level,
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
        severity = data.get('severity', 5)
        
        MonitoringEvent.objects.create(
            attempt=attempt,
            event_type=event_type,
            event_data=event_data,
            timestamp=timestamp,
            severity=severity
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
        if not exam.is_active:
            return JsonResponse({'error': 'Exam not available'}, status=403)
        
        # Check if student is enrolled
        if not Enrollment.objects.filter(
            student=request.user,
            section__in=exam.sections.all(),
            is_active=True
        ).exists():
            return JsonResponse({'error': 'Access denied'}, status=403)
    
    questions = []
    for exam_question in exam.exam_questions.select_related('question').order_by('order'):
        question = exam_question.question
        questions.append({
            'id': question.id,
            'question_text': question.question_text,
            'question_type': question.type,
            'points': float(exam_question.points),
            'order': exam_question.order
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
            answer_data = data.get('answer_data', {})
            
            response, created = QuestionResponse.objects.get_or_create(
                attempt=attempt,
                question=question,
                defaults={'student_answer': answer_data}
            )
            
            if not created:
                response.student_answer = answer_data
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
    if not request.user.is_superadmin and not exam.sections.filter(
        course__department__institution=request.user.institution
    ).exists() and exam.created_by != request.user:
        raise PermissionDenied("You don't have permission to view this report.")
    
    attempts = ExamAttempt.objects.filter(
        exam=exam,
        status=ExamAttempt.Status.SUBMITTED
    ).select_related('student')
    
    # Calculate statistics
    stats = attempts.aggregate(
        avg_score=Avg('score'),
        max_score=Max('score'),
        min_score=Min('score'),
        avg_time=Avg(F('end_time') - F('start_time'))
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
    if not request.user.is_superadmin and not exam.sections.filter(
        course__department__institution=request.user.institution
    ).exists() and exam.created_by != request.user:
        raise PermissionDenied("You don't have permission to export these results.")
    
    attempts = ExamAttempt.objects.filter(
        exam=exam,
        status=ExamAttempt.Status.SUBMITTED
    ).select_related('student')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{exam.title}_results.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Student ID', 'Student Name', 'Score', 'Percentage', 'Start Time', 'End Time', 'Duration (min)'])
    
    for attempt in attempts:
        duration = (attempt.end_time - attempt.start_time).total_seconds() / 60 if attempt.end_time else 0
        writer.writerow([
            attempt.student.username,
            attempt.student.get_full_name(),
            attempt.score or 0,
            f"{(attempt.score / exam.total_points * 100):.2f}%" if attempt.score and exam.total_points else "N/A",
            attempt.start_time,
            attempt.end_time,
            f"{duration:.2f}"
        ])
    
    return response

# Error handling
def handler404(request, exception):
    return render(request, 'exams/404.html', status=404)

def handler500(request):
    return render(request, 'exams/500.html', status=500)