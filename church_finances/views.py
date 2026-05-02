from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, logout
from django.contrib.auth.models import User, Group
from django.contrib.messages import success, error, info, warning
from django.db.models import Sum, Q
from decimal import Decimal
from django.http import HttpResponseNotAllowed, HttpResponse, JsonResponse
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from functools import wraps
import random
import string
from datetime import timedelta
from .models import Transaction, Church, ChurchMember, Member, Contribution, Child, ChildAttendance, BabyChristening, CertificateTemplate, EmailOTP, SubscriptionPlan
from .forms import (
    CustomUserCreationForm, TransactionForm, ChurchRegistrationForm,
    ChurchMemberForm, MemberForm, ContributionForm, DashboardUserRegistrationForm,
    PersonalProfileForm, ChurchDetailForm
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
from django.views.decorators.http import require_POST, require_http_methods


# Conditional import for PDF generation
try:
    # Temporarily disabled due to import issues
    # from xhtml2pdf import pisa
    PDF_AVAILABLE = False
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
    Redirect to the new subscription/pricing page.
    """
    return redirect('subscription')

def choose_plan_view(request):
    """
    Redirect to the new multi-tier subscription/pricing page.
    All nav and home-page links use the 'choose_plan' URL name so we
    redirect here rather than updating every template individually.
    """
    return redirect('subscription')

def privacy_policy_view(request):
    """
    Display the Privacy Policy page
    """
    return render(request, 'privacy_policy.html')

def terms_of_service_view(request):
    """
    Display the Terms of Service page
    """
    return render(request, 'terms_of_service.html')

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
    # Check if user is authenticated and not anonymous
    if not user or not user.is_authenticated or user.is_anonymous:
        return None
        
    try:
        member = ChurchMember.objects.filter(user=user, is_active=True).first()
        if member is None:
            return None
        return member.church if member.church.is_approved else None
    except ChurchMember.DoesNotExist:
        return None


# ---------------------------------------------------------------------------
# Contribution → Transaction sync helpers
# ---------------------------------------------------------------------------

# Maps each Contribution.contribution_type to a Transaction.category
CONTRIBUTION_CATEGORY_MAP = {
    'tithe':            'tithes',
    'offering':         'offerings',
    'special_offering': 'offerings',
    'building_fund':    'donations',
    'missions':         'other_income',
    'other':            'other_income',
}

# Reverse: category → all contribution_types that feed it
_CATEGORY_TO_CONTRIB_TYPES = {}
for _ct, _cat in CONTRIBUTION_CATEGORY_MAP.items():
    _CATEGORY_TO_CONTRIB_TYPES.setdefault(_cat, []).append(_ct)


def _sync_contribution_transaction(church, date, contribution_type, recorded_by=None):
    """
    Recalculate and upsert/delete the Transaction that represents the total
    of all contributions for a given (church, date, contribution_type).

    - Multiple contribution_types can share one category (e.g. offering +
      special_offering → 'offerings'), so we always sum ALL types in that
      category before saving.
    - If the total drops to zero (e.g. after a delete) the Transaction row
      is removed so the transactions list stays clean.
    """
    category = CONTRIBUTION_CATEGORY_MAP.get(contribution_type)
    if not category:
        return

    contrib_types = _CATEGORY_TO_CONTRIB_TYPES[category]
    total = (
        Contribution.objects
        .filter(church=church, date=date, contribution_type__in=contrib_types)
        .aggregate(total=Sum('amount'))['total']
    ) or Decimal('0.00')

    if total > 0:
        txn, created = Transaction.objects.get_or_create(
            church=church,
            date=date,
            category=category,
            type='income',
            defaults={
                'amount': total,
                'description': f'Contributions – {category.replace("_", " ").title()}',
                'recorded_by': recorded_by,
                'from_contribution': True,
            },
        )
        if not created:
            txn.amount = total
            txn.from_contribution = True
            txn.save(update_fields=['amount', 'from_contribution', 'updated_at'])
    else:
        Transaction.objects.filter(
            church=church, date=date, category=category, type='income'
        ).delete()


def _is_rate_limited(cache_key, max_attempts, window_seconds):
    """
    Simple cache-based rate limiter.
    Returns True if the caller has exceeded max_attempts within the rolling window.
    """
    from django.core.cache import cache
    count = cache.get(cache_key, 0)
    if count >= max_attempts:
        return True
    cache.set(cache_key, count + 1, timeout=window_seconds)
    return False


def _get_fail_count(cache_key):
    """Return the current failure count for a cache key."""
    from django.core.cache import cache
    return cache.get(cache_key, 0)


def _increment_fail_count(cache_key, window_seconds):
    """Increment failure count and return the new value."""
    from django.core.cache import cache
    count = cache.get(cache_key, 0) + 1
    cache.set(cache_key, count, timeout=window_seconds)
    return count


def _clear_rate_limit(cache_key):
    """Remove a rate-limit counter from cache (e.g. after a successful login)."""
    from django.core.cache import cache
    cache.delete(cache_key)


def _client_ip(request):
    """Return the real client IP, honouring Railway's forwarded header."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def _send_login_notification(user, request):
    """Email the user a notification that their account was just logged into."""
    if not user.email:
        return
    try:
        from django.core.mail import send_mail
        from django.conf import settings as django_settings
        ip = _client_ip(request)
        ua = request.META.get('HTTP_USER_AGENT', 'Unknown device')[:120]
        now = timezone.now().strftime('%d %b %Y at %H:%M UTC')
        reset_url = request.build_absolute_uri('/finances/password-reset/')
        first_name = user.first_name or user.username
        send_mail(
            subject='Church Books — New Login to Your Account',
            message=(
                f'Hi {first_name},\n\n'
                f'A successful login was made to your Church Books account.\n\n'
                f'Time:       {now}\n'
                f'IP Address: {ip}\n'
                f'Device:     {ua}\n\n'
                f'If this was you, no action is needed.\n\n'
                f'If you did NOT make this login, your account may be compromised. '
                f'Change your password immediately:\n{reset_url}\n\n'
                f'— Church Books Security'
            ),
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
        logging.getLogger(__name__).info(f'Login notification sent to {user.email}')
    except Exception:
        pass  # Never block a login because of a notification failure


def _send_lockout_notification(user, request):
    """Email the user a warning that their account has been temporarily locked."""
    if not user.email:
        return
    try:
        from django.core.mail import send_mail
        from django.conf import settings as django_settings
        ip = _client_ip(request)
        now = timezone.now().strftime('%d %b %Y at %H:%M UTC')
        reset_url = request.build_absolute_uri('/finances/password-reset/')
        first_name = user.first_name or user.username
        send_mail(
            subject='Church Books — Account Temporarily Locked',
            message=(
                f'Hi {first_name},\n\n'
                f'Your Church Books account has been temporarily locked after '
                f'5 failed login attempts.\n\n'
                f'Time:       {now}\n'
                f'IP Address: {ip}\n\n'
                f'Your account will automatically unlock in 15 minutes.\n\n'
                f'If this was you, please wait and try again later.\n\n'
                f'If you did NOT make these attempts, your password may be '
                f'compromised. Reset it immediately:\n{reset_url}\n\n'
                f'— Church Books Security'
            ),
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
        logging.getLogger(__name__).warning(f'Lockout notification sent to {user.email}')
    except Exception:
        pass


def send_otp_view(request):
    """
    AJAX endpoint: validates personal-info / credentials fields, generates a
    6-digit OTP, e-mails it to the supplied address and stores the result in
    the session so the subsequent verify step can confirm it.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Invalid request method.'})

    # Rate-limit: max 5 OTP requests per IP per 10 minutes
    ip = _client_ip(request)
    if _is_rate_limited(f'otp_send_ip_{ip}', max_attempts=5, window_seconds=600):
        return JsonResponse({'ok': False, 'error': 'Too many requests. Please wait a few minutes before trying again.'})

    email = request.POST.get('email', '').strip().lower()
    if not email:
        return JsonResponse({'ok': False, 'error': 'Email address is required.'})

    # Rate-limit: max 3 OTP requests per email per 10 minutes
    if _is_rate_limited(f'otp_send_email_{email}', max_attempts=3, window_seconds=600):
        return JsonResponse({'ok': False, 'error': 'Too many verification requests for this email. Please wait 10 minutes before requesting a new code.'})

    # Reject already-registered email addresses immediately
    if User.objects.filter(email__iexact=email).exists():
        return JsonResponse({'ok': False, 'error': 'This email address is already registered. Please use a different email or sign in.'})

    # Generate a fresh 6-digit code
    code = ''.join(random.choices(string.digits, k=6))

    # Reuse an existing valid (non-expired, non-verified) OTP so that going
    # Back → Next doesn't silently regenerate the code while the user already
    # has the first one open in their inbox.
    existing = EmailOTP.objects.filter(
        email=email, is_verified=False
    ).order_by('-created_at').first()

    if existing and not existing.is_expired:
        # Reuse the existing code — don't regenerate.
        code = existing.code  # use the code already in the DB
    else:
        # Delete any stale OTPs and create a fresh one.
        EmailOTP.objects.filter(email=email).delete()
        existing = EmailOTP.objects.create(
            email=email,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=10),
        )

    # Send the verification e-mail (mirrors the password-reset email setup)
    try:
        import logging
        from django.core.mail import send_mail
        from django.conf import settings as django_settings
        logger = logging.getLogger(__name__)

        send_mail(
            subject='Church Books — Your Email Verification Code',
            message=(
                f'Your Church Books verification code is: {code}\n\n'
                f'This code will expire in 10 minutes.\n\n'
                f'If you did not request this code, please ignore this email.'
            ),
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        logger.info(f'OTP email sent to {email}')
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(f'OTP email failed for {email}: {exc}', exc_info=True)
        return JsonResponse({'ok': False, 'error': 'Failed to send verification email. Please try again or contact support.'})

    # Remember the verified email in session
    request.session['otp_email'] = email
    request.session['otp_verified'] = False

    return JsonResponse({'ok': True})


def verify_otp_view(request):
    """
    AJAX endpoint: checks the code entered by the user against the stored OTP.
    Sets session['otp_verified'] = True on success.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Invalid request method.'})

    import re
    import logging
    logger = logging.getLogger(__name__)

    # Normalise: strip everything except digits, then zero-pad to 6 chars.
    # This handles iOS autocomplete stripping leading zeros and keyboards
    # that insert spaces between digit groups (e.g. "123 456" → "123456").
    raw_code = request.POST.get('code', '')
    code = re.sub(r'\D', '', raw_code).zfill(6)

    # Use session email; fall back to the email passed from the JS form if
    # the session was lost (e.g. load-balancer routing to a different dyno).
    email = request.session.get('otp_email', '').strip().lower()
    if not email:
        email = request.POST.get('email', '').strip().lower()

    if not email:
        return JsonResponse({'ok': False, 'error': 'Session expired. Please go back and start again.'})

    # Ensure session is populated (handles the fallback case)
    if not request.session.get('otp_email'):
        request.session['otp_email'] = email
        request.session['otp_verified'] = False

    logger.info(f'OTP verify attempt for email={email}, code_len={len(code)}')

    try:
        otp = EmailOTP.objects.filter(email=email, is_verified=False).latest('created_at')
    except EmailOTP.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'No verification code found. Please request a new one.'})

    if otp.is_expired:
        return JsonResponse({'ok': False, 'error': 'Code has expired. Please click "Resend Code" to get a new one.'})

    if otp.attempts >= 5:
        return JsonResponse({'ok': False, 'error': 'Too many incorrect attempts. Please request a new code.'})

    if otp.code != code:
        otp.attempts += 1
        otp.save(update_fields=['attempts'])
        remaining = max(0, 5 - otp.attempts)
        logger.warning(
            f'OTP mismatch for {email}: stored_len={len(otp.code)}, '
            f'submitted_len={len(code)}, stored_last2={otp.code[-2:]}, '
            f'submitted_last2={code[-2:]}'
        )
        return JsonResponse({'ok': False, 'error': f'Incorrect code. {remaining} attempt(s) remaining.'})

    otp.is_verified = True
    otp.save(update_fields=['is_verified'])

    request.session['otp_verified'] = True
    return JsonResponse({'ok': True})


def register_view(request):
    """
    Handles new church registration with user creation.
    New church registrations require admin approval.
    """
    # Set default package for free trial registration
    selected_package = request.session.get('selected_package', 'standard')  # Default to standard package for free trial
    
    # Check if user is authenticated and already has registered a church
    if request.user.is_authenticated:
        existing_church = Church.objects.filter(registered_by=request.user).first()
        if existing_church:
            error(request, f"You have already registered a church: {existing_church.name}. Each account can only register one church.")
            return redirect('dashboard')
        
    if request.method == "POST":
        # Block submission if OTP has not been verified in this session
        if not request.session.get('otp_verified'):
            user_form = CustomUserCreationForm(request.POST)
            church_form = ChurchRegistrationForm(request.POST, prefix='church', user=request.user if request.user.is_authenticated else None)
            error(request, 'Please verify your email address before completing registration.')
            context = {"user_form": user_form, "church_form": church_form}
            return render(request, "church_finances/register.html", context)

        # Trust the OTP-verified session email — override whatever was submitted in the
        # form field (guards against browser autofill or navigating back to Step 1 and
        # changing the email after the OTP has already been verified).
        # The church email is a separate prefixed field and is always allowed to differ.
        verified_email = request.session.get('otp_email', '').strip().lower()
        if not verified_email:
            error(request, 'Your session has expired. Please start registration again.')
            return redirect('register')
        post_data = request.POST.copy()
        post_data['email'] = verified_email
        user_form = CustomUserCreationForm(post_data)
        church_form = ChurchRegistrationForm(post_data, prefix='church', user=request.user if request.user.is_authenticated else None)

        if user_form.is_valid() and church_form.is_valid():
            try:
                with transaction.atomic():
                    user = user_form.save()
                    church = church_form.save(commit=False)
                    church.is_approved = True  # Automatically approve for 30-day trial
                    church.subscription_type = selected_package
                    church.subscription_status = 'pending'  # Still pending payment, but approved for trial
                    church.registered_by = user  # Set the registering user
                    # Attach subscription plan chosen on pricing page (if any)
                    plan_id_session = request.session.get('selected_plan_id')
                    if plan_id_session:
                        try:
                            church.subscription_plan = SubscriptionPlan.objects.get(id=plan_id_session)
                        except SubscriptionPlan.DoesNotExist:
                            pass
                    declared_count = request.session.get('declared_member_count')
                    if declared_count:
                        church.declared_member_count = declared_count
                    sub_amount = request.session.get('package_price')
                    if sub_amount:
                        church.subscription_amount = float(sub_amount)
                    # Start the 30-day trial clock
                    church.trial_end_date = timezone.now() + timedelta(days=30)
                    church.save()
                    # Validate and save logo if uploaded
                    logo_file = request.FILES.get('church_logo')
                    if logo_file:
                        # Enforce allowed content types and size (max 5 MB)
                        allowed_types = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
                        if logo_file.content_type not in allowed_types:
                            error(request, 'Logo must be a JPEG, PNG, GIF, or WebP image.')
                            return render(request, 'church_finances/register.html', {"user_form": user_form, "church_form": church_form})
                        if logo_file.size > 5 * 1024 * 1024:  # 5 MB
                            error(request, 'Logo file is too large. Maximum size is 5 MB.')
                            return render(request, 'church_finances/register.html', {"user_form": user_form, "church_form": church_form})
                        church.save_logo(logo_file)
                    # Create an active church member for immediate trial access
                    ChurchMember.objects.create(
                        user=user,
                        church=church,
                        role='admin',  # Creator becomes church admin
                        is_active=True  # Member is active for trial period
                    )
                    # Clear the subscription session data
                    request.session.pop('selected_package', None)
                    request.session.pop('package_price', None)
                    request.session.pop('selected_plan_id', None)
                    request.session.pop('declared_member_count', None)
                    # Clear OTP session data after successful registration
                    request.session.pop('otp_verified', None)
                    request.session.pop('otp_email', None)
                    success(request, f"Welcome to Church Books! Your 30-day free trial has started. You have {church.trial_days_remaining} days to explore all features.")
                    login(request, user)
                    
                    # Check if there's a redirect URL in session (e.g., from PayPal payment)
                    next_url = request.session.get('next_url')
                    if next_url:
                        del request.session['next_url']  # Clear it from session
                        return redirect(next_url)

                    return redirect("dashboard")

            except Exception as e:
                error(request, "An error occurred during registration. Please try again.")
                # Delete the user if church association failed
                if 'user' in locals():
                    user.delete()
        else:
            for field, errors_list in user_form.errors.items():
                for err in errors_list:
                    if field == '__all__':
                        error(request, err)
                    else:
                        error(request, err)
            for field, errors_list in church_form.errors.items():
                for err in errors_list:
                    error(request, err)
    else:
        user_form = CustomUserCreationForm()
        church_form = ChurchRegistrationForm(prefix='church', user=request.user if request.user.is_authenticated else None)
    
    context = {
        "user_form": user_form,
        "church_form": church_form
    }
    return render(request, "church_finances/register.html", context)

@admin_required
def church_approval_list(request):
    """
    List all churches pending approval, with platform-wide stats.
    """
    pending_churches = Church.objects.filter(is_approved=False).order_by('created_at')
    all_churches = Church.objects.all().select_related('registered_by').order_by('-created_at')

    # Pending offline/bank-transfer payments that have a reference submitted but not yet verified
    pending_payments = Church.objects.filter(
        is_approved=False,
        payment_method__in=('offline', 'bank_transfer'),
        offline_payment_reference__isnull=False,
        offline_verified_at__isnull=True,
    ).exclude(offline_payment_reference='').order_by('created_at')

    # Stats
    total_accounts = Church.objects.count()
    active_accounts = Church.objects.filter(is_approved=True, subscription_status='active').count()
    total_members = Member.objects.filter(is_active=True).count()
    pending_count = pending_churches.count()

    return render(request, 'church_finances/church_approval_list.html', {
        'pending_churches': pending_churches,
        'pending_payments': pending_payments,
        'all_churches': all_churches,
        'total_accounts': total_accounts,
        'active_accounts': active_accounts,
        'total_members': total_members,
        'pending_count': pending_count,
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
        return redirect('church_approval_list')

    # For offline payments, auto-verify if not already done
    if church.payment_method == 'offline' and not church.offline_verified_at:
        church.offline_verified_at = timezone.now()
        church.offline_verified_by = request.user
        if not church.offline_payment_reference:
            church.offline_payment_reference = f"ADMIN_APPROVED_{church.id}"

    church.is_approved = True
    church.subscription_status = 'active'
    # End any trial period since they are now fully subscribed
    church.is_trial_active = False
    if not church.subscription_start_date:
        church.subscription_start_date = timezone.now()
    if not church.subscription_end_date:
        church.subscription_end_date = timezone.now() + timezone.timedelta(days=365)
    church.save()

    church_members = ChurchMember.objects.filter(church=church)
    activated_users = []
    for member in church_members:
        if not member.user.is_active:
            member.user.is_active = True
            member.user.save()
            activated_users.append(member.user.username)
        if not member.is_active:
            member.is_active = True
            member.save()

    success_msg = f"Church '{church.name}' has been approved and activated."
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

@admin_required
@require_POST
def verify_offline_payment(request, church_id):
    """Verify offline payment for a pending church and approve it.

    Expects POST fields:
      offline_payment_reference (required)
      offline_notes (optional)
    """
    church = get_object_or_404(Church, id=church_id)
    if church.payment_method != 'offline':
        error(request, f"Church '{church.name}' is not using offline payment.")
        return redirect('church_approval_list')
    reference = request.POST.get('offline_payment_reference', '').strip()
    notes = request.POST.get('offline_notes', '').strip()
    if not reference:
        error(request, "Offline payment reference is required to verify payment.")
        return redirect('church_approval_list')
    # Update church payment verification fields
    church.offline_payment_reference = reference
    church.offline_notes = notes
    church.offline_verified_by = request.user
    church.offline_verified_at = timezone.now()
    # Approve and activate subscription, end trial
    church.is_approved = True
    church.subscription_status = 'active'
    church.is_trial_active = False
    if not church.subscription_start_date:
        church.subscription_start_date = timezone.now()
    if not church.subscription_end_date:
        church.subscription_end_date = timezone.now() + timezone.timedelta(days=365)
    church.save()

    # Activate users/members associated if not active
    members = ChurchMember.objects.filter(church=church)
    activated_users = []
    for member in members:
        if not member.user.is_active:
            member.user.is_active = True
            member.user.save()
            activated_users.append(member.user.username)
        if not member.is_active:
            member.is_active = True
            member.save()

    msg = f"Offline payment verified and church '{church.name}' approved."
    if activated_users:
        msg += f" Activated users: {', '.join(activated_users)}"
    success(request, msg)
    return redirect('church_approval_list')


@admin_required
@require_POST
def deny_payment(request, church_id):
    """Deny / reject an offline payment submission — keeps the church record but marks
    payment as denied and sets subscription_status back to pending."""
    church = get_object_or_404(Church, id=church_id)
    reason = request.POST.get('deny_reason', '').strip()
    church.offline_payment_reference = None
    church.offline_verified_at = None
    church.offline_verified_by = None
    church.offline_notes = reason if reason else 'Payment denied by admin.'
    church.subscription_status = 'pending'
    church.is_approved = False
    church.save()
    error(request, f"Payment for '{church.name}' has been denied. The church will need to resubmit.")
    return redirect('church_approval_list')


@admin_required
@require_POST
def admin_delete_church(request, church_id):
    """Hard-delete a church record (for cleaning up test / old data)."""
    church = get_object_or_404(Church, id=church_id)
    name = church.name
    church.delete()
    success(request, f"Church '{name}' has been permanently deleted.")
    return redirect('church_approval_list')


# CSRF-related imports removed as CSRF protection is disabled
from django.core.exceptions import PermissionDenied
import logging

logger = logging.getLogger(__name__)

def user_login_view(request):
    """
    Handles user login.
    """
    if request.method == "POST":
        # 1. IP-based rate limit: max 5 attempts per IP per 5 minutes
        ip = _client_ip(request)
        if _is_rate_limited(f'login_attempt_{ip}', max_attempts=5, window_seconds=300):
            error(request, 'Too many login attempts from your network. Please wait 5 minutes before trying again.')
            return render(request, 'church_finances/login.html', {'form': AuthenticationForm()})

        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        # 2. Per-username lockout: locked after 5 failed attempts for 15 minutes
        username_fail_key = f'login_fail_user_{username.lower()}'
        if _get_fail_count(username_fail_key) >= 5:
            error(request, 'This account has been temporarily locked due to too many failed attempts. Please try again in 15 minutes or reset your password.')
            return render(request, 'church_finances/login.html', {'form': AuthenticationForm()})

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

                # Check trial status and redirect to payment if expired
                if not member.church.can_access_dashboard:
                    if member.church.is_trial_expired:
                        # Log the user in so the payment page can access their church info
                        login(request, user)
                        return redirect("trial_expired_payment")
                    else:
                        error(request, "Your church account does not have access. Please contact an administrator.")
                        return render(request, "church_finances/login.html", {"form": form})

            except ChurchMember.DoesNotExist:
                # Allow admin users without church membership
                if not user.is_superuser:
                    error(request, "No church membership found. Please contact an administrator.")
                    return render(request, "church_finances/login.html", {"form": form})

            # Successful login: reset failure counter and notify the account owner
            _clear_rate_limit(username_fail_key)
            _send_login_notification(user, request)
            login(request, user)

            # Check if there's a redirect URL in session (e.g., from PayPal payment)
            next_url = request.session.get('next_url')
            if next_url:
                del request.session['next_url']  # Clear it from session
                return redirect(next_url)

            return redirect("dashboard")
        else:
            # Track per-username failures; send lockout email when threshold reached
            try:
                fail_user = User.objects.get(username=username)
                fail_count = _increment_fail_count(username_fail_key, window_seconds=900)
                if fail_count >= 5:
                    _send_lockout_notification(fail_user, request)
            except User.DoesNotExist:
                pass  # Don't reveal whether the username exists
            error(request, "Something went wrong. Please check your credentials and try again.")
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

    members = Member.objects.filter(church=church)
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

    # ---- Member limit enforcement ----------------------------------------
    if church.is_at_member_limit:
        limit = church.member_limit
        plan_name = church.subscription_plan.name if church.subscription_plan else 'your current plan'
        error(
            request,
            f"You have reached the member capacity for {plan_name} "
            f"({limit} members). Please upgrade your plan to add more members."
        )
        return redirect('member_list')
    # -----------------------------------------------------------------------

    if request.method == "POST":
        form = MemberForm(request.POST)
        if form.is_valid():
            try:
                # Second check inside the transaction to prevent race conditions
                if church.is_at_member_limit:
                    limit = church.member_limit
                    plan_name = church.subscription_plan.name if church.subscription_plan else 'your current plan'
                    error(
                        request,
                        f"You have reached the member capacity for {plan_name} "
                        f"({limit} members). Please upgrade your plan to add more members."
                    )
                    return redirect('member_list')
                new_member = form.save(commit=False)
                new_member.church = church
                new_member.save()
                success(request, f"Member '{new_member.full_name}' added successfully!")
                return redirect("member_list")
            except Exception as e:
                error(request, f"Error creating member: {str(e)}")
    else:
        form = MemberForm(initial={'membership_date': date.today()})

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

    member = get_object_or_404(Member, pk=pk, church=church)
    
    # Get member's contribution history
    contributions = Contribution.objects.filter(member=member).order_by('-date')
    
    context = {
        "member": member,
        "contributions": contributions,
        "church": church
    }
    return render(request, "church_finances/member_detail.html", context)

@login_required
@require_http_methods(["POST"])
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

    member = get_object_or_404(Member, pk=pk, church=church)
    member.is_active = True
    member.save()
    success(request, f"Member {member.full_name} has been activated.")
    return redirect('member_list')

@login_required
@require_http_methods(["POST"])
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

    member = get_object_or_404(Member, pk=pk, church=church)
    member.is_active = False
    member.save()
    success(request, f"Member {member.full_name} has been deactivated.")
    return redirect('member_list')


@login_required
def baptism_list_view(request):
    """
    Display all members who have been baptised.
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    baptised = Member.objects.filter(
        church=church,
        baptism_date__isnull=False
    ).order_by('-baptism_date')

    not_yet_baptised = Member.objects.filter(
        church=church,
        is_active=True,
        baptism_date__isnull=True
    ).order_by('last_name', 'first_name')

    return render(request, "church_finances/baptism_list.html", {
        "church": church,
        "baptised": baptised,
        "not_yet_baptised": not_yet_baptised,
        "total_baptised": baptised.count(),
    })


@login_required
def baptism_add_view(request):
    """
    Record a baptism for an existing member.
    Sets the baptism_date on their ChurchMember record.
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    # Allow church founder or any recognised staff role to record baptisms
    ALLOWED_ROLES = ['admin', 'pastor', 'bishop', 'assistant_pastor', 'deacon', 'treasurer']
    is_founder = (church.registered_by_id == request.user.pk)
    user_member = ChurchMember.objects.filter(user=request.user, church=church).first()
    has_role = user_member and user_member.role in ALLOWED_ROLES
    if not is_founder and not has_role:
        raise PermissionDenied("You don't have permission to record baptisms.")

    # Members not yet baptised (for the dropdown)
    not_yet_baptised = Member.objects.filter(
        church=church,
        baptism_date__isnull=True
    ).order_by('last_name', 'first_name')

    if request.method == "POST":
        member_id      = request.POST.get('member_id', '').strip()
        baptism_date   = request.POST.get('baptism_date', '').strip()
        baptism_location = request.POST.get('baptism_location', '').strip()
        notes          = request.POST.get('notes', '').strip()

        if not member_id or not baptism_date:
            error(request, "Please select a member and enter the baptism date.")
        else:
            member = get_object_or_404(Member, pk=member_id, church=church)
            member.baptism_date = baptism_date
            if notes:
                member.notes = (member.notes + "\n" + f"Baptism notes: {notes}").strip()
            member.save()
            success(request, f"{member.full_name} has been recorded as baptised on {baptism_date}.")
            return redirect('baptism_list')

    from datetime import date as _date
    preselected_member_id = request.GET.get('member', '')

    return render(request, "church_finances/baptism_add.html", {
        "church": church,
        "not_yet_baptised": not_yet_baptised,
        "today_date": _date.today().isoformat(),
        "preselected_member_id": preselected_member_id,
    })

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

    member = get_object_or_404(Member, pk=pk, church=church)
    if request.method == "POST":
        form = MemberForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            success(request, "Member updated successfully!")
            return redirect("member_list")
    else:
        form = MemberForm(instance=member)

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
            _sync_contribution_transaction(church, contribution.date, contribution.contribution_type, request.user)
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
            # Capture old values before saving so we can re-sync if they changed
            old_date = contribution.date
            old_type = contribution.contribution_type
            updated = form.save()
            # Sync old slot (in case date or type changed, that slot needs recalculating)
            _sync_contribution_transaction(church, old_date, old_type, request.user)
            # Sync new slot
            _sync_contribution_transaction(church, updated.date, updated.contribution_type, request.user)
            success(request, "Contribution updated successfully!")
            return redirect("contribution_list")
    else:
        form = ContributionForm(instance=contribution, church=church)

    return render(request, "church_finances/contribution_form.html", {"form": form})


@login_required
@require_POST
def contribution_delete_view(request, pk):
    """
    Delete a contribution and re-sync its transaction total.
    Requires POST (triggered by a small form with a delete button).
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'treasurer', 'pastor']:
        raise PermissionDenied("You don't have permission to delete contributions.")

    contribution = get_object_or_404(Contribution, pk=pk, church=church)
    saved_date = contribution.date
    saved_type = contribution.contribution_type
    contribution.delete()
    _sync_contribution_transaction(church, saved_date, saved_type, request.user)
    success(request, "Contribution deleted successfully.")
    return redirect("contribution_list")


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
    try:
        member = ChurchMember.objects.get(user=request.user, church=church)
        if member.role not in ['admin', 'pastor', 'bishop', 'treasurer']:
            raise PermissionDenied(f"You don't have permission to register staff members. Your role is '{member.role}' but 'admin', 'pastor', 'bishop', or 'treasurer' is required.")
    except ChurchMember.DoesNotExist:
        raise PermissionDenied("You are not a member of this church.")

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

@login_required
def profile_view(request):
    """User profile page – edit personal details and (if admin) church details."""
    church_member = request.user.churchmember_set.select_related('church').first()
    church = church_member.church if church_member else None
    is_church_admin = (
        church_member is not None and church_member.role == 'admin'
    ) or (
        church is not None and getattr(church, 'registered_by_id', None) == request.user.pk
    )

    personal_form = PersonalProfileForm(instance=request.user)
    church_form = ChurchDetailForm(instance=church) if (church and is_church_admin) else None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'personal':
            personal_form = PersonalProfileForm(request.POST, instance=request.user)
            if personal_form.is_valid():
                personal_form.save()
                success(request, 'Personal details updated successfully.')
                return redirect('profile')

        elif action == 'church' and church and is_church_admin:
            church_form = ChurchDetailForm(request.POST, request.FILES, instance=church)
            if church_form.is_valid():
                updated_church = church_form.save(commit=False)
                # If a new logo file was uploaded, also store it as base64
                new_logo = request.FILES.get('logo')
                if new_logo:
                    updated_church.save()          # save model first so ImageField path is set
                    updated_church.save_logo(new_logo)  # now store base64 copy
                else:
                    updated_church.save()
                success(request, 'Church details updated successfully.')
                return redirect('profile')

    return render(request, 'church_finances/profile.html', {
        'personal_form': personal_form,
        'church_form': church_form,
        'church': church,
        'church_member': church_member,
        'is_church_admin': is_church_admin,
    })


@login_required
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
    total_members = Member.objects.filter(church=church, is_active=True).count()
    total_transactions = Transaction.objects.filter(church=church).count()
    total_contributions = Contribution.objects.filter(church=church).count()
    total_children = Child.objects.filter(church=church, is_active=True).count()
    total_christenings = BabyChristening.objects.filter(church=church, is_active=True).count()
    
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
        "total_children": total_children,
        "total_christenings": total_christenings,
        # Trial system information — suppress trial banner when subscription is already active
        "is_trial_active": church.is_trial_active and church.subscription_status != 'active',
        "trial_days_remaining": church.trial_days_remaining,
        "is_trial_expired": church.is_trial_expired and church.subscription_status != 'active',
        "trial_end_date": church.trial_end_date,
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

    income_categories = [v for v, _ in Transaction.INCOME_CATEGORIES]
    expense_categories = [v for v, _ in Transaction.EXPENSE_CATEGORIES]
    return render(
        request,
        "church_finances/transaction_form.html",
        {
            "form": form,
            "title": "Add New Transaction",
            "income_categories": income_categories,
            "expense_categories": expense_categories,
        },
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

    income_categories = [v for v, _ in Transaction.INCOME_CATEGORIES]
    expense_categories = [v for v, _ in Transaction.EXPENSE_CATEGORIES]
    return render(
        request,
        "church_finances/transaction_form.html",
        {
            "form": form,
            "title": "Update Transaction",
            "income_categories": income_categories,
            "expense_categories": expense_categories,
        },
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
    ).order_by('date', 'member__last_name')

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
def contribution_member_annual_summary(request):
    """
    Generate a printable per-member annual contribution summary
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    year = int(request.GET.get('year', timezone.now().year))

    contributions = Contribution.objects.filter(
        church=church,
        date__year=year
    ).select_related('member').order_by('member__last_name', 'member__first_name')

    # Build per-member totals
    member_totals = {}
    for contribution in contributions:
        member = contribution.member
        member_id = member.id
        if member_id not in member_totals:
            member_totals[member_id] = {
                'id': member_id,
                'name': member.full_name,
                'tithe': 0,
                'offering': 0,
                'total': 0,
            }
        member_totals[member_id]['total'] += contribution.amount
        if contribution.contribution_type == 'tithe':
            member_totals[member_id]['tithe'] += contribution.amount
        elif contribution.contribution_type == 'offering':
            member_totals[member_id]['offering'] += contribution.amount

    grand_total = contributions.aggregate(Sum('amount'))['amount__sum'] or 0
    grand_tithe = contributions.filter(contribution_type='tithe').aggregate(Sum('amount'))['amount__sum'] or 0
    grand_offering = contributions.filter(contribution_type='offering').aggregate(Sum('amount'))['amount__sum'] or 0

    context = {
        'church': church,
        'member_totals': member_totals.values(),
        'year': year,
        'current_year': timezone.now().year,
        'grand_total': grand_total,
        'grand_tithe': grand_tithe,
        'grand_offering': grand_offering,
        'print_date': timezone.now(),
    }

    return render(request, "church_finances/print/member_annual_contributions.html", context)

@login_required
def contribution_member_detail(request, member_id):
    """
    Generate a printable individual member contribution report for a given year
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    year = int(request.GET.get('year', timezone.now().year))

    member = get_object_or_404(Member, id=member_id, church=church)

    contributions = Contribution.objects.filter(
        church=church,
        member=member,
        date__year=year
    ).order_by('date')

    total_tithe = contributions.filter(contribution_type='tithe').aggregate(Sum('amount'))['amount__sum'] or 0
    total_offering = contributions.filter(contribution_type='offering').aggregate(Sum('amount'))['amount__sum'] or 0
    grand_total = contributions.aggregate(Sum('amount'))['amount__sum'] or 0

    context = {
        'church': church,
        'member': member,
        'contributions': contributions,
        'year': year,
        'current_year': timezone.now().year,
        'total_tithe': total_tithe,
        'total_offering': total_offering,
        'grand_total': grand_total,
        'print_date': timezone.now(),
    }

    return render(request, "church_finances/print/member_contribution_detail.html", context)

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


@login_required
def trial_expired_payment_view(request):
    """
    Shown when a user's 30-day trial has expired.
    They can pay with Stripe (credit card) or submit an offline payment request.
    Admin can also activate them from the admin panel.
    """
    try:
        member = ChurchMember.objects.get(user=request.user)
        church = member.church
    except ChurchMember.DoesNotExist:
        return redirect('dashboard')

    # If their subscription is already active (e.g. admin approved), send to dashboard
    if church.subscription_status == 'active' and church.is_approved:
        return redirect('dashboard')

    context = {
        'church': church,
        'paypal_client_id': getattr(settings, 'PAYPAL_CLIENT_ID', ''),
    }
    return render(request, "church_finances/trial_expired_payment.html", context)


@login_required
@require_POST
def trial_expired_offline_request(request):
    """
    Handle offline payment request from the trial-expired page.
    Sets payment_method='offline' and marks the church as pending admin approval.
    """
    try:
        member = ChurchMember.objects.get(user=request.user)
        church = member.church
    except ChurchMember.DoesNotExist:
        return redirect('dashboard')

    offline_notes = request.POST.get('offline_notes', '').strip()
    church.payment_method = 'offline'
    church.subscription_status = 'pending'
    church.is_approved = False  # Needs admin to approve after payment confirmation
    if offline_notes:
        church.offline_notes = offline_notes
    church.save()

    success(request, "Your offline payment request has been submitted. An administrator will activate your account once payment is confirmed.")
    return render(request, "church_finances/pending_approval.html")

@login_required
def account_status_view(request):
    """
    Display detailed account status for troubleshooting
    """
    church = None
    church_member = None
    
    # Ensure user is authenticated
    if not request.user.is_authenticated:
        return redirect('login')
    
    try:
        # Get church member record (even if church is not approved)
        church_member = ChurchMember.objects.get(user=request.user)
        church = church_member.church
    except ChurchMember.DoesNotExist:
        # Try to find any church associated with this user
        try:
            # Look for any church membership, even inactive ones
            church_members = ChurchMember.objects.filter(user=request.user)
            if church_members.exists():
                church_member = church_members.first()
                church = church_member.church
        except:
            pass
    
    context = {
        'church': church,
        'church_member': church_member,
    }
    return render(request, 'church_finances/account_status.html', context)

@admin_required
def quick_approve_user_church(request, user_id):
    """
    Quick approve function for admins to fix user accounts
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    
    user = get_object_or_404(User, id=user_id)
    
    try:
        church_member = ChurchMember.objects.get(user=user)
        church = church_member.church
        
        # Approve and activate everything
        if not church.is_approved:
            church.is_approved = True
            church.subscription_status = 'active'
            if not church.subscription_start_date:
                church.subscription_start_date = timezone.now()
            if not church.subscription_end_date:
                church.subscription_end_date = timezone.now() + timezone.timedelta(days=365)
            
            # Auto-verify offline payments
            if church.payment_method == 'offline' and not church.offline_verified_at:
                church.offline_verified_at = timezone.now()
                church.offline_verified_by = request.user
                if not church.offline_payment_reference:
                    church.offline_payment_reference = f"QUICK_APPROVED_{church.id}"
            
            church.save()
        
        # Activate user and member
        if not user.is_active:
            user.is_active = True
            user.save()
        
        if not church_member.is_active:
            church_member.is_active = True
            church_member.save()
        
        success(request, f"Successfully approved and activated church '{church.name}' and user '{user.username}'")
        
    except ChurchMember.DoesNotExist:
        error(request, f"No church membership found for user '{user.username}'")
    
    return redirect('account_status')


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

    # Contribution.member is a FK to Member (congregation), not ChurchMember (staff).
    # Try to match by email so staff with a congregation Member record can see their contributions.
    member_record = None
    if request.user.email:
        member_record = Member.objects.filter(church=church, email=request.user.email).first()

    if member_record:
        contributions = Contribution.objects.filter(
            member=member_record,
            date__range=[start_date, end_date]
        ).order_by('-date')
    else:
        contributions = Contribution.objects.none()

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
            response['Content-Disposition'] = f'inline; filename="contribution_statement_{year}_{member.full_name.replace(" ", "_")}.pdf"'
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
            ).values('member__first_name', 'member__last_name').annotate(
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
    total_members_count = Member.objects.filter(church=church, is_active=True).count() if context_type == 'admin' else 0
    
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
        service_date = request.POST.get('service_date')
        default_payment_method = request.POST.get('default_payment_method', 'cash')
        
        success_count = 0
        error_count = 0
        synced_keys = set()  # track (date, contrib_type) pairs to sync after all saves
        
        # Process each row of contributions
        row_index = 0
        while True:
            member_id = request.POST.get(f'contributions[{row_index}][member]')
            if not member_id:
                break
                
            try:
                contrib_member = Member.objects.get(id=member_id, church=church)
                row_payment_method = request.POST.get(f'contributions[{row_index}][payment_method]') or default_payment_method
                
                # Define contribution types mapping
                contribution_types = {
                    'tithe': 'tithe',
                    'offering': 'offering', 
                    'special_offering': 'special_offering',
                    'building_fund': 'building_fund',
                    'missions': 'missions',
                    'other': 'other'
                }
                
                # Process each contribution type for this member
                for field_name, contrib_type in contribution_types.items():
                    amount_str = request.POST.get(f'contributions[{row_index}][{field_name}]', '0')
                    if amount_str:
                        try:
                            amount = float(amount_str)
                            if amount > 0:
                                contrib_date = datetime.strptime(service_date, '%Y-%m-%d').date()
                                Contribution.objects.create(
                                    member=contrib_member,
                                    church=church,
                                    date=contrib_date,
                                    contribution_type=contrib_type,
                                    amount=amount,
                                    payment_method=row_payment_method,
                                    notes=f"Bulk entry - {request.POST.get('service_type', 'Regular Service')}",
                                    recorded_by=request.user
                                )
                                synced_keys.add((contrib_date, contrib_type))
                                success_count += 1
                        except (ValueError, TypeError):
                            error_count += 1
                            
            except Member.DoesNotExist:
                error_count += 1
            except Exception as e:
                error_count += 1
                
            row_index += 1

        # Sync transactions for every (date, contrib_type) that was created
        for sync_date, sync_type in synced_keys:
            _sync_contribution_transaction(church, sync_date, sync_type, request.user)

        if success_count > 0:
            success(request, f"Successfully recorded {success_count} contributions.")
        if error_count > 0:
            error(request, f"Failed to record {error_count} contributions.")
            
        return redirect('contribution_list')

    # Get all church members for the dropdown
    church_members = Member.objects.filter(church=church, is_active=True).order_by('last_name', 'first_name')
    
    # Prepare members data for JavaScript
    import json
    from django.utils.safestring import mark_safe
    
    members_data = []
    for cm in church_members:
        members_data.append({
            'id': cm.id,
            'name': cm.full_name
        })
    
    from datetime import date
    
    context = {
        'member': member,
        'church': church,
        'church_members': church_members,
        'contribution_types': Contribution.CONTRIBUTION_TYPES,
        'payment_methods': Contribution.PAYMENT_METHODS,
        'members_json': mark_safe(json.dumps(members_data)),
        'today': date.today().strftime('%Y-%m-%d'),
    }
    
    return render(request, "church_finances/bulk_contribution_entry.html", context)


# ============== CHILDREN MANAGEMENT VIEWS ==============

@login_required
def children_list_view(request):
    """
    Display a list of all children in the church
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    children = Child.objects.filter(church=church, is_active=True).order_by('last_name', 'first_name')
    
    context = {
        'children': children,
        'church': church,
        'total_children': children.count(),
    }
    return render(request, "church_finances/children_list.html", context)


@login_required
def child_detail_view(request, child_id):
    """
    Display detailed information about a specific child
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")
    
    child = get_object_or_404(Child, id=child_id, church=church)
    
    # Get recent attendance records
    recent_attendance = ChildAttendance.objects.filter(child=child).order_by('-date')[:10]
    
    context = {
        'child': child,
        'church': church,
        'recent_attendance': recent_attendance,
    }
    return render(request, "church_finances/child_detail.html", context)


@login_required
def child_add_view(request):
    """
    Add a new child to the church
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    church_member = ChurchMember.objects.filter(user=request.user, church=church).first()
    if not church_member or church_member.role not in ['admin', 'pastor', 'bishop', 'assistant_pastor']:
        error(request, "You don't have permission to add children records.")
        return redirect('dashboard')

    if request.method == 'POST':
        # Get form data
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        date_of_birth = request.POST.get('date_of_birth')
        grade_level = request.POST.get('grade_level', '')
        sunday_school_class = request.POST.get('sunday_school_class', '')
        parent_ids = request.POST.getlist('parents')
        
        # Emergency contact info
        emergency_contact_name = request.POST.get('emergency_contact_name', '')
        emergency_contact_phone = request.POST.get('emergency_contact_phone', '')
        emergency_contact_relationship = request.POST.get('emergency_contact_relationship', '')
        
        # Additional info
        address = request.POST.get('address', '')
        phone_number = request.POST.get('phone_number', '')
        notes = request.POST.get('notes', '')
        
        try:
            # Create the child
            child = Child.objects.create(
                first_name=first_name,
                last_name=last_name,
                date_of_birth=date_of_birth,
                grade_level=grade_level,
                sunday_school_class=sunday_school_class,
                church=church,
                emergency_contact_name=emergency_contact_name,
                emergency_contact_phone=emergency_contact_phone,
                emergency_contact_relationship=emergency_contact_relationship,
                address=address,
                phone_number=phone_number,
                notes=notes,
                added_by=request.user
            )
            
            # Add parents if selected
            if parent_ids:
                parents = Member.objects.filter(id__in=parent_ids, church=church)
                child.parents.set(parents)
            
            success(request, f"Successfully added {child.full_name} to the children's directory.")
            return redirect('child_detail', child_id=child.id)
            
        except Exception as e:
            error(request, f"Error adding child: {str(e)}")
    
    # Get church members as potential parents
    church_members = Member.objects.filter(church=church, is_active=True).order_by('first_name', 'last_name')
    
    context = {
        'church': church,
        'church_members': church_members,
        'grade_levels': Child.GRADE_LEVELS,
        'sunday_school_classes': Child.SUNDAY_SCHOOL_CLASSES,
    }
    return render(request, "church_finances/child_add.html", context)


@login_required  
def child_edit_view(request, child_id):
    """
    Edit an existing child's information
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    church_member = ChurchMember.objects.filter(user=request.user, church=church).first()
    if not church_member or church_member.role not in ['admin', 'pastor', 'bishop', 'assistant_pastor']:
        error(request, "You don't have permission to edit children records.")
        return redirect('dashboard')

    child = get_object_or_404(Child, id=child_id, church=church)
    
    if request.method == 'POST':
        # Update child information
        child.first_name = request.POST.get('first_name')
        child.last_name = request.POST.get('last_name')
        child.date_of_birth = request.POST.get('date_of_birth')
        child.grade_level = request.POST.get('grade_level')
        child.sunday_school_class = request.POST.get('sunday_school_class')
        
        # Emergency contact info
        child.emergency_contact_name = request.POST.get('emergency_contact_name')
        child.emergency_contact_phone = request.POST.get('emergency_contact_phone')
        child.emergency_contact_relationship = request.POST.get('emergency_contact_relationship')
        
        # Medical info
        child.allergies = request.POST.get('allergies')
        child.medications = request.POST.get('medications')
        child.medical_notes = request.POST.get('medical_notes')
        
        # Additional info
        child.address = request.POST.get('address')
        child.phone_number = request.POST.get('phone_number')
        child.notes = request.POST.get('notes')
        child.is_active = request.POST.get('is_active') == 'on'
        
        try:
            child.save()
            
            # Update parents
            parent_ids = request.POST.getlist('parents')
            if parent_ids:
                parents = Member.objects.filter(id__in=parent_ids, church=church)
                child.parents.set(parents)
            else:
                child.parents.clear()
                
            success(request, f"Successfully updated {child.full_name}'s information.")
            return redirect('child_detail', child_id=child.id)
            
        except Exception as e:
            error(request, f"Error updating child: {str(e)}")
    
    # Get church members as potential parents
    church_members = Member.objects.filter(church=church, is_active=True).order_by('first_name', 'last_name')
    
    context = {
        'child': child,
        'church': church,
        'church_members': church_members,
        'grade_levels': Child.GRADE_LEVELS,
        'sunday_school_classes': Child.SUNDAY_SCHOOL_CLASSES,
    }
    return render(request, "church_finances/child_edit.html", context)


@login_required
def attendance_record_view(request):
    """
    Record attendance for children
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    church_member = ChurchMember.objects.filter(user=request.user, church=church).first()
    if not church_member or church_member.role not in ['admin', 'pastor', 'bishop', 'assistant_pastor', 'deacon']:
        error(request, "You don't have permission to record attendance.")
        return redirect('dashboard')

    if request.method == 'POST':
        date = request.POST.get('date')
        activity_type = request.POST.get('activity_type')
        activity_name = request.POST.get('activity_name', '')
        
        attendance_data = request.POST.getlist('attendance')  # List of child IDs who were present
        
        try:
            children = Child.objects.filter(church=church, is_active=True)
            
            for child in children:
                # Check if child was marked as present
                present = str(child.id) in attendance_data
                
                # Create or update attendance record
                attendance, created = ChildAttendance.objects.update_or_create(
                    child=child,
                    church=church,
                    date=date,
                    activity_type=activity_type,
                    defaults={
                        'activity_name': activity_name,
                        'present': present,
                        'recorded_by': request.user
                    }
                )
            
            success(request, f"Attendance recorded for {activity_type} on {date}.")
            return redirect('attendance_record')
            
        except Exception as e:
            error(request, f"Error recording attendance: {str(e)}")
    
    children = Child.objects.filter(church=church, is_active=True).order_by('last_name', 'first_name')
    
    context = {
        'church': church,
        'children': children,
        'activity_types': ChildAttendance.ACTIVITY_TYPES,
    }
    return render(request, "church_finances/attendance_record.html", context)


# ============== BABY CHRISTENING VIEWS ==============

@login_required
def christenings_list_view(request):
    """
    Display a list of all baby christenings in the church
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    christenings = BabyChristening.objects.filter(church=church, is_active=True).order_by('-christening_date')
    
    context = {
        'christenings': christenings,
        'church': church,
        'total_christenings': christenings.count(),
    }
    return render(request, "church_finances/christenings_list.html", context)


@login_required
def christening_detail_view(request, christening_id):
    """
    Display detailed information about a specific christening
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")
    
    christening = get_object_or_404(BabyChristening, id=christening_id, church=church)
    
    context = {
        'christening': christening,
        'church': church,
    }
    return render(request, "church_finances/christening_detail.html", context)


@login_required
def christening_add_view(request):
    """
    Add a new baby christening record
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    if request.method == 'POST':
        try:
            # Get baby information
            baby_first_name = request.POST.get('baby_first_name')
            baby_last_name = request.POST.get('baby_last_name')
            baby_date_of_birth = request.POST.get('baby_date_of_birth') or None
            
            # Get christening details
            christening_date = request.POST.get('christening_date')
            christening_time = request.POST.get('christening_time') or None
            pastor = request.POST.get('pastor')
            ceremony_notes = request.POST.get('ceremony_notes')
            certificate_number = request.POST.get('certificate_number')
            
            # Get parents information
            father_name = request.POST.get('father_name')
            mother_name = request.POST.get('mother_name')
            parent_member_ids = request.POST.getlist('parent_members')
            
            # Get godparents information
            godfather_name = request.POST.get('godfather_name')
            godmother_name = request.POST.get('godmother_name')
            other_godparents = request.POST.get('other_godparents')
            
            # Get contact information
            contact_phone = request.POST.get('contact_phone', '')
            contact_email = request.POST.get('contact_email', '')
            
            # Create the christening record
            christening = BabyChristening.objects.create(
                baby_first_name=baby_first_name,
                baby_last_name=baby_last_name,
                baby_date_of_birth=baby_date_of_birth,
                christening_date=christening_date,
                christening_time=christening_time,
                pastor=pastor or '',
                ceremony_notes=ceremony_notes or '',
                certificate_number=certificate_number or '',
                father_name=father_name or '',
                mother_name=mother_name or '',
                godfather_name=godfather_name or '',
                godmother_name=godmother_name or '',
                other_godparents=other_godparents or '',
                contact_phone=contact_phone,
                contact_email=contact_email,
                church=church,
                recorded_by=request.user
            )
            
            # Add parent members if selected
            if parent_member_ids:
                parent_members = Member.objects.filter(id__in=parent_member_ids, church=church)
                christening.parent_members.set(parent_members)
            
            success(request, f"Successfully added christening record for {christening.baby_full_name}.")
            return redirect('christening_detail', christening_id=christening.id)
            
        except Exception as e:
            error(request, f"Error adding christening: {str(e)}")
    
    # Get church members as potential parents
    church_members = Member.objects.filter(church=church, is_active=True).order_by('first_name', 'last_name')
    
    context = {
        'church': church,
        'church_members': church_members,
    }
    return render(request, "church_finances/christening_add.html", context)


@login_required  
def christening_edit_view(request, christening_id):
    """
    Edit an existing christening record
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")
    
    christening = get_object_or_404(BabyChristening, id=christening_id, church=church)
    
    if request.method == 'POST':
        try:
            # Update baby information
            christening.baby_first_name = request.POST.get('baby_first_name')
            christening.baby_last_name = request.POST.get('baby_last_name')
            christening.baby_date_of_birth = request.POST.get('baby_date_of_birth') or None
            
            # Update christening details
            christening.christening_date = request.POST.get('christening_date')
            christening.christening_time = request.POST.get('christening_time') or None
            christening.pastor = request.POST.get('pastor')
            christening.ceremony_notes = request.POST.get('ceremony_notes')
            christening.certificate_number = request.POST.get('certificate_number')
            
            # Update parents information
            christening.father_name = request.POST.get('father_name')
            christening.mother_name = request.POST.get('mother_name')
            
            # Update godparents information
            christening.godfather_name = request.POST.get('godfather_name')
            christening.godmother_name = request.POST.get('godmother_name')
            christening.other_godparents = request.POST.get('other_godparents')
            
            # Update contact information
            christening.contact_address = request.POST.get('contact_address')
            christening.contact_phone = request.POST.get('contact_phone')
            christening.contact_email = request.POST.get('contact_email')
            
            # Update status
            christening.is_active = request.POST.get('is_active') == 'on'
            
            christening.save()
            
            # Update parent members
            parent_member_ids = request.POST.getlist('parent_members')
            if parent_member_ids:
                parent_members = Member.objects.filter(id__in=parent_member_ids, church=church)
                christening.parent_members.set(parent_members)
            else:
                christening.parent_members.clear()
                
            success(request, f"Successfully updated christening record for {christening.baby_full_name}.")
            return redirect('christening_detail', christening_id=christening.id)
            
        except Exception as e:
            error(request, f"Error updating christening: {str(e)}")
    
    # Get church members as potential parents
    church_members = Member.objects.filter(church=church, is_active=True).order_by('first_name', 'last_name')
    
    context = {
        'christening': christening,
        'church': church,
        'church_members': church_members,
    }
    return render(request, "church_finances/christening_edit.html", context)


# ---------------------------------------------------------------------------
# Certificate Templates
# ---------------------------------------------------------------------------

@login_required
def certificate_templates_list(request):
    """List all certificate templates for this church."""
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'pastor']:
        raise PermissionDenied("You don't have permission to manage certificate templates.")

    templates = CertificateTemplate.objects.filter(church=church)
    context = {
        'church': church,
        'templates': templates,
        'type_choices': CertificateTemplate.TYPE_CHOICES,
    }
    return render(request, "church_finances/certificate_templates_list.html", context)


@login_required
def certificate_template_create(request):
    """Create a new certificate template."""
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'pastor']:
        raise PermissionDenied

    if request.method == 'POST':
        try:
            tmpl = CertificateTemplate.objects.create(
                church=church,
                name=request.POST.get('name', ''),
                certificate_type=request.POST.get('certificate_type', 'christening'),
                title_text=request.POST.get('title_text', 'Certificate of Christening'),
                subtitle_text=request.POST.get('subtitle_text', ''),
                footer_text=request.POST.get('footer_text', ''),
                border_color=request.POST.get('border_color', '#1e3a5f'),
                primary_color=request.POST.get('primary_color', '#1e3a5f'),
                accent_color=request.POST.get('accent_color', '#c9a84c'),
                background_color=request.POST.get('background_color', '#fdfaf4'),
                background_style=request.POST.get('background_style', 'solid'),
                background_color2=request.POST.get('background_color2', '#ffffff'),
                gradient_direction=request.POST.get('gradient_direction', 'to bottom right'),
                corner_style=request.POST.get('corner_style', 'none'),
                border_style=request.POST.get('border_style', 'double'),
                border_width=int(request.POST.get('border_width', 6)),
                show_logo='show_logo' in request.POST,
                is_active='is_active' in request.POST,
                baptism_declaration=request.POST.get(
                    'baptism_declaration',
                    'was baptised in the name of the Father, the Son, and the Holy Spirit'
                ),
            )
            success(request, f"Template '{tmpl.name}' created successfully.")
            return redirect('certificate_templates_list')
        except Exception as e:
            error(request, f"Error creating template: {str(e)}")

    context = {
        'church': church,
        'type_choices': CertificateTemplate.TYPE_CHOICES,
        'border_choices': CertificateTemplate.BORDER_CHOICES,
        'corner_style_choices': CertificateTemplate.CORNER_STYLE_CHOICES,
        'template': None,
    }
    return render(request, "church_finances/certificate_template_form.html", context)


@login_required
def certificate_template_edit(request, template_id):
    """Edit an existing certificate template."""
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'pastor']:
        raise PermissionDenied

    tmpl = get_object_or_404(CertificateTemplate, pk=template_id, church=church)

    if request.method == 'POST':
        try:
            tmpl.name               = request.POST.get('name', tmpl.name)
            tmpl.certificate_type   = request.POST.get('certificate_type', tmpl.certificate_type)
            tmpl.title_text         = request.POST.get('title_text', tmpl.title_text)
            tmpl.subtitle_text      = request.POST.get('subtitle_text', '')
            tmpl.footer_text        = request.POST.get('footer_text', '')
            tmpl.border_color       = request.POST.get('border_color', tmpl.border_color)
            tmpl.primary_color      = request.POST.get('primary_color', tmpl.primary_color)
            tmpl.accent_color       = request.POST.get('accent_color', tmpl.accent_color)
            tmpl.background_color   = request.POST.get('background_color', tmpl.background_color)
            tmpl.background_style   = request.POST.get('background_style', tmpl.background_style)
            tmpl.background_color2  = request.POST.get('background_color2', tmpl.background_color2)
            tmpl.gradient_direction = request.POST.get('gradient_direction', tmpl.gradient_direction)
            tmpl.corner_style          = request.POST.get('corner_style', tmpl.corner_style)
            tmpl.border_style          = request.POST.get('border_style', tmpl.border_style)
            tmpl.border_width          = int(request.POST.get('border_width', tmpl.border_width))
            tmpl.show_logo             = 'show_logo' in request.POST
            tmpl.is_active             = 'is_active' in request.POST
            tmpl.baptism_declaration   = request.POST.get('baptism_declaration', tmpl.baptism_declaration)
            tmpl.save()
            success(request, f"Template '{tmpl.name}' updated.")
            return redirect('certificate_templates_list')
        except Exception as e:
            error(request, f"Error updating template: {str(e)}")

    context = {
        'church': church,
        'template': tmpl,
        'type_choices': CertificateTemplate.TYPE_CHOICES,
        'border_choices': CertificateTemplate.BORDER_CHOICES,
        'corner_style_choices': CertificateTemplate.CORNER_STYLE_CHOICES,
    }
    return render(request, "church_finances/certificate_template_form.html", context)


@login_required
def certificate_template_delete(request, template_id):
    """Delete a certificate template (POST only)."""
    church = get_user_church(request.user)
    if not church:
        return redirect('christenings_list')
    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'pastor']:
        raise PermissionDenied
    tmpl = get_object_or_404(CertificateTemplate, pk=template_id, church=church)
    if request.method == 'POST':
        tmpl.delete()
        success(request, "Template deleted.")
    return redirect('certificate_templates_list')


@login_required
def certificate_template_detail(request, template_id):
    """View full details and a live preview of a certificate template."""
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    member = ChurchMember.objects.get(user=request.user, church=church)
    if member.role not in ['admin', 'pastor']:
        raise PermissionDenied("You don't have permission to view certificate templates.")

    tmpl = get_object_or_404(CertificateTemplate, pk=template_id, church=church)
    context = {
        'church': church,
        'tmpl': tmpl,
        'colour_fields': [
            ('Primary Colour',    tmpl.primary_color),
            ('Accent Colour',     tmpl.accent_color),
            ('Background Colour', tmpl.background_color),
            ('Background Colour 2', tmpl.background_color2),
        ],
    }
    return render(request, "church_finances/certificate_template_detail.html", context)


@login_required
def christening_certificate_view(request, christening_id):
    """Render a printable christening certificate using the church's active template."""
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    christening = get_object_or_404(BabyChristening, pk=christening_id, church=church)

    # Find the active christening template; fall back to a default if none exists
    tmpl = CertificateTemplate.objects.filter(
        church=church, certificate_type='christening', is_active=True
    ).first()

    context = {
        'christening': christening,
        'church': church,
        'tmpl': tmpl,
    }
    return render(request, "church_finances/christening_certificate.html", context)


@login_required
def baptism_certificate_view(request, member_id):
    """Render a printable baptism certificate for a member using the church's active baptism template."""
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    member = get_object_or_404(Member, pk=member_id, church=church)

    tmpl = CertificateTemplate.objects.filter(
        church=church, certificate_type='baptism', is_active=True
    ).first()

    context = {
        'member': member,
        'church': church,
        'tmpl': tmpl,
    }
    return render(request, "church_finances/baptism_certificate.html", context)
