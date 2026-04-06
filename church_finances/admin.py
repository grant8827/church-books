from django.contrib import admin
from django.utils import timezone
from datetime import timedelta
from .models import Church, Member, Contribution, Transaction, Child, BabyChristening, ChurchMember, SubscriptionPlan
from .admin_site import church_admin_site


@admin.register(SubscriptionPlan, site=church_admin_site)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'member_limit', 'annual_price', 'is_custom', 'is_active']
    list_filter  = ['is_active', 'is_custom']
    search_fields = ['name', 'slug']
    readonly_fields = ['slug']  # slug is the stable key used in code logic


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
        'subscription_status', 'is_approved',
        'plan_display', 'member_count_display',
        'payment_status_display', 'subscription_end_date', 'created_at',
    ]
    list_filter = ['subscription_status', 'is_approved', 'payment_method', 'payment_status', 'subscription_plan']
    search_fields = ['name', 'email', 'phone']
    readonly_fields = ['created_at', 'updated_at', 'offline_verified_at', 'offline_verified_by', 'member_count_display']
    actions = ['activate_churches', 'suspend_churches', 'mark_as_paid', 'mark_as_pending', 'renew_one_year']

    fieldsets = (
        ('Church Information', {
            'fields': ('name', 'logo', 'address', 'phone', 'email', 'website')
        }),
        ('Account Status', {
            'fields': ('is_approved', 'subscription_status', 'subscription_type',
                       'subscription_start_date', 'subscription_end_date')
        }),
        ('Subscription Plan', {
            'fields': ('subscription_plan', 'declared_member_count', 'subscription_amount',
                       'member_count_display'),
            'description': 'Assign a pricing tier. member_count_display shows live active member count.'
        }),
        ('Payment', {
            'fields': ('payment_method', 'payment_status',
                       'offline_payment_reference',
                       'offline_verified_by', 'offline_verified_at', 'offline_notes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # ---- Custom display ----

    def plan_display(self, obj):
        if obj.subscription_plan:
            return f"{obj.subscription_plan.name} ({obj.subscription_plan.member_limit or 'Custom'} members)"
        return '— No plan assigned'
    plan_display.short_description = 'Plan'

    def member_count_display(self, obj):
        from django.utils.html import format_html
        count = obj.active_member_count
        limit = obj.member_limit
        if limit is None:
            return format_html('<span style="color:gray;">{} (no limit)</span>', count)
        colour = 'red' if count >= limit else ('orange' if count >= limit * 0.9 else 'green')
        return format_html(
            '<span style="color:{}; font-weight:bold;">{} / {}</span>', colour, count, limit
        )
    member_count_display.short_description = 'Members (used/limit)'

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

    def payment_status_display(self, obj):
        from django.utils.html import format_html
        colour = 'green' if obj.payment_status == 'paid' else 'orange'
        label  = obj.get_payment_status_display()
        return format_html('<span style="color:{}; font-weight:bold;">{}</span>', colour, label)
    payment_status_display.short_description = 'Payment'

    # ---- Actions ----

    def activate_churches(self, request, queryset):
        now = timezone.now()
        end = now + timedelta(days=365)
        count = 0
        for church in queryset:
            church.is_approved            = True
            church.subscription_status    = 'active'
            church.is_trial_active        = False
            church.payment_status         = 'paid'
            church.subscription_start_date = now
            church.subscription_end_date   = end
            church.save(update_fields=[
                'is_approved', 'subscription_status', 'is_trial_active',
                'payment_status', 'subscription_start_date', 'subscription_end_date',
            ])
            count += 1
        self.message_user(request, f"{count} church(es) activated, marked as Paid, subscription expires {end.strftime('%d %b %Y')}.")
    activate_churches.short_description = "Activate selected churches (Paid — 1 year)"

    def suspend_churches(self, request, queryset):
        updated = queryset.update(is_approved=False, subscription_status='suspended')
        self.message_user(request, f"{updated} church(es) suspended.")
    suspend_churches.short_description = "Suspend selected churches"

    def mark_as_paid(self, request, queryset):
        updated = queryset.update(payment_status='paid')
        self.message_user(request, f"{updated} church(es) marked as Paid.")
    mark_as_paid.short_description = "Mark selected churches as Paid"

    def mark_as_pending(self, request, queryset):
        updated = queryset.update(payment_status='pending')
        self.message_user(request, f"{updated} church(es) marked as Pending.")
    mark_as_pending.short_description = "Mark selected churches as Pending payment"

    def renew_one_year(self, request, queryset):
        now = timezone.now()
        count = 0
        for church in queryset:
            # Extend from today if expired, or from existing end date if still active
            base = church.subscription_end_date if (
                church.subscription_end_date and church.subscription_end_date > now
            ) else now
            church.subscription_end_date  = base + timedelta(days=365)
            church.subscription_status    = 'active'
            church.payment_status         = 'paid'
            church.is_approved            = True
            church.save(update_fields=[
                'subscription_end_date', 'subscription_status', 'payment_status', 'is_approved',
            ])
            count += 1
        self.message_user(request, f"{count} church(es) renewed for 1 year.")
    renew_one_year.short_description = "Renew subscription by 1 year"

    def save_model(self, request, obj, form, change):
        """When a new logo is uploaded via admin, also store it as base64 for print reports."""
        logo_file = request.FILES.get('logo')
        if logo_file:
            obj.save_logo(logo_file)
        else:
            super().save_model(request, obj, form, change)
