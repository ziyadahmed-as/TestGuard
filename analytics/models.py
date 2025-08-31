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
    Standardized assessment framework for evaluating subjective responses.
    Provides structured criteria and performance descriptors for consistent manual grading.
    """
    
    name = models.CharField(
        max_length=100,
        help_text="Descriptive identifier for the grading rubric"
    )
    description = models.TextField(
        blank=True,
        help_text="Comprehensive overview of the rubric's purpose, application, and evaluation standards"
    )
    criteria = models.JSONField(
        help_text="Structured evaluation criteria with point allocations and performance level descriptors"
    )
    max_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
        help_text="Maximum achievable score derived from criteria point allocations"
    )
    created_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        related_name='grading_rubrics',
        help_text="Educator responsible for creating this assessment framework"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['created_by']),
            models.Index(fields=['created_at']),
            models.Index(fields=['max_score']),
        ]
        verbose_name = "Grading Rubric"
        verbose_name_plural = "Grading Rubrics"

    def __str__(self):
        return f"{self.name} (Max Score: {self.max_score})"

    def save(self, *args, **kwargs):
        """
        Calculate maximum possible score from rubric criteria before persistence.
        Maintains data integrity between criteria definitions and scoring limits.
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
        Compute total assessment score based on individual criterion evaluations.
        
        Args:
            scores (dict): Mapping of criterion names to awarded points
            
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
        Validate that provided scores comply with rubric constraints and limits.
        
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

    @property
    def criteria_count(self):
        """Return the number of evaluation criteria in this rubric."""
        return len(self.criteria) if self.criteria else 0


