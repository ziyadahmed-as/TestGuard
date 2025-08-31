from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from core.models import User
from exams.models import ExamAttempt, QuestionResponse, Exam, MonitoringEvent


class GradingRubric(models.Model):
    """
    Assessment rubric defining criteria and standards for evaluating subjective responses.
    Provides structured grading framework for consistent evaluation of essay and short answer questions.
    """
    
    name = models.CharField(
        max_length=100,
        help_text="Descriptive name for the grading rubric"
    )
    description = models.TextField(
        blank=True,
        help_text="Comprehensive description of the rubric's purpose and application"
    )
    criteria = models.JSONField(
        help_text="Structured grading criteria with point allocations and performance descriptors"
    )
    max_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
        help_text="Maximum achievable score calculated from criteria point allocations"
    )
    created_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        related_name='grading_rubrics',
        help_text="Instructor who created this grading rubric"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['created_by']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Grading Rubric"
        verbose_name_plural = "Grading Rubrics"

    def __str__(self):
        return f"{self.name} (Max Score: {self.max_score})"

    def save(self, *args, **kwargs):
        """
        Calculate maximum possible score from rubric criteria before persisting.
        Ensures data integrity between criteria definitions and maximum score.
        """
        if self.criteria:
            total = sum(
                criterion.get('max_points', 0) 
                for criterion in self.criteria.values()
            )
            self.max_score = total
        super().save(*args, **kwargs)

    def calculate_score(self, scores):
        """
        Compute total score based on individual criterion scores.
        
        Args:
            scores (dict): Dictionary mapping criterion names to awarded points
            
        Returns:
            decimal.Decimal: Total score with validation against maximum limits
        """
        total = 0
        for criterion_name, points in scores.items():
            if criterion_name in self.criteria:
                max_points = self.criteria[criterion_name].get('max_points', 0)
                total += min(float(points), float(max_points))
        return total

    def validate_scores(self, scores):
        """
        Validate that provided scores comply with rubric constraints.
        
        Args:
            scores (dict): Proposed scores for validation
            
        Raises:
            ValidationError: If any score exceeds maximum allowed points
        """
        errors = []
        for criterion_name, points in scores.items():
            if criterion_name in self.criteria:
                max_points = self.criteria[criterion_name].get('max_points', 0)
                if points > max_points:
                    errors.append(
                        f"Criterion '{criterion_name}': {points} exceeds maximum of {max_points}"
                    )
        if errors:
            raise ValidationError(errors)


class RubricScore(models.Model):
    """
    Evaluation record storing manual scores assigned using a specific grading rubric.
    Links student responses to rubric-based assessments with detailed scoring breakdown.
    """
    
    response = models.ForeignKey(
        'exams.QuestionResponse',
        on_delete=models.CASCADE,
        related_name='rubric_scores',
        help_text="Student response being evaluated"
    )
    rubric = models.ForeignKey(
        GradingRubric,
        on_delete=models.CASCADE,
        related_name='scores',
        help_text="Grading rubric applied for assessment"
    )
    scores = models.JSONField(
        help_text="Criterion-level scoring breakdown: {criterion_name: awarded_points}"
    )
    total_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Automatically calculated total score from criterion scores"
    )
    graded_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'role__in': [User.Role.INSTRUCTOR, User.Role.ADMIN]},
        related_name='assigned_scores',
        help_text="Educator who performed the assessment"
    )
    feedback_comments = models.TextField(
        blank=True,
        help_text="Comprehensive feedback on the overall response quality"
    )
    graded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['response', 'rubric']
        ordering = ['-graded_at']
        indexes = [
            models.Index(fields=['response', 'rubric']),
            models.Index(fields=['graded_by']),
            models.Index(fields=['graded_at']),
        ]
        verbose_name = "Rubric Score"
        verbose_name_plural = "Rubric Scores"

    def __str__(self):
        return f"Assessment: {self.response} | Score: {self.total_score}/{self.rubric.max_score}"

    def clean(self):
        """
        Validate scoring integrity before saving.
        Ensures criterion scores do not exceed defined maximums.
        """
        if self.rubric and self.scores:
            self.rubric.validate_scores(self.scores)

    def save(self, *args, **kwargs):
        """
        Calculate total score and validate data before persistence.
        Maintains data consistency between individual scores and total assessment.
        """
        if self.rubric and self.scores:
            self.total_score = self.rubric.calculate_score(self.scores)
        super().save(*args, **kwargs)

    @property
    def score_percentage(self):
        """Calculate achieved percentage of maximum possible score."""
        if self.rubric.max_score > 0:
            return (self.total_score / self.rubric.max_score) * 100
        return 0


