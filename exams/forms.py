# forms.py
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (
    BulkQuestionImport, QuestionBank, Question, Exam, 
    ExamQuestion, ExamAttempt, QuestionResponse, MonitoringEvent
)
from core.models import User, Section, Institution

class BulkQuestionUploadForm(forms.ModelForm):
    """
    Form for uploading and processing bulk question imports with Tailwind styling
    """
    class Meta:
        model = BulkQuestionImport
        fields = ['question_bank', 'import_file']
        widgets = {
            'question_bank': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
            }),
            'import_file': forms.FileInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'accept': '.xlsx,.xls'
            }),
        }
        labels = {
            'import_file': 'Excel File',
        }
    
    def __init__(self, *args, **kwargs):
        self.uploaded_by = kwargs.pop('uploaded_by', None)
        super().__init__(*args, **kwargs)
        
        # Limit question banks to those accessible by the user
        if self.uploaded_by:
            self.fields['question_bank'].queryset = QuestionBank.objects.filter(
                institution=self.uploaded_by.institution
            )


class QuestionBankForm(forms.ModelForm):
    """
    Form for creating and updating question banks with Tailwind styling
    """
    class Meta:
        model = QuestionBank
        fields = ['name', 'description', 'is_global', 'is_public']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': 'Enter question bank name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'rows': 4,
                'placeholder': 'Describe the purpose and content of this question bank'
            }),
            'is_global': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
            }),
            'is_public': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.institution = kwargs.pop('institution', None)
        self.created_by = kwargs.pop('created_by', None)
        super().__init__(*args, **kwargs)
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.institution:
            instance.institution = self.institution
        if self.created_by:
            instance.created_by = self.created_by
        
        if commit:
            instance.save()
        return instance


class QuestionForm(forms.ModelForm):
    """
    Form for creating and updating questions with Tailwind styling
    """
    class Meta:
        model = Question
        fields = ['question_text', 'type', 'bank', 'learning_objective', 'points', 'estimated_time', 'is_active']
        widgets = {
            'question_text': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'rows': 4,
                'placeholder': 'Enter the question text'
            }),
            'type': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
            }),
            'bank': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
            }),
            'learning_objective': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': 'Enter learning objective'
            }),
            'points': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'step': '0.01',
                'min': '0.01'
            }),
            'estimated_time': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'min': '1'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.created_by = kwargs.pop('created_by', None)
        super().__init__(*args, **kwargs)
        
        # Limit banks to those accessible by the user
        if self.created_by:
            self.fields['bank'].queryset = QuestionBank.objects.filter(
                institution=self.created_by.institution
            )
    
    def clean(self):
        cleaned_data = super().clean()
        bank = cleaned_data.get('bank')
        
        # Validate that the bank belongs to the same institution as the creator
        if bank and self.created_by and bank.institution != self.created_by.institution:
            raise ValidationError("Question bank must belong to your institution.")
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.created_by:
            instance.created_by = self.created_by
        
        if commit:
            instance.save()
        return instance


class ExamForm(forms.ModelForm):
    """
    Form for creating and updating exams with Tailwind styling
    """
    sections = forms.ModelMultipleChoiceField(
        queryset=Section.objects.all(),
        widget=forms.SelectMultiple(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
        }),
        required=False
    )
    
    class Meta:
        model = Exam
        fields = [
            'title', 'description', 'instructions', 'duration', 'max_attempts', 
            'pass_percentage', 'exam_password', 'start_date', 'end_date', 'time_zone',
            'shuffle_questions', 'shuffle_answers', 'disable_copy_paste', 
            'full_screen_required', 'require_webcam', 'allow_backtracking', 
            'enable_auto_save', 'sections'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': 'Enter exam title'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'rows': 4,
                'placeholder': 'Describe the exam purpose and content'
            }),
            'instructions': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'rows': 4,
                'placeholder': 'Provide instructions for exam takers'
            }),
            'duration': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'min': '1'
            }),
            'max_attempts': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'min': '1'
            }),
            'pass_percentage': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'step': '0.01',
                'min': '0',
                'max': '100'
            }),
            'exam_password': forms.PasswordInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'autocomplete': 'new-password',
                'placeholder': 'Optional exam password'
            }),
            'start_date': forms.DateTimeInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'type': 'datetime-local'
            }),
            'end_date': forms.DateTimeInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'type': 'datetime-local'
            }),
            'time_zone': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
            }),
            'shuffle_questions': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
            }),
            'shuffle_answers': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
            }),
            'disable_copy_paste': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
            }),
            'full_screen_required': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
            }),
            'require_webcam': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
            }),
            'allow_backtracking': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
            }),
            'enable_auto_save': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.created_by = kwargs.pop('created_by', None)
        super().__init__(*args, **kwargs)
        
        # Limit sections to those accessible by the user
        if self.created_by:
            self.fields['sections'].queryset = Section.objects.filter(
                institution=self.created_by.institution
            )
    
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if start_date and end_date and start_date >= end_date:
            raise ValidationError("Exam end date must be after start date.")
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.created_by:
            instance.created_by = self.created_by
        
        if commit:
            instance.save()
            self.save_m2m()  # Save the many-to-many sections field
        
        return instance


