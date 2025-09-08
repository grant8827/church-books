from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, logout
from django.contrib.auth.models import User, Group
from django.contrib.messages import success, error, info
from django.db.models import Sum, Q
from django.http import HttpResponseNotAllowed
from django.utils import timezone
from .models import Transaction, Church, ChurchMember, Contribution
from .forms import (
    CustomUserCreationForm, TransactionForm, ChurchRegistrationForm,
    ChurchMemberForm, ContributionForm, DashboardUserRegistrationForm
)
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from datetime import datetime
from calendar import monthrange
from collections import defaultdict

# Static page views
def about_view(request):
    """
    Display the About page
    """
    return render(request, 'about.html')

def contact_view(request):
    """
    Display the Contact page and handle contact form submissions
    """
    if request.method == 'POST':
        # Handle contact form submission
        name = request.POST.get('name')
        email = request.POST.get('email')
        church_name = request.POST.get('church_name', '')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        # In a real application, you would send an email here
        # For now, we'll just show a success message
        success(request, f"Thank you, {name}! Your message has been sent. We'll get back to you soon.")
        return redirect('contact')
    
    return render(request, 'contact.html')

def pricing_view(request):
    """
    Display the Pricing page
    """
    return render(request, 'pricing.html')

def choose_plan_view(request):
    """
    Display the Choose Your Plan page and handle plan selection
    """
    if request.method == 'POST':
        # Handle plan selection form submission
        plan = request.POST.get('plan')
        church_name = request.POST.get('church_name')
        contact_name = request.POST.get('contact_name')
        contact_email = request.POST.get('contact_email')
        
        # Store the selected plan in session
        request.session['selected_package'] = plan
        request.session['church_name'] = church_name
        request.session['contact_name'] = contact_name
        request.session['contact_email'] = contact_email
        
        success(request, f"Thank you for choosing the {plan.title()} plan! Please complete your registration.")
        return redirect('register')
    
    return render(request, 'choose_plan.html')

def is_superadmin(user):
    return user.is_superuser

def get_user_church(user):
    """Helper function to get the user's church"""
    try:
        member = ChurchMember.objects.get(user=user, is_active=True)
        return member.church if member.church.is_approved else None
    except ChurchMember.DoesNotExist:
        return None


def register_view(request):
    """
    Handles new church registration with user creation.
    New church registrations require admin approval.
    """
    # Check if a subscription package was selected
    selected_package = request.session.get('selected_package')
    if not selected_package:
        info(request, "Please select a subscription package first.")
        return redirect('subscription')
        
    if request.method == "POST":
        user_form = CustomUserCreationForm(request.POST)
        church_form = ChurchRegistrationForm(request.POST)
        
        if user_form.is_valid() and church_form.is_valid():
            try:
                with transaction.atomic():
                    user = user_form.save()
                    church = church_form.save(commit=False)
                    church.is_approved = False  # New churches require approval
                    church.subscription_type = selected_package
                    church.subscription_status = 'pending'
                    church.save()
                    # Create an inactive church member until approved
                    ChurchMember.objects.create(
                        user=user,
                        church=church,
                        role='admin',  # Creator becomes church admin
                        is_active=False  # Member is inactive until church is approved
                    )
                    # Clear the subscription session data
                    request.session.pop('selected_package', None)
                    request.session.pop('package_price', None)
                    success(request, "Registration successful! Your church is pending payment and admin approval.")
                    login(request, user)
                    return redirect("dashboard")
                    
            except Exception as e:
                error(request, "An error occurred during registration. Please try again.")
                # Delete the user if church association failed
                if 'user' in locals():
                    user.delete()
        else:
            for field, errors_list in user_form.errors.items():
                for err in errors_list:
                    error(request, f"{field}: {err}")
            for field, errors_list in church_form.errors.items():
                for err in errors_list:
                    error(request, f"{field}: {err}")
    else:
        user_form = CustomUserCreationForm()
        church_form = ChurchRegistrationForm()
    
    context = {
        "user_form": user_form,
        "church_form": church_form
    }
    return render(request, "church_finances/register.html", context)

@user_passes_test(is_superadmin)
def church_approval_list(request):
    """
    List all churches pending approval
    """
    pending_churches = Church.objects.filter(is_approved=False)
    return render(request, 'church_finances/church_approval_list.html', {
        'pending_churches': pending_churches
    })

