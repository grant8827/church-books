from django.contrib import admin
from .models import Church, ChurchMember, Transaction
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