class ManualGradingQueue(models.Model):
    """
    Workflow management system for tracking and assigning subjective question grading.
    Coordinates the distribution and progress monitoring of manual assessment tasks.
    """
    
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Grading'
        IN_PROGRESS = 'IN_PROGRESS', 'Grading in Progress'
        COMPLETED = 'COMPLETED', 'Grading Completed'
        REVIEW_NEEDED = 'REVIEW_NEEDED', 'Quality Review Required'

    response = models.OneToOneField(
        'exams.QuestionResponse',
        on_delete=models.CASCADE,
        related_name='grading_queue',
        help_text="Student response requiring manual assessment"
    )
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'role__in': [User.Role.INSTRUCTOR, User.Role.ADMIN]},
        related_name='assigned_gradings',
        help_text="Educator responsible for completing this assessment"
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Current workflow state of the grading task"
    )
    priority = models.PositiveIntegerField(
        default=1,
        choices=[(1, 'Low'), (2, 'Medium'), (3, 'High')],
        help_text="Urgency level for grading completion"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when grading commenced"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when grading was finalized"
    )

    class Meta:
        ordering = ['priority', '-created_at']
        indexes = [
            models.Index(fields=['status', 'assigned_to']),
            models.Index(fields=['priority']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Grading Queue Item"
        verbose_name_plural = "Grading Queue"

    def __str__(self):
        return f"Grading Task: {self.response} | Status: {self.get_status_display()}"

    def start_grading(self, grader):
        """
        Transition grading task to in-progress state.
        
        Args:
            grader (User): Educator initiating the assessment process
        """
        self.status = self.Status.IN_PROGRESS
        self.assigned_to = grader
        self.started_at = timezone.now()
        self.save()

    def complete_grading(self):
        """Mark grading task as completed with timestamp."""
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.save()

    @property
    def time_to_grade(self):
        """Calculate total time spent on grading in minutes."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() / 60
        return None


class Feedback(models.Model):
    """
    Comprehensive evaluation feedback providing detailed assessment insights.
    Supports both general comments and criterion-specific observations.
    """
    
    response = models.ForeignKey(
        QuestionResponse, 
        on_delete=models.CASCADE, 
        related_name='feedbacks',
        help_text="Student response receiving feedback"
    )
    rubric_score = models.OneToOneField(
        RubricScore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='feedback',
        help_text="Associated rubric-based scoring record"
    )
    given_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        related_name='given_feedback',
        help_text="Educator providing the feedback"
    )
    comment = models.TextField(
        help_text="Overall assessment commentary and general observations"
    )
    criterion_feedback = models.JSONField(
        default=dict,
        help_text="Targeted feedback for individual rubric criteria"
    )
    suggested_improvement = models.TextField(
        blank=True,
        help_text="Actionable recommendations for future improvement"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['response']),
            models.Index(fields=['rubric_score']),
            models.Index(fields=['given_by']),
        ]
        verbose_name = "Assessment Feedback"
        verbose_name_plural = "Assessment Feedback"

    def __str__(self):
        return f"Feedback for {self.response} by {self.given_by}"

    def get_criterion_feedback(self, criterion_name):
        """
        Retrieve specific feedback for a given criterion.
        
        Args:
            criterion_name (str): Name of the rubric criterion
            
        Returns:
            str: Feedback text for the specified criterion
        """
        return self.criterion_feedback.get(criterion_name, '')


class GradingAnalytics(models.Model):
    """
    Comprehensive analytics and performance metrics for manual grading operations.
    Provides insights into grading efficiency, quality, and workload distribution.
    """
    
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name='grading_analytics',
        help_text="Exam being analyzed for grading performance"
    )
    total_manual_questions = models.PositiveIntegerField(
        default=0,
        help_text="Total number of questions requiring manual assessment"
    )
    graded_questions = models.PositiveIntegerField(
        default=0,
        help_text="Number of questions that have been evaluated"
    )
    average_grading_time = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Mean time in minutes to complete question assessment"
    )
    grader_performance = models.JSONField(
        default=dict,
        help_text="Productivity and quality metrics by individual grader"
    )
    rubric_usage = models.JSONField(
        default=dict,
        help_text="Frequency and application statistics of grading rubrics"
    )
    score_distribution = models.JSONField(
        default=dict,
        help_text="Statistical distribution of assigned scores across evaluations"
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['exam', 'generated_at']),
        ]
        verbose_name = "Grading Analytics"
        verbose_name_plural = "Grading Analytics"

    def __str__(self):
        return f"Grading Analytics for {self.exam.title} - {self.generated_at.date()}"

    def completion_rate(self):
        """
        Calculate the percentage of completed manual assessments.
        
        Returns:
            float: Completion percentage (0-100)
        """
        if self.total_manual_questions > 0:
            return round((self.graded_questions / self.total_manual_questions) * 100, 2)
        return 0.0

    def update_metrics(self):
        """Refresh all analytics metrics based on current data."""
        # Implementation would aggregate data from various grading models
        pass


# Signal Handlers for Automated Workflow Management
@receiver(post_save, sender=QuestionResponse)
def add_to_grading_queue(sender, instance, created, **kwargs):
    """
    Automatically enqueue subjective questions for manual grading.
    Triggers when essay or short answer responses are submitted.
    """
    if (instance.question.type in ['ES', 'SA'] and  # Essay or Short Answer
        not hasattr(instance, 'grading_queue')):
        ManualGradingQueue.objects.create(response=instance)


@receiver(post_save, sender=RubricScore)
def update_response_score(sender, instance, created, **kwargs):
    """
    Propagate rubric scores to question responses upon assessment completion.
    Ensures student records reflect latest evaluation results.
    """
    if created:
        instance.response.points_awarded = instance.total_score
        instance.response.is_submitted = True
        instance.response.save()
        
        # Update grading queue status upon completion
        if hasattr(instance.response, 'grading_queue'):
            instance.response.grading_queue.complete_grading()


@receiver(post_save, sender=ManualGradingQueue)
def notify_grader_assignment(sender, instance, created, **kwargs):
    """
    Notify educators when assigned new grading tasks.
    Supports workload management and timely assessment completion.
    """
    if (instance.assigned_to and 
        instance.status == ManualGradingQueue.Status.IN_PROGRESS):
        # Notification creation logic would be implemented here
        pass


class PerformanceAnalytics(models.Model):
    """
    Comprehensive student performance metrics with support for mixed assessment types.
    Distinguishes between automatically and manually evaluated components.
    """
    
    student = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.STUDENT},
        related_name='performance_analytics',
        help_text="Student whose performance is being analyzed"
    )
    exam = models.ForeignKey(
        Exam, 
        on_delete=models.CASCADE, 
        related_name='performance_analytics',
        help_text="Exam associated with performance metrics"
    )
    overall_score = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Composite score combining automatic and manual evaluation components"
    )
    auto_graded_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text="Points earned from automatically assessed questions"
    )
    manually_graded_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text="Points earned from manually evaluated subjective responses"
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['student', 'exam']
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['student', 'exam']),
            models.Index(fields=['generated_at']),
        ]
        verbose_name = "Performance Analytics"
        verbose_name_plural = "Performance Analytics"

    def __str__(self):
        return f"Performance: {self.student} - {self.exam} - {self.overall_score}"

    @property
    def passed_exam(self):
        """
        Determine if student achieved passing score based on institutional standards.
        
        Returns:
            bool: True if overall score meets or exceeds passing threshold
        """
        return self.overall_score >= self.exam.pass_percentage

    @property
    def manual_grading_ratio(self):
        """
        Calculate proportion of score derived from manual assessment.
        
        Returns:
            float: Percentage of total score from manual evaluation (0-100)
        """
        if self.overall_score > 0:
            return (self.manually_graded_score / self.overall_score) * 100
        return 0.0