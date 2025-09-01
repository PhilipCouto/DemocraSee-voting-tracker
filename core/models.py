from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from datetime import datetime
import re


class Parliament(models.Model):
    """Represents a parliamentary session"""
    number = models.IntegerField(unique=True, validators=[MinValueValidator(1)])
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ['-number']

    def __str__(self):
        return f"{self.number}th Parliament"


class PolicyTopic(models.Model):
    """Stores policy topic names and their associated keyword lists."""
    name = models.CharField(max_length=100, unique=True)
    keywords = models.TextField(help_text="Comma-separated list of keywords used for classification")
    parent_topic = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)
    color = models.CharField(max_length=7, default='#6B7280')  # For UI visualization

    class Meta:
        ordering = ['name']

    def keyword_list(self):
        return [kw.strip().lower() for kw in self.keywords.split(',') if kw.strip()]

    def __str__(self):
        return self.name


class MemberOfParliament(models.Model):
    """Stores high-level details about MPs"""
    PARTY_CHOICES = [
        ('CPC', 'Conservative Party of Canada'),
        ('LPC', 'Liberal Party of Canada'),
        ('NDP', 'New Democratic Party'),
        ('BQ', 'Bloc Québécois'),
        ('GP', 'Green Party of Canada'),
        ('PPC', 'People\'s Party of Canada'),
        ('IND', 'Independent'),
        ('OTHER', 'Other'),
    ]

    STATUS_CHOICES = [
        ('ACTIVE', 'Active Member of Parliament'),
        ('FORMER', 'Former Member of Parliament'),
        ('DECEASED', 'Deceased'),
    ]

    # Core identification
    name = models.CharField(max_length=255, db_index=True)
    honourific_title = models.CharField(max_length=50, blank=True)

    # Political information
    political_affiliation = models.CharField(max_length=100)
    party_code = models.CharField(max_length=10, choices=PARTY_CHOICES, default='OTHER')

    # Geographic information
    constituency = models.CharField(max_length=255, db_index=True)
    province = models.CharField(max_length=50, db_index=True)

    # Status and dates
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    first_elected = models.DateField(null=True, blank=True)
    last_active = models.DateField(null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name', 'constituency']),
            models.Index(fields=['party_code', 'status']),
        ]

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        return self.status == 'ACTIVE'


class Bill(models.Model):
    """Represents a parliamentary bill"""
    BILL_TYPES = [
        ('GOVERNMENT', 'Government Bill'),
        ('PRIVATE_MEMBER', 'Private Member\'s Bill'),
        ('PRIVATE', 'Private Bill'),
        ('SENATE_GOVERNMENT', 'Senate Government Bill'),
        ('SENATE_PRIVATE_MEMBER', 'Senate Private Member\'s Bill'),
    ]

    STATUS_CHOICES = [
        ('INTRODUCED', 'Introduced'),
        ('FIRST_READING', 'First Reading'),
        ('SECOND_READING', 'Second Reading'),
        ('COMMITTEE', 'In Committee'),
        ('REPORT_STAGE', 'Report Stage'),
        ('THIRD_READING', 'Third Reading'),
        ('SENATE', 'In Senate'),
        ('ROYAL_ASSENT', 'Received Royal Assent'),
        ('DEFEATED', 'Defeated'),
        ('WITHDRAWN', 'Withdrawn'),
    ]

    # Core identification
    bill_number = models.CharField(max_length=50, db_index=True)
    subject = models.TextField()

    # Parliamentary context
    parliament = models.ForeignKey(Parliament, on_delete=models.CASCADE)
    session = models.IntegerField(default=1, validators=[MinValueValidator(1)])

    # Bill details
    bill_type = models.CharField(max_length=30, choices=BILL_TYPES, null=True, blank=True)
    sponsor = models.ForeignKey(MemberOfParliament, on_delete=models.SET_NULL, null=True, blank=True)
    current_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='INTRODUCED')

    # Dates
    introduced_date = models.DateField(null=True, blank=True)
    last_activity_date = models.DateField(null=True, blank=True)

    # Policy classification - updated field names to match your existing scraping
    policy_tags = models.JSONField(default=list, blank=True)  # Store as JSON list
    primary_policy_area = models.CharField(max_length=100, blank=True)  # String field to match existing
    classification_confidence = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    auto_classified = models.BooleanField(default=False)
    classification_date = models.DateTimeField(null=True, blank=True)

    # URLs and metadata
    bill_url = models.URLField(max_length=500, blank=True)
    summary = models.TextField(blank=True)

    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-parliament__number', '-introduced_date']
        indexes = [
            models.Index(fields=['bill_number', 'parliament']),
            models.Index(fields=['current_status', 'parliament']),
            models.Index(fields=['introduced_date']),
        ]

    def generate_bill_url(self):
        """Generate the parl.ca URL for this bill"""
        if self.bill_number and self.parliament_id:
            # Extract proper bill code like "C-5" or "S-8"
            match = re.search(r'\b([C|S]-\d+)\b', self.bill_number.upper())
            if match:
                bill_code = match.group(1).lower()
                return f"https://www.parl.ca/legisinfo/en/bill/{self.parliament.number}-{self.session}/{bill_code}"
        return ""

    def save(self, *args, **kwargs):
        if not self.bill_url:
            self.bill_url = self.generate_bill_url()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.bill_number} - {self.subject[:50]}..."

    @property
    def is_active(self):
        return self.current_status not in ['ROYAL_ASSENT', 'DEFEATED', 'WITHDRAWN']


