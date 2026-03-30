import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'church_finance_project.settings')
django.setup()

from django.contrib.auth.models import User
from django.db.models import Count
from church_finances.models import ChurchMember

print(f"{'ID':<5} {'Username':<25} {'Email':<35} {'Church':<30} {'Role':<15} {'Super':<7} {'Active':<7} {'Joined'}")
print('-' * 135)
for u in User.objects.all().order_by('date_joined'):
    member = ChurchMember.objects.select_related('church').filter(user=u).first()
    try:
        church = member.church.name if (member and member.church_id) else '-- no church --'
    except Exception:
        church = '-- no church --'
    role = member.role if member else '--'
    print(f"{u.id:<5} {u.username:<25} {u.email:<35} {church:<30} {role:<15} {str(u.is_superuser):<7} {str(u.is_active):<7} {u.date_joined.strftime('%Y-%m-%d')}")

print()
print(f"Total users: {User.objects.count()}")

dup_emails = User.objects.values('email').annotate(c=Count('id')).filter(c__gt=1)
if dup_emails:
    print(f"Duplicate emails: {[d['email'] for d in dup_emails]}")
else:
    print("No duplicate emails found.")

dup_usernames = User.objects.values('username').annotate(c=Count('id')).filter(c__gt=1)
if dup_usernames:
    print(f"Duplicate usernames: {[d['username'] for d in dup_usernames]}")
else:
    print("No duplicate usernames found.")
