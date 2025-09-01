from django.contrib import admin
from django.utils.html import format_html
from django.db import models
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import (
    Parliament, Bill, VoteRecord, MemberOfParliament, MPVote,
    Committee, CommitteeMember, PolicyTopic, MPVotingPattern, UserWatchlist
)


# 1. Parliament Admin
@admin.register(Parliament)
class ParliamentAdmin(admin.ModelAdmin):
    list_display = ('number', 'start_date', 'end_date', 'is_current', 'bill_count', 'vote_count')
    list_filter = ('is_current',)
    search_fields = ('number',)
    ordering = ('-number',)

    def bill_count(self, obj):
        return obj.bill_set.count()

    bill_count.short_description = 'Bills'

    def vote_count(self, obj):
        return obj.voterecord_set.count()

    vote_count.short_description = 'Votes'


# 2. Policy Topic Admin
@admin.register(PolicyTopic)
class PolicyTopicAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent_topic', 'color_preview', 'keyword_count')
    list_filter = ('parent_topic',)
    search_fields = ('name', 'keywords')
    ordering = ('name',)

    def color_preview(self, obj):
        return format_html(
            '<div style="width: 20px; height: 20px; background-color: {}; border: 1px solid #ccc;"></div>',
            obj.color
        )
    color_preview.short_description = 'Color'

    def keyword_count(self, obj):
        return len(obj.keyword_list())
    keyword_count.short_description = 'Keywords'


# 3. Member of Parliament Admin
@admin.register(MemberOfParliament)
class MemberOfParliamentAdmin(admin.ModelAdmin):
    list_display = ('name', 'party_code', 'constituency', 'province', 'status', 'vote_count', 'committee_count')
    list_filter = ('party_code', 'status', 'province')
    search_fields = ('name', 'constituency', 'political_affiliation')
    ordering = ('name',)

    fieldsets = (
        ('Personal Information', {
            'fields': ('honourific_title', 'name')
        }),
        ('Political Information', {
            'fields': ('political_affiliation', 'party_code')
        }),
        ('Geographic Information', {
            'fields': ('constituency', 'province')
        }),
        ('Status & Dates', {
            'fields': ('status', 'first_elected', 'last_active')
        }),
    )

    readonly_fields = ('created_at', 'updated_at')

    def vote_count(self, obj):
        return obj.mpvote_set.count()

    vote_count.short_description = 'Votes Cast'

    def committee_count(self, obj):
        return obj.committeemember_set.filter(end_date__isnull=True).count()

    committee_count.short_description = 'Active Committees'


