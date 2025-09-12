from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, logout
from django.contrib.auth.models import User, Group
from django.contrib.messages import success, error, info
from django.db.models import Sum, Q
from django.http import HttpResponseNotAllowed, HttpResponse
from django.utils import timezone
from django.urls import reverse
from functools import wraps
from .models import Transaction, Church, ChurchMember, Contribution
from .forms import (
    CustomUserCreationForm, TransactionForm, ChurchRegistrationForm,
    ChurchMemberForm, ContributionForm, DashboardUserRegistrationForm
)
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from datetime import datetime, date
from calendar import monthrange
from collections import defaultdict
import io
from django.template.loader import get_template

# Conditional import for PDF generation
try:
    from xhtml2pdf import pisa
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

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

def admin_required(function):
    """Custom decorator that redirects to the correct login page for admin access"""
    @wraps(function)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('/finances/login/')
        if not request.user.is_superuser:
            raise PermissionDenied("You must be a superuser to access this page.")
        return function(request, *args, **kwargs)
    return wrapper

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

@admin_required
def church_approval_list(request):
    """
    List all churches pending approval
    """
    pending_churches = Church.objects.filter(is_approved=False)
    return render(request, 'church_finances/church_approval_list.html', {
        'pending_churches': pending_churches
    })

@admin_required
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
        church.subscription_status = 'active'
        church.save()
        
        # Find and activate any inactive users associated with this church
        from .models import ChurchMember
        church_members = ChurchMember.objects.filter(church=church)
        
        activated_users = []
        for member in church_members:
            if not member.user.is_active:
                member.user.is_active = True
                member.user.save()
                activated_users.append(member.user.username)
            
            # Also activate the church member
            if not member.is_active:
                member.is_active = True
                member.save()
        
        success_msg = f"Church '{church.name}' has been approved."
        if activated_users:
            success_msg += f" Activated user accounts: {', '.join(activated_users)}"
        
        success(request, success_msg)
    return redirect('church_approval_list')

@admin_required
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


# CSRF-related imports removed as CSRF protection is disabled
from django.core.exceptions import PermissionDenied
import logging

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

def user_login_view(request):
    """
    Handles user login.
    """
    if request.method == "POST":
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        
        # Check if user exists but is inactive
        try:
            user = User.objects.get(username=username)
            if not user.is_active:
                error(request, f"Your account '{username}' is inactive. Please contact an administrator or check if your church account is pending approval.")
                form = AuthenticationForm()
                return render(request, "church_finances/login.html", {"form": form})
        except User.DoesNotExist:
            pass  # Will be handled by AuthenticationForm
        
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            
            # Additional check for church member status
            try:
                member = ChurchMember.objects.get(user=user)
                if not member.is_active:
                    error(request, "Your church membership is pending approval. Please contact an administrator.")
                    return render(request, "church_finances/login.html", {"form": form})
                    
                if not member.church.is_approved:
                    error(request, "Your church account is pending approval. Please contact an administrator.")
                    return render(request, "church_finances/login.html", {"form": form})
                    
            except ChurchMember.DoesNotExist:
                # Allow admin users without church membership
                if not user.is_superuser:
                    error(request, "No church membership found. Please contact an administrator.")
                    return render(request, "church_finances/login.html", {"form": form})
            
            login(request, user)
            success(request, f"Welcome back, {user.username}!")
            return redirect("dashboard")
        else:
            # More detailed error handling
            if form.errors:
                for field, field_errors in form.errors.items():
                    for err_msg in field_errors:
                        error(request, f"{field}: {err_msg}")
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
    if member.role not in ['admin', 'treasurer', 'pastor']:
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
    if user_member.role not in ['admin', 'treasurer', 'pastor']:
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
    if user_member.role not in ['admin', 'treasurer', 'pastor']:
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
    if user_member.role not in ['admin', 'treasurer', 'pastor']:
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
    if member.role not in ['admin', 'treasurer', 'pastor']:
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
    if member.role not in ['admin', 'treasurer', 'pastor']:
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
    # Handle admin users who don't have church relationships
    if request.user.is_superuser:
        # For admin users, show all churches data or a special admin dashboard
        total_income = (
            Transaction.objects.filter(type="income")
            .aggregate(Sum("amount"))["amount__sum"] or 0
        )
        total_expense = (
            Transaction.objects.filter(type="expense")
            .aggregate(Sum("amount"))["amount__sum"] or 0
        )
        net_balance = total_income - total_expense
        recent_transactions = Transaction.objects.all()[:10]
        
        context = {
            "total_income": total_income,
            "total_expense": total_expense,
            "net_balance": net_balance,
            "recent_transactions": recent_transactions,
            "church_role": "Administrator",
            "is_admin": True,
            "all_churches": Church.objects.all(),
        }
        return render(request, "church_finances/dashboard.html", context)
    
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
    try:
        church_member = ChurchMember.objects.get(user=request.user, church=church)
        church_role = church_member.role
    except ChurchMember.DoesNotExist:
        # If no ChurchMember relationship exists, user shouldn't have access
        info(request, "Your church membership is not properly configured. Please contact support.")
        return render(request, "church_finances/pending_approval.html")
    
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
    if member.role not in ['admin', 'treasurer', 'pastor']:
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
    if member.role not in ['admin', 'treasurer', 'pastor']:
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
    if member.role not in ['admin', 'treasurer', 'pastor']:
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


