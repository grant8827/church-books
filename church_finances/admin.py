from django.contrib import admin
from django.utils import timezone
from .models import Church, ChurchMember, Transaction, Child, ChildAttendance, BabyChristening
from .admin_site import church_admin_site

@admin.register(Church, site=church_admin_site)
class ChurchAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'email', 'subscription_type', 'subscription_status', 'is_approved', 
        'payment_method', 'offline_verified_status', 'created_at', 'subscription_start_date', 'subscription_end_date'
    ]
    list_filter = ['is_approved', 'subscription_type', 'subscription_status', 'payment_method', 'created_at', 'offline_verified_at']
    search_fields = ['name', 'email', 'phone', 'offline_payment_reference']
    actions = ['approve_churches', 'reject_churches', 'mark_offline_payment_verified']

    def approve_churches(self, request, queryset):
        queryset.update(is_approved=True)
    approve_churches.short_description = "Approve selected churches"

    def reject_churches(self, request, queryset):
        """Action to reject multiple churches"""
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"Successfully rejected {count} church(es).")
    reject_churches.short_description = "Reject selected churches"
    
    def mark_offline_payment_verified(self, request, queryset):
        """Action to mark offline payments as verified"""
        offline_churches = queryset.filter(payment_method='offline', offline_verified_at__isnull=True)
        count = 0
        for church in offline_churches:
            church.offline_verified_at = timezone.now()
            church.offline_verified_by = request.user
            church.offline_payment_reference = f"ADMIN_VERIFIED_{church.id}"
            church.save()
            count += 1
        self.message_user(request, f"Marked {count} offline payment(s) as verified.")
    mark_offline_payment_verified.short_description = "Mark offline payments as verified"

@admin.register(ChurchMember, site=church_admin_site)
class ChurchMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'church', 'role', 'is_active', 'created_at')
    list_filter = ('role', 'is_active', 'church')
    search_fields = ('user__username', 'church__name')

@admin.register(Transaction, site=church_admin_site)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'type', 'category', 'amount', 'church', 'recorded_by')
    list_filter = ('type', 'category', 'church')
    search_fields = ('description', 'church__name', 'recorded_by__username')
    date_hierarchy = 'date'

@admin.register(Child, site=church_admin_site)
class ChildAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'age', 'grade_level', 'sunday_school_class', 'church', 'is_active')
    list_filter = ('grade_level', 'sunday_school_class', 'church', 'is_active')
    search_fields = ('first_name', 'last_name', 'parents__user__first_name', 'parents__user__last_name')
    filter_horizontal = ('parents',)
    fieldsets = (
        ('Basic Information', {
            'fields': ('first_name', 'last_name', 'date_of_birth', 'grade_level')
        }),
        ('Church Information', {
            'fields': ('church', 'parents', 'sunday_school_class', 'baptism_date')
        }),
        ('Emergency Contact', {
            'fields': ('emergency_contact_name', 'emergency_contact_phone', 'emergency_contact_relationship')
        }),
        ('Medical Information', {
            'fields': ('allergies', 'medications', 'medical_notes'),
            'classes': ('collapse',)
        }),
        ('Contact Information', {
            'fields': ('address', 'phone_number'),
            'classes': ('collapse',)
        }),
        ('Status & Notes', {
            'fields': ('is_active', 'notes')
        })
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # If creating a new child
            obj.added_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(ChildAttendance, site=church_admin_site)
class ChildAttendanceAdmin(admin.ModelAdmin):
    list_display = ('child', 'activity_type', 'date', 'present', 'church')
    list_filter = ('activity_type', 'present', 'date', 'church')
    search_fields = ('child__first_name', 'child__last_name', 'activity_name')
    date_hierarchy = 'date'
    
    def save_model(self, request, obj, form, change):
        if not change:  # If creating a new attendance record
            obj.recorded_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(BabyChristening, site=church_admin_site)
class BabyChristeningAdmin(admin.ModelAdmin):
    list_display = ('baby_full_name', 'christening_date', 'parents_list', 'pastor', 'church', 'is_active')
    list_filter = ('christening_date', 'church', 'is_active', 'pastor')
    search_fields = ('baby_first_name', 'baby_last_name', 'father_name', 'mother_name', 'pastor')
    filter_horizontal = ('parent_members',)
    date_hierarchy = 'christening_date'
    
    fieldsets = (
        ('Baby Information', {
            'fields': ('baby_first_name', 'baby_last_name', 'baby_date_of_birth')
        }),
        ('Christening Details', {
            'fields': ('christening_date', 'christening_time', 'pastor', 'ceremony_notes', 'certificate_number')
        }),
        ('Parents Information', {
            'fields': ('father_name', 'mother_name', 'parent_members')
        }),
        ('Godparents Information', {
            'fields': ('godfather_name', 'godmother_name', 'other_godparents'),
            'classes': ('collapse',)
        }),
        ('Contact Information', {
            'fields': ('contact_address', 'contact_phone', 'contact_email'),
            'classes': ('collapse',)
        }),
        ('Administrative', {
            'fields': ('church', 'is_active')
        })
    )
    
    readonly_fields = ('baby_age_at_christening',)
    
    def save_model(self, request, obj, form, change):
        if not change:  # If creating a new christening record
            obj.recorded_by = request.user
        super().save_model(request, obj, form, change)