@user_passes_test(is_superadmin)
def approve_church(request, church_id):
    """
    Approve a church registration
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    
    church = get_object_or_404(Church, id=church_id)
    if church.is_approved:
        error(request, f"Church '{church.name}' is already approved.")
    else:
        church.is_approved = True
        church.save()
        success(request, f"Church '{church.name}' has been approved.")
    return redirect('church_approval_list')

@user_passes_test(is_superadmin)
def reject_church(request, church_id):
    """
    Reject a church registration
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    
    church = get_object_or_404(Church, id=church_id)
    name = church.name
    church.delete()
    success(request, f"Church '{name}' registration has been rejected.")
    return redirect('church_approval_list')


from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.exceptions import PermissionDenied
import logging

logger = logging.getLogger(__name__)

@ensure_csrf_cookie
def user_login_view(request):
    """
    Handles user login with enhanced CSRF protection and debugging.
    """
    if request.method == "POST":
        # Log CSRF token information for debugging
        logger.debug(f"CSRF Token in Cookie: {request.COOKIES.get('csrftoken')}")
        logger.debug(f"CSRF Token in POST: {request.POST.get('csrfmiddlewaretoken')}")
        
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            success(request, f"Welcome back, {user.username}!")
            return redirect("dashboard")
        else:
            error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    
    response = render(request, "church_finances/login.html", {
        "form": form,
    })
    return response


@login_required
def user_logout_view(request):
    """
    Handles user logout.
    """
    logout(request)
    info(request, "You have been logged out.")
    return redirect("home")

@login_required
def member_list_view(request):
    """
    Display list of church members
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    members = ChurchMember.objects.filter(church=church)
    return render(request, "church_finances/member_list.html", {
        "members": members,
        "church": church
    })

@login_required
def member_add_view(request):
    """
    Add a new church member
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Check if user has permission to add members
    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'treasurer']:
        raise PermissionDenied("You don't have permission to add members.")

    if request.method == "POST":
        form = ChurchMemberForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Create a basic user account with the member's name
                    first_name = form.cleaned_data['first_name']
                    last_name = form.cleaned_data['last_name']
                    # Create a unique username based on first and last name
                    base_username = f"{first_name.lower()}.{last_name.lower()}"
                    username = base_username
                    counter = 1
                    while User.objects.filter(username=username).exists():
                        username = f"{base_username}{counter}"
                        counter += 1
                    
                    # Create user with a random password (they can't login with this)
                    import uuid
                    random_password = str(uuid.uuid4())
                    user = User.objects.create_user(
                        username=username,
                        password=random_password,
                        first_name=first_name,
                        last_name=last_name
                    )
                    
                    # Create the ChurchMember
                    member = form.save(commit=False)
                    member.user = user
                    member.church = church
                    member.role = 'member'  # Default role for new members
                    member.save()
                    
                    success(request, "Member added successfully!")
                    return redirect("member_list")
            except Exception as e:
                error(request, f"Error creating member: {str(e)}")
                # If there was an error, delete the user if it was created
                if 'user' in locals():
                    user.delete()
    else:
        form = ChurchMemberForm()

    return render(request, "church_finances/member_form.html", {"form": form})

@login_required
def member_detail_view(request, pk):
    """
    Display details of a church member
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    member = get_object_or_404(ChurchMember, pk=pk, church=church)
    
    # Get member's contribution history
    contributions = Contribution.objects.filter(member=member).order_by('-date')
    
    context = {
        "member": member,
        "contributions": contributions,
        "church": church
    }
    return render(request, "church_finances/member_detail.html", context)

@login_required
def member_activate_view(request, pk):
    """
    Activate a church member
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Check if user has permission to activate members
    user_member = ChurchMember.objects.get(user=request.user, church=church)
    if user_member.role not in ['admin', 'treasurer']:
        raise PermissionDenied("You don't have permission to activate members.")

    member = get_object_or_404(ChurchMember, pk=pk, church=church)
    member.is_active = True
    member.save()
    success(request, f"Member {member.user.get_full_name()} has been activated.")
    return redirect('member_list')