class RubricScore(models.Model):
    """
    Detailed scoring record for manual evaluations using standardized rubrics.
    Captures criterion-level assessments and comprehensive feedback.
    """
    
    response = models.ForeignKey(
        'exams.QuestionResponse',
        on_delete=models.CASCADE,
        related_name='rubric_scores',
        help_text="Student response being evaluated against rubric criteria"
    )
    rubric = models.ForeignKey(
        GradingRubric,
        on_delete=models.CASCADE,
        related_name='scores',
        help_text="Grading framework applied for this assessment"
    )
    scores = models.JSONField(
        help_text="Criterion-level scoring breakdown: {criterion_name: awarded_points}"
    )
    total_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Automatically calculated aggregate score from individual criterion evaluations"
    )
    graded_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'role__in': [User.Role.INSTRUCTOR, User.Role.ADMIN]},
        related_name='assigned_scores',
        help_text="Educator responsible for this evaluation"
    )
    feedback_comments = models.TextField(
        blank=True,
        help_text="Comprehensive qualitative feedback on response quality and areas for improvement"
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
            models.Index(fields=['total_score']),
        ]
        verbose_name = "Rubric Score"
        verbose_name_plural = "Rubric Scores"

    def __str__(self):
        return f"Assessment: {self.response} | Score: {self.total_score}/{self.rubric.max_score}"

    def clean(self):
        """
        Validate scoring integrity and compliance with rubric constraints.
        Ensures criterion scores do not exceed defined maximums.
        """
        if self.rubric and self.scores:
            self.rubric.validate_scores(self.scores)

    def save(self, *args, **kwargs):
        """
        Calculate total score and validate data integrity before persistence.
        Maintains consistency between individual scores and overall assessment.
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

    @property
    def grading_duration(self):
        """Calculate time taken to complete this evaluation."""
        if self.graded_at and self.response.created_at:
            return (self.graded_at - self.response.created_at).total_seconds() / 60
        return None


class ManualGradingQueue(models.Model):
    """
    Workflow management system for distributing and tracking manual assessment tasks.
    Coordinates grading assignments, priorities, and completion monitoring.
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
        help_text="Student response awaiting manual evaluation"
    )
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'role__in': [User.Role.INSTRUCTOR, User.Role.ADMIN]},
        related_name='assigned_gradings',
        help_text="Educator responsible for this assessment task"
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Current workflow state of the grading assignment"
    )
    priority = models.PositiveIntegerField(
        default=1,
        choices=[(1, 'Low'), (2, 'Medium'), (3, 'High')],
        help_text="Urgency level determining grading queue position"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when grading process commenced"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when grading process was finalized"
    )

    class Meta:
        ordering = ['priority', '-created_at']
        indexes = [
            models.Index(fields=['status', 'assigned_to']),
            models.Index(fields=['priority']),
            models.Index(fields=['created_at']),
            models.Index(fields=['started_at']),
        ]
        verbose_name = "Grading Queue Item"
        verbose_name_plural = "Grading Queue"

    def __str__(self):
        return f"Grading Task: {self.response} | Status: {self.get_status_display()}"

    def start_grading(self, grader):
        """
        Transition grading task to in-progress state with assignment tracking.
        
        Args:
            grader (User): Educator initiating the assessment process
        """
        self.status = self.Status.IN_PROGRESS
        self.assigned_to = grader
        self.started_at = timezone.now()
        self.save()

    def complete_grading(self):
        """Mark grading task as completed with completion timestamp."""
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.save()

    @property
    def time_to_grade(self):
        """Calculate total time spent on grading in minutes."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() / 60
        return None

    @property
    def queue_time(self):
        """Calculate time spent waiting in queue before assignment."""
        if self.started_at and self.created_at:
            return (self.started_at - self.created_at).total_seconds() / 60
        return None


class Feedback(models.Model):
    """
    Comprehensive evaluation feedback with structured qualitative assessment.
    Supports both holistic comments and criterion-specific observations.
    """
    
    response = models.ForeignKey(
        QuestionResponse, 
        on_delete=models.CASCADE, 
        related_name='feedbacks',
        help_text="Student response receiving evaluation feedback"
    )
    rubric_score = models.OneToOneField(
        RubricScore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='feedback',
        help_text="Associated quantitative scoring record"
    )
    given_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        related_name='given_feedback',
        help_text="Educator providing the assessment feedback"
    )
    comment = models.TextField(
        help_text="Comprehensive overall commentary on response quality and performance"
    )
    criterion_feedback = models.JSONField(
        default=dict,
        help_text="Targeted feedback for individual rubric criteria with specific observations"
    )
    suggested_improvement = models.TextField(
        blank=True,
        help_text="Actionable recommendations for future development and enhancement"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['response']),
            models.Index(fields=['rubric_score']),
            models.Index(fields=['given_by']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Assessment Feedback"
        verbose_name_plural = "Assessment Feedback"

    def __str__(self):
        return f"Feedback for {self.response} by {self.given_by}"

    def get_criterion_feedback(self, criterion_name):
        """
        Retrieve specific feedback for a given evaluation criterion.
        
        Args:
            criterion_name (str): Name of the rubric criterion
            
        Returns:
            str: Detailed feedback text for the specified criterion
        """
        return self.criterion_feedback.get(criterion_name, '')

    @property
    def feedback_completeness(self):
        """Calculate completeness score based on feedback components."""
        components = [
            bool(self.comment.strip()),
            bool(self.criterion_feedback),
            bool(self.suggested_improvement.strip())
        ]
        return sum(components) / len(components) * 100


class GradingAnalytics(models.Model):
    """
    Comprehensive analytics and performance metrics for manual grading operations.
    Provides insights into efficiency, quality, and workload distribution patterns.
    """
    
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name='grading_analytics',
        help_text="Exam being analyzed for grading performance metrics"
    )
    total_manual_questions = models.PositiveIntegerField(
        default=0,
        help_text="Total number of questions requiring manual evaluation"
    )
    graded_questions = models.PositiveIntegerField(
        default=0,
        help_text="Number of questions that have been completely assessed"
    )
    average_grading_time = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Mean time in minutes to complete question evaluation"
    )
    grader_performance = models.JSONField(
        default=dict,
        help_text="Productivity, consistency, and quality metrics by individual grader"
    )
    rubric_usage = models.JSONField(
        default=dict,
        help_text="Frequency distribution and application statistics of grading rubrics"
    )
    score_distribution = models.JSONField(
        default=dict,
        help_text="Statistical distribution of assigned scores across all evaluations"
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['exam', 'generated_at']),
            models.Index(fields=['total_manual_questions']),
            models.Index(fields=['graded_questions']),
        ]
        verbose_name = "Grading Analytics"
        verbose_name_plural = "Grading Analytics"

    def __str__(self):
        return f"Grading Analytics for {self.exam.title} - {self.generated_at.date()}"

    def completion_rate(self):
        """
        Calculate the percentage of completed manual assessments.
        
        Returns:
            float: Completion percentage (0-100) with two decimal precision
        """
        if self.total_manual_questions > 0:
            return round((self.graded_questions / self.total_manual_questions) * 100, 2)
        return 0.0

    def update_metrics(self):
        """
        Refresh all analytics metrics based on current grading data.
        Aggregates performance statistics from various assessment models.
        """
        # Implementation would aggregate data from RubricScore, ManualGradingQueue, etc.
        pass

    @property
    def pending_grading_count(self):
        """Calculate number of questions still awaiting evaluation."""
        return self.total_manual_questions - self.graded_questions

    @property
    def estimated_completion_time(self):
        """Estimate time required to complete remaining grading."""
        if self.average_grading_time and self.pending_grading_count > 0:
            return self.average_grading_time * self.pending_grading_count
        return None


class PerformanceAnalytics(models.Model):
    """
    Comprehensive student performance metrics with detailed assessment breakdown.
    Distinguishes between automated and manual evaluation components.
    """
    
    student = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.Role.STUDENT},
        related_name='performance_analytics',
        help_text="Student whose academic performance is being analyzed"
    )
    exam = models.ForeignKey(
        Exam, 
        on_delete=models.CASCADE, 
        related_name='performance_analytics',
        help_text="Assessment associated with these performance metrics"
    )
    overall_score = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Composite score combining all assessment components"
    )
    auto_graded_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text="Points earned from automatically evaluated objective questions"
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
            models.Index(fields=['overall_score']),
        ]
        verbose_name = "Performance Analytics"
        verbose_name_plural = "Performance Analytics"

    def __str__(self):
        return f"Performance: {self.student} - {self.exam} - Score: {self.overall_score}"

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
        Calculate proportion of total score derived from manual assessment.
        
        Returns:
            float: Percentage of total score from manual evaluation (0-100)
        """
        if self.overall_score > 0:
            return (self.manually_graded_score / self.overall_score) * 100
        return 0.0

    @property
    def performance_quartile(self):
        """
        Estimate performance quartile based on institutional grading patterns.
        
        Returns:
            int: Estimated quartile position (1-4) or None if insufficient data
        """
        # Implementation would compare with cohort performance data
        return None

    @property
    def score_consistency(self):
        """
        Calculate consistency score across different assessment types.
        
        Returns:
            float: Consistency metric between auto and manual grading components
        """
        if self.overall_score > 0:
            auto_ratio = self.auto_graded_score / self.overall_score
            manual_ratio = self.manually_graded_score / self.overall_score
            return 100 - (abs(auto_ratio - manual_ratio) * 50)
        return 0.0