# ==================== ENHANCED TITHES & OFFERINGS MANAGEMENT ====================

@login_required
def member_contributions_view(request):
    """
    Member's personal contribution history and summary
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    try:
        member = ChurchMember.objects.get(user=request.user, church=church)
    except ChurchMember.DoesNotExist:
        error(request, "Church membership not found.")
        return redirect('dashboard')

    # Get current year or requested year
    year = request.GET.get('year', timezone.now().year)
    try:
        year = int(year)
    except (ValueError, TypeError):
        year = timezone.now().year

    # Get member's contributions for the year
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)
    
    contributions = Contribution.objects.filter(
        member=member,
        date__range=[start_date, end_date]
    ).order_by('-date')

    # Calculate totals by type
    totals = {
        'tithe': contributions.filter(contribution_type='tithe').aggregate(Sum('amount'))['amount__sum'] or 0,
        'offering': contributions.filter(contribution_type='offering').aggregate(Sum('amount'))['amount__sum'] or 0,
        'special_offering': contributions.filter(contribution_type='special_offering').aggregate(Sum('amount'))['amount__sum'] or 0,
        'building_fund': contributions.filter(contribution_type='building_fund').aggregate(Sum('amount'))['amount__sum'] or 0,
        'missions': contributions.filter(contribution_type='missions').aggregate(Sum('amount'))['amount__sum'] or 0,
        'other': contributions.filter(contribution_type='other').aggregate(Sum('amount'))['amount__sum'] or 0,
    }
    totals['total'] = sum(totals.values())

    # Monthly breakdown
    monthly_totals = {}
    for month in range(1, 13):
        month_contributions = contributions.filter(date__month=month)
        monthly_totals[month] = {
            'total': month_contributions.aggregate(Sum('amount'))['amount__sum'] or 0,
            'tithe': month_contributions.filter(contribution_type='tithe').aggregate(Sum('amount'))['amount__sum'] or 0,
            'offering': month_contributions.filter(contribution_type='offering').aggregate(Sum('amount'))['amount__sum'] or 0,
        }

    context = {
        'member': member,
        'contributions': contributions,
        'totals': totals,
        'monthly_totals': monthly_totals,
        'year': year,
        'current_year': timezone.now().year,
        'available_years': range(2020, timezone.now().year + 1),
        'church': church,
    }
    
    return render(request, "church_finances/member_contributions.html", context)

@login_required
def contribution_statement_pdf(request, year=None):
    """
    Generate annual contribution statement PDF for a member
    """
    # Check if PDF generation is available
    if not PDF_AVAILABLE:
        error(request, "PDF generation is currently unavailable. Please contact your administrator.")
        return redirect('member_contributions')
    
    church = get_user_church(request.user)
    if not church:
        return HttpResponse('Unauthorized', status=401)

    try:
        member = ChurchMember.objects.get(user=request.user, church=church)
    except ChurchMember.DoesNotExist:
        return HttpResponse('Member not found', status=404)

    if year is None:
        year = timezone.now().year
    else:
        year = int(year)

    # Get contributions for the year
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)
    
    contributions = Contribution.objects.filter(
        member=member,
        date__range=[start_date, end_date]
    ).order_by('date')

    # Calculate contribution summary
    contribution_summary = []
    for contrib_type, display_name in Contribution.CONTRIBUTION_TYPES:
        type_contributions = contributions.filter(contribution_type=contrib_type)
        count = type_contributions.count()
        total = type_contributions.aggregate(Sum('amount'))['amount__sum'] or 0
        if count > 0:  # Only include types with contributions
            contribution_summary.append({
                'type': contrib_type,
                'type_display': display_name,
                'count': count,
                'total': total
            })

    # Monthly breakdown
    monthly_breakdown = []
    for month in range(1, 13):
        month_start = date(year, month, 1)
        month_end = date(year, month, monthrange(year, month)[1])
        month_contributions = contributions.filter(date__range=[month_start, month_end])
        
        month_data = {
            'month': month_start.strftime('%B'),
            'tithe': month_contributions.filter(contribution_type='tithe').aggregate(Sum('amount'))['amount__sum'] or 0,
            'offering': month_contributions.filter(contribution_type='offering').aggregate(Sum('amount'))['amount__sum'] or 0,
            'special_offering': month_contributions.filter(contribution_type='special_offering').aggregate(Sum('amount'))['amount__sum'] or 0,
            'building_fund': month_contributions.filter(contribution_type='building_fund').aggregate(Sum('amount'))['amount__sum'] or 0,
            'missions': month_contributions.filter(contribution_type='missions').aggregate(Sum('amount'))['amount__sum'] or 0,
            'other': month_contributions.filter(contribution_type='other').aggregate(Sum('amount'))['amount__sum'] or 0,
        }
        month_data['total'] = sum(month_data.values()) - month_data['month']  # Subtract the month string
        monthly_breakdown.append(month_data)

    total_amount = sum([item['total'] for item in contribution_summary])
    total_contributions = contributions.count()

    # Generate PDF
    template = get_template('church_finances/contribution_statement.html')
    context = {
        'member': member,
        'church': church,
        'contribution_summary': contribution_summary,
        'monthly_breakdown': monthly_breakdown,
        'total_amount': total_amount,
        'total_contributions': total_contributions,
        'year': year,
        'statement_date': timezone.now(),
    }
    
    html = template.render(context)
    result = io.BytesIO()
    
    try:
        pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), result)
        
        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="contribution_statement_{year}_{member.user.username}.pdf"'
            return response
        else:
            error(request, "Error generating PDF. Please try again or contact support.")
            return redirect('member_contributions')
    except Exception as e:
        error(request, f"PDF generation failed: {str(e)}")
        return redirect('member_contributions')

@login_required
def quick_tithe_entry(request):
    """
    Quick tithe entry form for members
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    try:
        member = ChurchMember.objects.get(user=request.user, church=church)
    except ChurchMember.DoesNotExist:
        error(request, "Church membership not found.")
        return redirect('dashboard')

    if request.method == 'POST':
        amount = request.POST.get('amount')
        contribution_type = request.POST.get('contribution_type', 'tithe')
        payment_method = request.POST.get('payment_method', 'cash')
        reference_number = request.POST.get('reference_number', '')
        notes = request.POST.get('notes', '')
        
        try:
            amount = float(amount)
            if amount <= 0:
                error(request, "Amount must be greater than zero.")
                return redirect('quick_tithe_entry')
                
            contribution = Contribution.objects.create(
                member=member,
                church=church,
                date=timezone.now().date(),
                contribution_type=contribution_type,
                amount=amount,
                payment_method=payment_method,
                reference_number=reference_number,
                notes=notes,
                recorded_by=request.user
            )
            
            success(request, f"${amount} {contribution_type} recorded successfully!")
            return redirect('member_contributions')
            
        except (ValueError, TypeError):
            error(request, "Please enter a valid amount.")
            return redirect('quick_tithe_entry')

    # Recent contributions for reference
    recent_contributions = Contribution.objects.filter(
        member=member
    ).order_by('-date')[:5]

    context = {
        'member': member,
        'church': church,
        'recent_contributions': recent_contributions,
        'contribution_types': Contribution.CONTRIBUTION_TYPES,
        'payment_methods': Contribution.PAYMENT_METHODS,
    }
    
    return render(request, "church_finances/quick_tithe_entry.html", context)