@login_required
def member_deactivate_view(request, pk):
    """
    Deactivate a church member
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Check if user has permission to deactivate members
    user_member = ChurchMember.objects.get(user=request.user, church=church)
    if user_member.role not in ['admin', 'treasurer']:
        raise PermissionDenied("You don't have permission to deactivate members.")

    member = get_object_or_404(ChurchMember, pk=pk, church=church)
    member.is_active = False
    member.save()
    success(request, f"Member {member.user.get_full_name()} has been deactivated.")
    return redirect('member_list')

@login_required
def member_edit_view(request, pk):
    """
    Edit an existing church member
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Check if user has permission to edit members
    user_member = ChurchMember.objects.get(user=request.user, church=church)
    if user_member.role not in ['admin', 'treasurer']:
        raise PermissionDenied("You don't have permission to edit members.")

    member = get_object_or_404(ChurchMember, pk=pk, church=church)
    if request.method == "POST":
        form = ChurchMemberForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            success(request, "Member updated successfully!")
            return redirect("member_list")
    else:
        form = ChurchMemberForm(instance=member)

    return render(request, "church_finances/member_form.html", {"form": form})

@login_required
def contribution_list_view(request):
    """
    Display list of contributions
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    contributions = Contribution.objects.filter(church=church).order_by('-date', '-created_at')
    
    # Calculate totals
    total_tithes = contributions.filter(contribution_type='tithe').aggregate(Sum('amount'))['amount__sum'] or 0
    total_offerings = contributions.filter(contribution_type='offering').aggregate(Sum('amount'))['amount__sum'] or 0
    total_contributions = contributions.aggregate(Sum('amount'))['amount__sum'] or 0

    context = {
        "contributions": contributions,
        "total_tithes": total_tithes,
        "total_offerings": total_offerings,
        "total_contributions": total_contributions,
        "church": church
    }
    return render(request, "church_finances/contribution_list.html", context)

@login_required
def contribution_add_view(request):
    """
    Add a new contribution
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Check if user has permission to add contributions
    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'treasurer']:
        raise PermissionDenied("You don't have permission to add contributions.")

    if request.method == "POST":
        form = ContributionForm(request.POST, church=church)
        if form.is_valid():
            contribution = form.save(commit=False)
            contribution.church = church
            contribution.recorded_by = request.user
            contribution.save()
            success(request, "Contribution recorded successfully!")
            return redirect("contribution_list")
    else:
        form = ContributionForm(church=church)

    return render(request, "church_finances/contribution_form.html", {"form": form})

@login_required
def contribution_detail_view(request, pk):
    """
    Display details of a single contribution
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    contribution = get_object_or_404(Contribution, pk=pk, church=church)
    return render(request, "church_finances/contribution_detail.html", {
        "contribution": contribution,
        "church": church
    })

@login_required
def contribution_edit_view(request, pk):
    """
    Edit an existing contribution
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Check if user has permission to edit contributions
    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'treasurer']:
        raise PermissionDenied("You don't have permission to edit contributions.")

    contribution = get_object_or_404(Contribution, pk=pk, church=church)
    if request.method == "POST":
        form = ContributionForm(request.POST, instance=contribution, church=church)
        if form.is_valid():
            form.save()
            success(request, "Contribution updated successfully!")
            return redirect("contribution_list")
    else:
        form = ContributionForm(instance=contribution, church=church)

    return render(request, "church_finances/contribution_form.html", {"form": form})


@login_required
@login_required
def dashboard_user_register_view(request):
    """
    Register new church staff members from the dashboard.
    These users are automatically approved since they are being added by an admin/pastor.
    """
    church = get_user_church(request.user)
    if not church or not church.is_approved:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Check if user has permission to register staff
    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'pastor']:
        raise PermissionDenied("You don't have permission to register staff members.")

    if request.method == "POST":
        form = DashboardUserRegistrationForm(request.POST, church=church)
        if form.is_valid():
            user = form.save()
            success(request, f"Successfully registered {user.get_full_name()} as {form.cleaned_data['role']}.")
            return redirect('dashboard')
    else:
        form = DashboardUserRegistrationForm(church=church)

    return render(request, "church_finances/dashboard_user_register.html", {
        "form": form,
        "church": church
    })