# 4. Bill Admin
@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = (
        'bill_number', 'subject_preview', 'parliament', 'sponsor', 'current_status',
        'primary_policy_area', 'classification_confidence', 'vote_count', 'bill_link'
    )
    list_filter = (
        'parliament', 'current_status', 'bill_type', 'primary_policy_area',
        'auto_classified', 'introduced_date'
    )
    search_fields = ('bill_number', 'subject', 'sponsor__name')
    ordering = ('-parliament__number', '-introduced_date')

    fieldsets = (
        ('Basic Information', {
            'fields': ('bill_number', 'subject', 'summary')
        }),
        ('Parliamentary Context', {
            'fields': ('parliament', 'session', 'bill_type', 'sponsor')
        }),
        ('Status & Dates', {
            'fields': ('current_status', 'introduced_date', 'last_activity_date')
        }),
        ('Policy Classification', {
            'fields': (
                'policy_tags', 'primary_policy_area', 'classification_confidence',
                'auto_classified', 'classification_date'
            ),
            'classes': ('collapse',)
        }),
        ('URLs & Metadata', {
            'fields': ('bill_url', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ('bill_url', 'created_at', 'updated_at')

    def subject_preview(self, obj):
        return obj.subject[:50] + '...' if len(obj.subject) > 50 else obj.subject

    subject_preview.short_description = 'Subject'

    def vote_count(self, obj):
        return obj.voterecord_set.count()

    vote_count.short_description = 'Votes'

    def bill_link(self, obj):
        if obj.bill_url:
            return format_html('<a href="{}" target="_blank">View Bill</a>', obj.bill_url)
        return '-'

    bill_link.short_description = 'External Link'


# 5. Vote Record Admin
@admin.register(VoteRecord)
class VoteRecordAdmin(admin.ModelAdmin):
    list_display = (
        'vote_number', 'subject_preview', 'vote_result', 'vote_date',
        'parliament', 'session', 'related_bill', 'vote_summary', 'policy_topics_display'
    )
    list_filter = ('vote_result', 'vote_type', 'parliament', 'session', 'vote_date')
    search_fields = ('vote_number', 'subject', 'related_bill__bill_number')
    ordering = ('-vote_number',)
    date_hierarchy = 'vote_date'

    fieldsets = (
        ('Basic Information', {
            'fields': ('vote_number', 'subject')
        }),
        ('Vote Details', {
            'fields': ('vote_type', 'vote_result', 'vote_date')
        }),
        ('Parliamentary Context', {
            'fields': ('parliament', 'session', 'related_bill')
        }),
        ('Vote Counts', {
            'fields': ('yea_count', 'nay_count', 'paired_count'),
            'classes': ('collapse',)
        }),
        ('Policy Classification', {
            'fields': ('policy_tags',),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ('yea_count', 'nay_count', 'paired_count', 'created_at', 'updated_at')

    def subject_preview(self, obj):
        return obj.subject[:60] + '...' if len(obj.subject) > 60 else obj.subject

    subject_preview.short_description = 'Subject'

    def vote_summary(self, obj):
        return f"Y:{obj.yea_count} N:{obj.nay_count} P:{obj.paired_count}"

    vote_summary.short_description = 'Y/N/P'

    def policy_topics_display(self, obj):
        if obj.policy_tags and isinstance(obj.policy_tags, list):
            return ', '.join(obj.policy_tags[:3])
        return '-'

    policy_topics_display.short_description = 'Policy Tags'

    actions = ['update_vote_counts']

    def update_vote_counts(self, request, queryset):
        for vote_record in queryset:
            vote_record.update_vote_counts()
        self.message_user(request, f"Updated vote counts for {queryset.count()} records.")

    update_vote_counts.short_description = "Update vote counts"


# 6. MP Vote Admin
@admin.register(MPVote)
class MPVoteAdmin(admin.ModelAdmin):
    list_display = ('mp_name', 'parliament_number', 'vote_number', 'vote_subject_preview', 'vote', 'mp_party')
    list_filter = ('vote', 'mp__party_code', 'parliament', 'vote_record__vote_date')
    search_fields = ('mp__name', 'vote_record__vote_number', 'vote_record__subject')
    ordering = ('-vote_record__vote_number', 'mp__name')

    def mp_name(self, obj):
        return obj.mp.name

    mp_name.short_description = 'MP'
    mp_name.admin_order_field = 'mp__name'

    def vote_number(self, obj):
        return obj.vote_record.vote_number

    vote_number.short_description = 'Vote #'
    vote_number.admin_order_field = 'vote_record__vote_number'

    def vote_subject_preview(self, obj):
        subject = obj.vote_record.subject
        return subject[:40] + '...' if len(subject) > 40 else subject

    vote_subject_preview.short_description = 'Subject'

    def mp_party(self, obj):
        return obj.mp.party_code

    mp_party.short_description = 'Party'
    mp_party.admin_order_field = 'mp__party_code'

    def parliament_number(self, obj):
        return f"Parliament {obj.parliament.number}"

    parliament_number.short_description = 'Parliament'


# 7. Committee Admin
@admin.register(Committee)
class CommitteeAdmin(admin.ModelAdmin):
    list_display = ('committee_name', 'committee_acronym', 'committee_type', 'member_count')
    list_filter = ('committee_type',)
    search_fields = ('committee_name', 'committee_acronym')
    ordering = ('committee_name',)

    def member_count(self, obj):
        return obj.committeemember_set.filter(end_date__isnull=True).count()

    member_count.short_description = 'Active Members'


# 8. Committee Member Admin
@admin.register(CommitteeMember)
class CommitteeMemberAdmin(admin.ModelAdmin):
    list_display = ('mp_name', 'committee_name', 'role', 'start_date', 'end_date', 'is_current')
    list_filter = ('role', 'committee__committee_type', 'start_date', 'end_date')
    search_fields = ('mp__name', 'committee__committee_name')
    ordering = ('committee__committee_name', 'role', 'mp__name')
    date_hierarchy = 'start_date'

    def mp_name(self, obj):
        return obj.mp.name

    mp_name.short_description = 'MP'
    mp_name.admin_order_field = 'mp__name'

    def committee_name(self, obj):
        return obj.committee.committee_name

    committee_name.short_description = 'Committee'
    committee_name.admin_order_field = 'committee__committee_name'

    def is_current(self, obj):
        return obj.is_current

    is_current.boolean = True
    is_current.short_description = 'Current'


# 9. MP Voting Pattern Admin
@admin.register(MPVotingPattern)
class MPVotingPatternAdmin(admin.ModelAdmin):
    list_display = (
        'mp_name', 'parliament', 'total_votes', 'party_loyalty_percentage',
        'voting_activity', 'last_calculated'
    )
    list_filter = ('parliament', 'last_calculated')
    search_fields = ('mp__name',)
    ordering = ('-party_loyalty_percentage',)
    readonly_fields = ('last_calculated',)

    def mp_name(self, obj):
        return obj.mp.name

    mp_name.short_description = 'MP'
    mp_name.admin_order_field = 'mp__name'

    def voting_activity(self, obj):
        if obj.total_votes > 0:
            active_percentage = ((obj.yea_votes + obj.nay_votes) / obj.total_votes) * 100
            return f"{active_percentage:.1f}%"
        return "0%"

    voting_activity.short_description = 'Activity Rate'

    actions = ['recalculate_statistics']

    def recalculate_statistics(self, request, queryset):
        for pattern in queryset:
            pattern.calculate_statistics()
        self.message_user(request, f"Recalculated statistics for {queryset.count()} MPs.")

    recalculate_statistics.short_description = "Recalculate voting statistics"


# 10. User Watchlist Admin
@admin.register(UserWatchlist)
class UserWatchlistAdmin(admin.ModelAdmin):
    list_display = ('name', 'description_preview', 'mp_count', 'topic_count', 'created_at')
    search_fields = ('name', 'description')
    ordering = ('-created_at',)
    filter_horizontal = ('watched_mps', 'watched_policy_topics', 'watched_committees')

    def description_preview(self, obj):
        return obj.description[:50] + '...' if len(obj.description) > 50 else obj.description

    description_preview.short_description = 'Description'

    def mp_count(self, obj):
        return obj.watched_mps.count()

    mp_count.short_description = 'MPs'

    def topic_count(self, obj):
        return obj.watched_policy_topics.count()

    topic_count.short_description = 'Topics'


# Custom admin site configuration
admin.site.site_header = "Parliamentary Voting Records Admin"
admin.site.site_title = "Parliament Admin"
admin.site.index_title = "Welcome to Parliamentary Data Administration"


# Group related models in the admin interface
class ParliamentaryDataAdminConfig:
    """Configuration for grouping admin models"""
    pass