@login_required
def tithes_offerings_dashboard(request):
    """
    Enhanced dashboard for tithes and offerings management
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    try:
        member = ChurchMember.objects.get(user=request.user, church=church)
    except ChurchMember.DoesNotExist:
        error(request, "Church membership not found.")
        return redirect('dashboard')

    # Current year stats
    current_year = timezone.now().year
    start_date = date(current_year, 1, 1)
    end_date = date(current_year, 12, 31)

    if member.role in ['admin', 'treasurer', 'pastor']:
        # Admin view - see all church contributions
        contributions = Contribution.objects.filter(
            church=church,
            date__range=[start_date, end_date]
        )
        
        # Top contributors (if admin/treasurer)
        if member.role in ['admin', 'treasurer']:
            top_contributors = Contribution.objects.filter(
                church=church,
                date__range=[start_date, end_date]
            ).values('member__user__first_name', 'member__user__last_name').annotate(
                total=Sum('amount')
            ).order_by('-total')[:10]
        else:
            top_contributors = []
            
        context_type = 'admin'
    else:
        # Member view - see only their contributions
        contributions = Contribution.objects.filter(
            member=member,
            date__range=[start_date, end_date]
        )
        top_contributors = []
        context_type = 'member'

    # Calculate totals
    totals = {
        'tithe': contributions.filter(contribution_type='tithe').aggregate(Sum('amount'))['amount__sum'] or 0,
        'offering': contributions.filter(contribution_type='offering').aggregate(Sum('amount'))['amount__sum'] or 0,
        'special_offering': contributions.filter(contribution_type='special_offering').aggregate(Sum('amount'))['amount__sum'] or 0,
        'building_fund': contributions.filter(contribution_type='building_fund').aggregate(Sum('amount'))['amount__sum'] or 0,
        'missions': contributions.filter(contribution_type='missions').aggregate(Sum('amount'))['amount__sum'] or 0,
        'other': contributions.filter(contribution_type='other').aggregate(Sum('amount'))['amount__sum'] or 0,
    }
    totals['total'] = sum(totals.values())

    # Recent contributions
    recent_contributions = contributions.order_by('-date')[:10]

    # Monthly trend (last 12 months)
    monthly_trend = []
    for i in range(12):
        month_date = timezone.now().date().replace(day=1) - timezone.timedelta(days=30*i)
        month_start = month_date.replace(day=1)
        if month_date.month == 12:
            month_end = month_date.replace(year=month_date.year+1, month=1, day=1) - timezone.timedelta(days=1)
        else:
            month_end = month_date.replace(month=month_date.month+1, day=1) - timezone.timedelta(days=1)
            
        month_contributions = contributions.filter(date__range=[month_start, month_end])
        monthly_trend.append({
            'month': month_date.strftime('%b %Y'),
            'total': month_contributions.aggregate(Sum('amount'))['amount__sum'] or 0,
            'tithe': month_contributions.filter(contribution_type='tithe').aggregate(Sum('amount'))['amount__sum'] or 0,
            'offering': month_contributions.filter(contribution_type='offering').aggregate(Sum('amount'))['amount__sum'] or 0,
        })
    
    monthly_trend.reverse()  # Show oldest to newest

    # Calculate additional values for template
    total_members_count = ChurchMember.objects.filter(church=church, is_active=True).count() if context_type == 'admin' else 0
    
    # Calculate percentages and averages
    if totals['total'] > 0:
        tithe_percentage = round((totals['tithe'] / totals['total']) * 100, 1)
        offering_percentage = round((totals['offering'] / totals['total']) * 100, 1)
    else:
        tithe_percentage = 0
        offering_percentage = 0
        
    if total_members_count > 0:
        average_per_member = round(totals['total'] / total_members_count, 2)
    else:
        average_per_member = 0
        
    # Add percentage to monthly trend for chart display
    max_month_total = max([month['total'] for month in monthly_trend] + [0])
    for month in monthly_trend:
        if max_month_total > 0:
            month['percentage'] = round((month['total'] / max_month_total) * 100, 1)
        else:
            month['percentage'] = 0

    context = {
        'member': member,
        'church': church,
        'totals': totals,
        'recent_contributions': recent_contributions,
        'monthly_trend': monthly_trend,
        'top_contributors': top_contributors,
        'current_year': current_year,
        'context_type': context_type,
        'total_members': total_members_count,
        'tithe_percentage': tithe_percentage,
        'offering_percentage': offering_percentage,
        'average_per_member': average_per_member,
    }
    
    return render(request, "church_finances/tithes_offerings_dashboard.html", context)

@login_required
def bulk_contribution_entry(request):
    """
    Bulk entry form for contributions (admin/treasurer only)
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    try:
        member = ChurchMember.objects.get(user=request.user, church=church)
    except ChurchMember.DoesNotExist:
        error(request, "Church membership not found.")
        return redirect('dashboard')

    # Check permissions
    if member.role not in ['admin', 'treasurer', 'pastor']:
        error(request, "You don't have permission to access bulk entry.")
        return redirect('dashboard')

    if request.method == 'POST':
        contributions_data = request.POST.getlist('contributions')
        success_count = 0
        error_count = 0
        
        for contribution_json in contributions_data:
            try:
                import json
                data = json.loads(contribution_json)
                
                # Validate and create contribution
                contrib_member = ChurchMember.objects.get(id=data['member_id'], church=church)
                
                Contribution.objects.create(
                    member=contrib_member,
                    church=church,
                    date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
                    contribution_type=data['contribution_type'],
                    amount=float(data['amount']),
                    payment_method=data['payment_method'],
                    reference_number=data.get('reference_number', ''),
                    notes=data.get('notes', ''),
                    recorded_by=request.user
                )
                success_count += 1
                
            except Exception as e:
                error_count += 1
                
        if success_count > 0:
            success(request, f"Successfully recorded {success_count} contributions.")
        if error_count > 0:
            error(request, f"Failed to record {error_count} contributions.")
            
        return redirect('contribution_list')

    # Get all church members for the dropdown
    church_members = ChurchMember.objects.filter(church=church, is_active=True).order_by('user__first_name', 'user__last_name')

    context = {
        'member': member,
        'church': church,
        'church_members': church_members,
        'contribution_types': Contribution.CONTRIBUTION_TYPES,
        'payment_methods': Contribution.PAYMENT_METHODS,
    }
    
    return render(request, "church_finances/bulk_contribution_entry.html", context)