def dashboard_view(request):
    """
    Displays a financial summary dashboard for the user's church.
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Get transactions for this church only
    total_income = (
        Transaction.objects.filter(church=church, type="income")
        .aggregate(Sum("amount"))["amount__sum"] or 0
    )
    total_expense = (
        Transaction.objects.filter(church=church, type="expense")
        .aggregate(Sum("amount"))["amount__sum"] or 0
    )
    net_balance = total_income - total_expense

    recent_transactions = Transaction.objects.filter(church=church)[:10]

    # Get church member info
    church_role = ChurchMember.objects.get(user=request.user, church=church).role
    
    # Get counts for dashboard cards
    total_members = ChurchMember.objects.filter(church=church, is_active=True).count()
    total_transactions = Transaction.objects.filter(church=church).count()
    total_contributions = Contribution.objects.filter(church=church).count()
    
    # Calculate this month's contributions
    now = timezone.now()
    first_day_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month_contributions = (
        Contribution.objects.filter(
            church=church,
            date__gte=first_day_of_month,
            date__lte=now
        ).aggregate(total=Sum('amount'))['total'] or 0
    )

    context = {
        "total_income": total_income,
        "total_expense": total_expense,
        "net_balance": net_balance,
        "recent_transactions": recent_transactions,
        "church": church,
        "church_role": church_role,
        "total_members": total_members,
        "total_transactions": total_transactions,
        "total_contributions": total_contributions,
        "this_month_contributions": this_month_contributions,
    }
    return render(request, "church_finances/dashboard.html", context)


@login_required
def transaction_list_view(request):
    """
    Displays a list of financial transactions for the user's church.
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    transactions = Transaction.objects.filter(church=church)
    context = {
        "transactions": transactions,
        "church": church
    }
    return render(request, "church_finances/transaction_list.html", context)


@login_required
def transaction_create_view(request):
    """
    Handles creation of new financial transactions for the user's church.
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Check if user has permission to create transactions
    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'treasurer']:
        raise PermissionDenied("You don't have permission to create transactions.")

    if request.method == "POST":
        form = TransactionForm(request.POST, church=church)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.recorded_by = request.user
            transaction.church = church
            transaction.save()
            success(request, "Transaction added successfully!")
            return redirect("transaction_list")
        else:
            for field, errors_list in form.errors.items():
                for err in errors_list:
                    error(request, f"{field}: {err}")
    else:
        form = TransactionForm(church=church)
    
    return render(
        request,
        "church_finances/transaction_form.html",
        {"form": form, "title": "Add New Transaction"},
    )


@login_required
def transaction_detail_view(request, pk):
    """
    Displays details of a single transaction.
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    transaction = get_object_or_404(Transaction, pk=pk, church=church)
    context = {
        "transaction": transaction,
        "church": church
    }
    return render(request, "church_finances/transaction_detail.html", context)


@login_required
def transaction_update_view(request, pk):
    """
    Handles updating an existing financial transaction.
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Check if user has permission to update transactions
    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'treasurer']:
        raise PermissionDenied("You don't have permission to update transactions.")

    transaction = get_object_or_404(Transaction, pk=pk, church=church)
    if request.method == "POST":
        form = TransactionForm(request.POST, instance=transaction, church=church)
        if form.is_valid():
            form.save()
            success(request, "Transaction updated successfully!")
            return redirect("transaction_detail", pk=pk)
        else:
            for field, errors_list in form.errors.items():
                for err in errors_list:
                    error(request, f"{field}: {err}")
    else:
        form = TransactionForm(instance=transaction, church=church)
    return render(
        request,
        "church_finances/transaction_form.html",
        {"form": form, "title": "Update Transaction"},
    )


@login_required
def transaction_delete_view(request, pk):
    """
    Handles deletion of a financial transaction.
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Check if user has permission to delete transactions
    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'treasurer']:
        raise PermissionDenied("You don't have permission to delete transactions.")

    transaction = get_object_or_404(Transaction, pk=pk, church=church)
    if request.method == "POST":
        transaction.delete()
        success(request, "Transaction deleted successfully!")
        return redirect("transaction_list")
    return render(
        request, "church_finances/confirm_delete.html", {"transaction": transaction}
    )

