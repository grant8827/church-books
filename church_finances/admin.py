from django.contrib import admin
from django.utils import timezone
from .models import Church, Member, Contribution, Transaction, Child, BabyChristening, ChurchMember
from .admin_site import church_admin_site


@admin.register(Member, site=church_admin_site)
class MemberAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'phone_number', 'church', 'is_active', 'membership_date']
    list_filter = ['church', 'is_active', 'marital_status']
    search_fields = ['first_name', 'last_name', 'email', 'phone_number']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Contribution, site=church_admin_site)
class ContributionAdmin(admin.ModelAdmin):
    list_display = ['member', 'church', 'date', 'contribution_type', 'amount', 'payment_method']
    list_filter = ['church', 'contribution_type', 'payment_method']
    search_fields = ['member__first_name', 'member__last_name', 'reference_number']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'date'


@admin.register(Transaction, site=church_admin_site)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['date', 'type', 'category', 'amount', 'church', 'recorded_by']
    list_filter = ['church', 'type', 'category']
    search_fields = ['description', 'category']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'date'


@admin.register(Child, site=church_admin_site)
class ChildAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'last_name', 'church', 'date_of_birth', 'is_active']
    list_filter = ['church', 'is_active', 'grade_level']
    search_fields = ['first_name', 'last_name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(BabyChristening, site=church_admin_site)
class BabyChristeningAdmin(admin.ModelAdmin):
    list_display = ['baby_first_name', 'baby_last_name', 'church', 'christening_date', 'is_active']
    list_filter = ['church', 'is_active']
    search_fields = ['baby_first_name', 'baby_last_name', 'father_name', 'mother_name']
    readonly_fields = ['date_recorded', 'last_modified']


@admin.register(ChurchMember, site=church_admin_site)
class ChurchMemberAdmin(admin.ModelAdmin):
    list_display = ['user', 'church', 'role', 'is_active', 'created_at']
    list_filter = ['church', 'role', 'is_active']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    readonly_fields = ['created_at', 'updated_at']





@admin.register(Church, site=church_admin_site)
class ChurchAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'email', 'phone', 'payment_method',
        'subscription_status', 'is_approved', 'payment_status_badge', 'created_at',
    ]
    list_filter = ['subscription_status', 'is_approved', 'payment_method']
    search_fields = ['name', 'email', 'phone']
    readonly_fields = ['created_at', 'updated_at', 'offline_verified_at', 'offline_verified_by']
    actions = ['activate_churches', 'suspend_churches']

    fieldsets = (
        ('Church Information', {
            'fields': ('name', 'logo', 'address', 'phone', 'email', 'website')
        }),
        ('Account Status', {
            'fields': ('is_approved', 'subscription_status', 'subscription_type',
                       'subscription_start_date', 'subscription_end_date')
        }),
        ('Payment', {
            'fields': ('payment_method', 'offline_payment_reference',
                       'offline_verified_by', 'offline_verified_at', 'offline_notes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # ---- Custom display ----

    def payment_status_badge(self, obj):
        from django.utils.html import format_html
        status = obj.offline_verified_status()
        if 'Verified' in status or obj.subscription_status == 'active':
            colour = 'green'
        elif 'Pending' in status:
            colour = 'orange'
        else:
            colour = 'gray'
        return format_html(
            '<span style="color:{}; font-weight:bold;">{}</span>', colour, status
        )
    payment_status_badge.short_description = 'Payment Status'

    # ---- Actions ----

    def activate_churches(self, request, queryset):
        updated = queryset.update(
            is_approved=True,
            subscription_status='active',
            is_trial_active=False,   # subscription is live — remove the free trial
        )
        self.message_user(request, f"{updated} church(es) activated successfully.")
    activate_churches.short_description = "Activate selected churches"

    def suspend_churches(self, request, queryset):
        updated = queryset.update(is_approved=False, subscription_status='suspended')
        self.message_user(request, f"{updated} church(es) suspended.")
    suspend_churches.short_description = "Suspend selected churches"

    def save_model(self, request, obj, form, change):
        """When a new logo is uploaded via admin, also store it as base64 for print reports."""
        logo_file = request.FILES.get('logo')
        if logo_file:
            obj.save_logo(logo_file)
        else:
            super().save_model(request, obj, form, change)