class VoteRecord(models.Model):
    """Represents a parliamentary vote"""
    VOTE_TYPES = [
        ('RECORDED', 'Recorded Division'),
        ('VOICE', 'Voice Vote'),
        ('STANDING', 'Standing Vote'),
    ]

    VOTE_RESULTS = [
        ('AGREED', 'Agreed to'),
        ('NEGATIVED', 'Negatived'),
        ('TIE', 'Tie'),
    ]

    # Core identification
    vote_number = models.IntegerField(db_index=True)
    subject = models.TextField()

    # Vote details
    vote_type = models.CharField(max_length=20, choices=VOTE_TYPES, default='RECORDED')
    vote_result = models.CharField(max_length=20, choices=VOTE_RESULTS)
    vote_date = models.DateField(db_index=True)

    # Parliamentary context
    parliament = models.ForeignKey(Parliament, on_delete=models.CASCADE)
    session = models.IntegerField(default=1, validators=[MinValueValidator(1)])

    # Related bill (if applicable)
    related_bill = models.ForeignKey(Bill, on_delete=models.SET_NULL, null=True, blank=True)

    # Vote counts
    yea_count = models.IntegerField(default=0)
    nay_count = models.IntegerField(default=0)
    paired_count = models.IntegerField(default=0)
    absent_count = models.IntegerField(default=0)  # Add this line

    # Policy classification (inherited from bill or manually set) - match existing structure
    policy_tags = models.JSONField(default=list, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-vote_number']
        unique_together = [['vote_number', 'parliament', 'session']]  # Add session here
        indexes = [
            models.Index(fields=['vote_date', 'parliament']),
            models.Index(fields=['vote_result']),
        ]

    def __str__(self):
        return f"Vote {self.vote_number} - {self.subject[:50]}..."

    def update_vote_counts(self):
        """Update vote counts based on related MPVote records"""
        from django.db.models import Count, Q

        counts = self.mpvote_set.aggregate(
            yea_count=Count('id', filter=Q(vote='YEA')),
            nay_count=Count('id', filter=Q(vote='NAY')),
            paired_count=Count('id', filter=Q(vote='PAIRED')),
            absent_count=Count('id', filter=Q(vote='ABSENT'))
        )

        self.yea_count = counts['yea_count']
        self.nay_count = counts['nay_count']
        self.paired_count = counts['paired_count']
        self.absent_count = counts['absent_count']
        self.save()


class MPVote(models.Model):
    """Stores how each MP voted for a given vote"""
    VOTE_CHOICES = [
        ('YEA', 'Yea'),
        ('NAY', 'Nay'),
        ('PAIRED', 'Paired'),
        ('ABSENT', 'Absent'),
    ]

    vote_record = models.ForeignKey(VoteRecord, on_delete=models.CASCADE)
    mp = models.ForeignKey(MemberOfParliament, on_delete=models.CASCADE)
    vote = models.CharField(max_length=10, choices=VOTE_CHOICES)
    parliament = models.ForeignKey(Parliament, on_delete=models.CASCADE)  # Direct parliament reference
    session = models.IntegerField(default=1)  # Session number

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('vote_record', 'mp')
        indexes = [
            models.Index(fields=['vote_record', 'vote']),
            models.Index(fields=['mp', 'vote']),
        ]

    def __str__(self):
        return f"{self.mp.name} - {self.vote} (Parliament {self.parliament.number})"


class Committee(models.Model):
    """Stores committee details"""
    COMMITTEE_TYPES = [
        ('STANDING', 'Standing Committee'),
        ('SPECIAL', 'Special Committee'),
        ('JOINT', 'Joint Committee'),
        ('OTHER', 'Other Committee'),
    ]

    committee_acronym = models.CharField(max_length=50, unique=True, db_index=True)
    committee_name = models.CharField(max_length=255)
    committee_type = models.CharField(max_length=20, choices=COMMITTEE_TYPES)

    # Parliamentary context
    # parliament = models.ForeignKey(Parliament, on_delete=models.CASCADE)
    # is_active = models.BooleanField(default=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['committee_name']

    def __str__(self):
        return f"{self.committee_name} ({self.committee_acronym})"


class CommitteeMember(models.Model):
    """Stores information about MPs who are part of a Committee"""
    ROLES = [
        ('CHAIR', 'Chair'),
        ('VICE_CHAIR', 'Vice-Chair'),
        ('MEMBER', 'Member'),
        ('ASSOCIATE', 'Associate Member'),
    ]

    committee = models.ForeignKey(Committee, on_delete=models.CASCADE)
    mp = models.ForeignKey(MemberOfParliament, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLES, default='MEMBER')

    # Dates
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('committee', 'mp', 'start_date')
        indexes = [
            models.Index(fields=['committee', 'role']),
        ]

    def __str__(self):
        return f"{self.mp.name} - {self.role} of {self.committee.committee_name}"

    @property
    def is_current(self):
        return self.end_date is None or self.end_date > timezone.now().date()


# Additional models for enhanced functionality

class MPVotingPattern(models.Model):
    """Stores aggregated voting patterns for MPs"""
    mp = models.OneToOneField(MemberOfParliament, on_delete=models.CASCADE)
    parliament = models.ForeignKey(Parliament, on_delete=models.CASCADE)

    # Voting statistics
    total_votes = models.IntegerField(default=0)
    yea_votes = models.IntegerField(default=0)
    nay_votes = models.IntegerField(default=0)
    paired_votes = models.IntegerField(default=0)
    absent_votes = models.IntegerField(default=0)

    # Party loyalty metrics
    party_line_votes = models.IntegerField(default=0)
    party_loyalty_percentage = models.FloatField(default=0.0)

    # Policy area voting counts
    policy_vote_counts = models.JSONField(default=dict)

    # Last updated
    last_calculated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('mp', 'parliament')

    def calculate_statistics(self):
        """Recalculate voting statistics for this MP"""
        # This would contain logic to aggregate MP votes
        pass


class UserWatchlist(models.Model):
    """Allows users to create watchlists of MPs and policy topics"""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    # What to watch
    watched_mps = models.ManyToManyField(MemberOfParliament, blank=True)
    watched_policy_topics = models.ManyToManyField(PolicyTopic, blank=True)
    watched_committees = models.ManyToManyField(Committee, blank=True)

    # User context (you'd integrate with your user system)
    # user = models.ForeignKey(User, on_delete=models.CASCADE)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name