@login_required
def contribution_print_monthly(request):
    """
    Generate a printable monthly report of contributions
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Get the month and year from query parameters or use current
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    
    # Get start and end dates for the selected month
    _, last_day = monthrange(year, month)
    start_date = timezone.datetime(year, month, 1)
    end_date = timezone.datetime(year, month, last_day)
    
    # Get all contributions for the month
    contributions = Contribution.objects.filter(
        church=church,
        date__gte=start_date,
        date__lte=end_date
    ).order_by('date', 'member__user__last_name')

    # Calculate totals
    totals = {
        'tithe': contributions.filter(contribution_type='tithe').aggregate(Sum('amount'))['amount__sum'] or 0,
        'offering': contributions.filter(contribution_type='offering').aggregate(Sum('amount'))['amount__sum'] or 0,
        'total': contributions.aggregate(Sum('amount'))['amount__sum'] or 0
    }

    context = {
        'church': church,
        'contributions': contributions,
        'totals': totals,
        'month': start_date.strftime('%B'),
        'year': year,
        'current_year': timezone.now().year,
        'print_date': timezone.now()
    }
    
    return render(request, "church_finances/print/monthly_contributions.html", context)

@login_required
def contribution_print_yearly(request):
    """
    Generate a printable yearly report of contributions
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Get the year from query parameters or use current
    year = int(request.GET.get('year', timezone.now().year))
    
    # Get start and end dates for the year
    start_date = timezone.datetime(year, 1, 1)
    end_date = timezone.datetime(year, 12, 31)
    
    # Get all contributions for the year
    contributions = Contribution.objects.filter(
        church=church,
        date__year=year
    ).order_by('date')

    # Group by month
    monthly_totals = defaultdict(lambda: {'tithe': 0, 'offering': 0, 'total': 0})
    for contribution in contributions:
        month = contribution.date.strftime('%B')
        monthly_totals[month]['total'] += contribution.amount
        if contribution.contribution_type == 'tithe':
            monthly_totals[month]['tithe'] += contribution.amount
        elif contribution.contribution_type == 'offering':
            monthly_totals[month]['offering'] += contribution.amount

    context = {
        'church': church,
        'monthly_totals': dict(monthly_totals),
        'year': year,
        'current_year': timezone.now().year,
        'total_amount': contributions.aggregate(Sum('amount'))['amount__sum'] or 0,
        'print_date': timezone.now()
    }
    
    return render(request, "church_finances/print/yearly_contributions.html", context)

@login_required
def transaction_print_monthly(request):
    """
    Generate a printable monthly report of transactions
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Get the month and year from query parameters or use current
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    
    # Get start and end dates for the selected month
    _, last_day = monthrange(year, month)
    start_date = timezone.datetime(year, month, 1)
    end_date = timezone.datetime(year, month, last_day)
    
    # Get all transactions for the month
    transactions = Transaction.objects.filter(
        church=church,
        date__gte=start_date,
        date__lte=end_date
    ).order_by('date')

    # Calculate totals
    totals = {
        'income': transactions.filter(type='income').aggregate(Sum('amount'))['amount__sum'] or 0,
        'expense': transactions.filter(type='expense').aggregate(Sum('amount'))['amount__sum'] or 0,
        'net': 0
    }
    totals['net'] = totals['income'] - totals['expense']

    context = {
        'church': church,
        'transactions': transactions,
        'totals': totals,
        'month': start_date.strftime('%B'),
        'year': year,
        'current_year': timezone.now().year,
        'print_date': timezone.now()
    }
    
    return render(request, "church_finances/print/monthly_transactions.html", context)

@login_required
def transaction_print_yearly(request):
    """
    Generate a printable yearly report of transactions
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Get the year from query parameters or use current
    year = int(request.GET.get('year', timezone.now().year))
    
    # Get all transactions for the year
    transactions = Transaction.objects.filter(
        church=church,
        date__year=year
    ).order_by('date')

    # Group by month
    monthly_totals = defaultdict(lambda: {'income': 0, 'expense': 0, 'net': 0})
    for transaction in transactions:
        month = transaction.date.strftime('%B')
        if transaction.type == 'income':
            monthly_totals[month]['income'] += transaction.amount
        else:
            monthly_totals[month]['expense'] += transaction.amount
        monthly_totals[month]['net'] = monthly_totals[month]['income'] - monthly_totals[month]['expense']

    # Calculate year totals
    year_totals = {
        'income': transactions.filter(type='income').aggregate(Sum('amount'))['amount__sum'] or 0,
        'expense': transactions.filter(type='expense').aggregate(Sum('amount'))['amount__sum'] or 0,
        'net': 0
    }
    year_totals['net'] = year_totals['income'] - year_totals['expense']

    context = {
        'church': church,
        'monthly_totals': dict(monthly_totals),
        'year_totals': year_totals,
        'year': year,
        'current_year': timezone.now().year,
        'print_date': timezone.now()
    }
    
    return render(request, "church_finances/print/yearly_transactions.html", context)

def pending_approval_view(request):
    """
    Display the pending approval page
    """
    return render(request, "church_finances/pending_approval.html")
