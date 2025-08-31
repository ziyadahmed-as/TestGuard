from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from core.models import User
from exams.models import ExamAttempt, QuestionResponse, Exam
from django.utils import timezone
class GradingRubric(models.Model):
    """Rubric for consistent grading of subjective questions."""
    name = models.CharField(max_length=100)
    criteria = models.JSONField(help_text="Structured grading criteria with point allocations")
    created_by = models.ForeignKey(
        User, 
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        on_delete=models.CASCADE, 
        related_name='grading_rubrics'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['created_by']),
        ]

    def __str__(self):
        return self.name

class Feedback(models.Model):
    """Instructor feedback on student responses."""
    response = models.ForeignKey(
        QuestionResponse, 
        on_delete=models.CASCADE, 
        related_name='feedbacks'
    )
    given_by = models.ForeignKey(
        User, 
        limit_choices_to={'role': User.Role.INSTRUCTOR},
        on_delete=models.CASCADE, 
        related_name='given_feedback'
    )
    comment = models.TextField()
    suggested_improvement = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['response']),
        ]

    def __str__(self):
        return f"Feedback for {self.response} by {self.given_by}"

class ExamReport(models.Model):
    """Generated exam reports and analytics."""
    class ReportType(models.TextChoices):
        SUMMARY = 'SUMMARY', 'Summary Report'
        DETAILED = 'DETAILED', 'Detailed Report'
        ITEM_ANALYSIS = 'ITEM_ANALYSIS', 'Item Analysis'
        COMPARATIVE = 'COMPARATIVE', 'Comparative Report'
        CONCURRENCY = 'CONCURRENCY', 'Concurrency Report'

    exam = models.ForeignKey(
        Exam, 
        on_delete=models.CASCADE, 
        related_name='reports'
    )
    report_type = models.CharField(max_length=20, choices=ReportType.choices)
    generated_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='generated_reports'
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    data = models.JSONField(help_text="Structured report data")
    format = models.CharField(
        max_length=10, 
        choices=[('PDF', 'PDF'), ('EXCEL', 'Excel'), ('JSON', 'JSON')],
        default='PDF'
    )
    file_size = models.PositiveIntegerField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['exam', 'report_type']),
        ]

    def __str__(self):
        return f"{self.exam.title} - {self.get_report_type_display()}"

    def increment_download_count(self):
        """Increment the download counter."""
        self.download_count += 1
        self.save(update_fields=['download_count'])

class PerformanceAnalytics(models.Model):
    """Student performance analytics and metrics."""
    student = models.ForeignKey(
        User, 
        limit_choices_to={'role': User.Role.STUDENT},
        on_delete=models.CASCADE, 
        related_name='performance_analytics'
    )
    exam = models.ForeignKey(
        Exam, 
        on_delete=models.CASCADE, 
        related_name='performance_analytics'
    )
    overall_score = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    percentile_rank = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    time_spent = models.PositiveIntegerField(help_text="Time spent in seconds")
    question_breakdown = models.JSONField(help_text="Detailed question-level performance")
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['student', 'exam']
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['student', 'exam']),
        ]

    def __str__(self):
        return f"Performance for {self.student} on {self.exam}"

class SecurityEvent(models.Model):
    """Track security-related events including concurrency violations."""
    class EventType(models.TextChoices):
        MULTI_DEVICE_ATTEMPT = 'MULTI_DEVICE', 'Multiple Device Attempt'
        SESSION_TIMEOUT = 'SESSION_TIMEOUT', 'Session Timeout'
        IP_CHANGE = 'IP_CHANGE', 'IP Address Change'
        BROWSER_CHANGE = 'BROWSER_CHANGE', 'Browser Change'
        AUTO_SAVE_FAILURE = 'AUTO_SAVE_FAILURE', 'Auto-Save Failure'

    attempt = models.ForeignKey(
        ExamAttempt, 
        on_delete=models.CASCADE, 
        related_name='security_events'
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    description = models.TextField()
    severity = models.PositiveIntegerField(
        choices=[(1, 'Low'), (2, 'Medium'), (3, 'High')], 
        default=2
    )
    detected_by = models.CharField(max_length=100, default='System')
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        User, 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL,
        related_name='resolved_events'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['attempt', 'event_type']),
            models.Index(fields=['resolved', 'severity']),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.attempt}"

    def mark_resolved(self, resolved_by):
        """Mark this security event as resolved."""
        self.resolved = True
        self.resolved_by = resolved_by
        self.resolved_at = timezone.now()
        self.save()

class ConcurrencyReport(models.Model):
    """Reports on exam concurrency violations and patterns."""
    exam = models.ForeignKey(
        Exam, 
        on_delete=models.CASCADE, 
        related_name='concurrency_reports'
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    total_attempts = models.PositiveIntegerField()
    multi_device_attempts = models.PositiveIntegerField()
    terminated_sessions = models.PositiveIntegerField()
    avg_auto_saves_per_attempt = models.DecimalField(
        max_digits=8, 
        decimal_places=2
    )
    details = models.JSONField(default=dict)

    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['exam', 'generated_at']),
        ]

    def __str__(self):
        return f"Concurrency Report for {self.exam.title}"

    def violation_rate(self):
        """Calculate the percentage of attempts with concurrency violations."""
        if self.total_attempts > 0:
            return (self.multi_device_attempts / self.total_attempts) * 100
        return 0

class Notification(models.Model):
    """System notifications and alerts."""
    class NotificationType(models.TextChoices):
        EXAM_REMINDER = 'EXAM_REMINDER', 'Exam Reminder'
        GRADE_PUBLISHED = 'GRADE_PUBLISHED', 'Grade Published'
        SYSTEM_ALERT = 'SYSTEM_ALERT', 'System Alert'
        SECURITY_FLAG = 'SECURITY_FLAG', 'Security Flag'
        AUTO_SAVE_SUMMARY = 'AUTO_SAVE_SUMMARY', 'Auto-Save Summary'

    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='notifications'
    )
    notification_type = models.CharField(max_length=20, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    priority = models.PositiveIntegerField(
        choices=[(1, 'Low'), (2, 'Medium'), (3, 'High')],
        default=2
    )
    related_attempt = models.ForeignKey(
        ExamAttempt, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='notifications'
    )
    action_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['notification_type', 'created_at']),
        ]

    def __str__(self):
        return f"{self.notification_type}: {self.title}"

    def mark_as_read(self):
        """Mark notification as read."""
        self.is_read = True
        self.save(update_fields=['is_read'])

    @classmethod
    def create_auto_save_summary(cls, attempt, save_count, success_rate):
        """Create an auto-save summary notification."""
        return cls.objects.create(
            user=attempt.student,
            notification_type=cls.NotificationType.AUTO_SAVE_SUMMARY,
            title="Exam Progress Auto-Saved",
            message=f"Your exam progress has been automatically saved {save_count} times with {success_rate}% success rate.",
            related_attempt=attempt,
            priority=1
        )