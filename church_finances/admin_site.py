from django.contrib.admin import AdminSite
from django.contrib.auth.models import User
from .models import Church

class ChurchAdminSite(AdminSite):
    def each_context(self, request):
        context = super().each_context(request)
        if request.user.is_authenticated:
            try:
                # Get the church associated with the logged-in user
                church_member = request.user.churchmember_set.first()
                if church_member and church_member.church:
                    church_name = church_member.church.name
                    context['site_header'] = church_name + " Administration"
                    context['site_title'] = church_name
                    context['index_title'] = church_name + " Management"
            except:
                pass
        return context

church_admin_site = ChurchAdminSite(name='church_admin')
