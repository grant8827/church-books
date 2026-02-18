from django.contrib import admin
from django.utils import timezone
from .models import Church
from .admin_site import church_admin_site


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
