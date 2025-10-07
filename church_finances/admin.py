from django.contrib import admin
from .models import Church, ChurchMember, Transaction, Child, ChildAttendance, BabyChristening
from .admin_site import church_admin_site

@admin.register(Church, site=church_admin_site)
class ChurchAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'is_approved', 'created_at')
    list_filter = ('is_approved',)
    search_fields = ('name', 'email')
    actions = ['approve_churches', 'reject_churches']

    def approve_churches(self, request, queryset):
        queryset.update(is_approved=True)
    approve_churches.short_description = "Approve selected churches"

    def reject_churches(self, request, queryset):
        queryset.delete()
    reject_churches.short_description = "Reject selected churches"

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