class ExamQuestionForm(forms.ModelForm):
    """
    Form for adding questions to exams with custom ordering and points with Tailwind styling
    """
    class Meta:
        model = ExamQuestion
        fields = ['question', 'order', 'points']
        widgets = {
            'question': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
            }),
            'order': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'min': '0'
            }),
            'points': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'step': '0.01',
                'min': '0.01'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.exam = kwargs.pop('exam', None)
        super().__init__(*args, **kwargs)
        
        # Limit questions to those accessible for this exam
        if self.exam:
            self.fields['question'].queryset = Question.objects.filter(
                bank__institution=self.exam.created_by.institution,
                is_active=True
            )
    
    def clean(self):
        cleaned_data = super().clean()
        points = cleaned_data.get('points')
        
        if points and points <= 0:
            raise ValidationError("Question points must be greater than zero.")
        
        return cleaned_data


class ExamAttemptStartForm(forms.Form):
    """
    Form for starting an exam attempt, including password validation with Tailwind styling
    """
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
            'placeholder': 'Enter exam password'
        }),
        label="Exam Password"
    )
    
    def __init__(self, *args, **kwargs):
        self.exam = kwargs.pop('exam', None)
        super().__init__(*args, **kwargs)
        
        # Make password required if exam has a password
        if self.exam and self.exam.requires_password:
            self.fields['password'].required = True
    
    def clean_password(self):
        password = self.cleaned_data.get('password')
        
        if self.exam and self.exam.requires_password:
            if not self.exam.validate_password(password):
                raise ValidationError("Incorrect exam password.")
        
        return password


class QuestionResponseForm(forms.ModelForm):
    """
    Form for answering exam questions, dynamically adapts to question type with Tailwind styling
    """
    class Meta:
        model = QuestionResponse
        fields = ['student_answer']
    
    def __init__(self, *args, **kwargs):
        self.question = kwargs.pop('question', None)
        super().__init__(*args, **kwargs)
        
        # Customize form based on question type
        if self.question:
            if self.question.type == Question.Type.MULTIPLE_CHOICE:
                # For multiple choice, we'd typically have choices from a related model
                # This is a simplified version
                self.fields['student_answer'] = forms.ChoiceField(
                    choices=[('A', 'Option A'), ('B', 'Option B'), ('C', 'Option C'), ('D', 'Option D')],
                    widget=forms.RadioSelect(attrs={
                        'class': 'focus:ring-indigo-500 h-4 w-4 text-indigo-600 border-gray-300'
                    }),
                    label="Select your answer"
                )
            elif self.question.type == Question.Type.TRUE_FALSE:
                self.fields['student_answer'] = forms.ChoiceField(
                    choices=[('T', 'True'), ('F', 'False')],
                    widget=forms.RadioSelect(attrs={
                        'class': 'focus:ring-indigo-500 h-4 w-4 text-indigo-600 border-gray-300'
                    }),
                    label="True or False?"
                )
            elif self.question.type in [Question.Type.SHORT_ANSWER, Question.Type.ESSAY]:
                self.fields['student_answer'] = forms.CharField(
                    widget=forms.Textarea(attrs={
                        'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                        'rows': 6
                    }),
                    label="Your answer"
                )
            elif self.question.type == Question.Type.FILL_BLANK:
                self.fields['student_answer'] = forms.CharField(
                    widget=forms.TextInput(attrs={
                        'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
                    }),
                    label="Fill in the blank"
                )


class MonitoringEventReviewForm(forms.ModelForm):
    """
    Form for reviewing and taking action on monitoring events with Tailwind styling
    """
    class Meta:
        model = MonitoringEvent
        fields = ['reviewed_status', 'review_notes', 'action_taken']
        widgets = {
            'reviewed_status': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
            }),
            'review_notes': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'rows': 4,
                'placeholder': 'Enter review notes and observations'
            }),
            'action_taken': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'rows': 4,
                'placeholder': 'Describe actions taken based on this review'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.reviewed_by = kwargs.pop('reviewed_by', None)
        super().__init__(*args, **kwargs)
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        if self.reviewed_by:
            instance.reviewed_by = self.reviewed_by
            instance.reviewed_at = timezone.now()
        
        if commit:
            instance.save()
        
        return instance


class ExamSearchForm(forms.Form):
    """
    Form for searching and filtering exams with Tailwind styling
    """
    STATUS_CHOICES = [
        ('', 'All Statuses'),
    ] + Exam.Status.choices
    
    title = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
            'placeholder': 'Search by title'
        })
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
        })
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
            'type': 'date'
        })
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
            'type': 'date'
        })
    )


class QuestionFilterForm(forms.Form):
    """
    Form for filtering questions in a question bank with Tailwind styling
    """
    TYPE_CHOICES = [
        ('', 'All Types'),
    ] + Question.Type.choices
    
    question_text = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
            'placeholder': 'Search question text'
        })
    )
    type = forms.ChoiceField(
        choices=TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500'
        })
    )
    learning_objective = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
            'placeholder': 'Search learning objective'
        })
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'
        })
    )