# Signal Handlers for Automated Workflow Management
@receiver(post_save, sender=QuestionResponse)
def add_to_grading_queue(sender, instance, created, **kwargs):
    """
    Automatically enqueue subjective questions for manual grading upon submission.
    Triggers when essay or short answer responses are created or updated.
    """
    if (instance.question.type in ['ES', 'SA'] and  # Essay or Short Answer
        not hasattr(instance, 'grading_queue')):
        ManualGradingQueue.objects.create(response=instance)


@receiver(post_save, sender=RubricScore)
def update_response_score(sender, instance, created, **kwargs):
    """
    Propagate rubric evaluation scores to question responses upon completion.
    Ensures student records reflect latest assessment results automatically.
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
    Notify educators when assigned new grading tasks for timely response.
    Supports efficient workload management and assessment turnaround.
    """
    if (instance.assigned_to and 
        instance.status == ManualGradingQueue.Status.IN_PROGRESS):
        # Notification creation logic would be implemented here
        # Example: send email or push notification to assigned grader
        pass


class AssessmentTrend(models.Model):
    """
    Longitudinal tracking of assessment patterns and performance trends over time.
    Provides historical analysis for curriculum development and instructional improvement.
    """
    
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name='assessment_trends',
        help_text="Exam being tracked for longitudinal analysis"
    )
    period_start = models.DateTimeField(
        help_text="Start of the analysis period"
    )
    period_end = models.DateTimeField(
        help_text="End of the analysis period"
    )
    average_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Mean score across all attempts during this period"
    )
    pass_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Percentage of passing attempts during this period"
    )
    common_misconceptions = models.JSONField(
        default=dict,
        help_text="Frequently identified knowledge gaps and misunderstanding patterns"
    )
    question_difficulty = models.JSONField(
        default=dict,
        help_text="Difficulty analysis for individual exam questions"
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-period_end']
        indexes = [
            models.Index(fields=['exam', 'period_end']),
            models.Index(fields=['average_score']),
            models.Index(fields=['pass_rate']),
        ]
        verbose_name = "Assessment Trend"
        verbose_name_plural = "Assessment Trends"

    def __str__(self):
        return f"Trend Analysis: {self.exam.title} - {self.period_end.date()}"

    @property
    def period_duration(self):
        """Calculate the duration of the analysis period in days."""
        return (self.period_end - self.period_start).days

    @property
    def performance_trend(self):
        """
        Calculate performance trend direction compared to previous periods.
        
        Returns:
            str: Trend direction ('improving', 'declining', 'stable')
        """
        # Implementation would compare with historical data
        return 'stable'