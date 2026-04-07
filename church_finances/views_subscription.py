from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.utils import timezone
from django.contrib.auth.models import User, Group
from django.contrib.auth import login
from django.db import transaction
from datetime import timedelta
import json
import stripe as stripe_lib
from .models import Church, PayPalSubscription, ChurchMember, SubscriptionPlan
from .paypal_service import PayPalService
from .stripe_service import create_checkout_session, retrieve_checkout_session, construct_webhook_event
from django.utils.decorators import method_decorator
from django.views import View
from django.utils import timezone
from django.contrib.auth.models import User
from datetime import timedelta
import json
from .models import Church, PayPalSubscription, ChurchMember, SubscriptionPlan
from .paypal_service import PayPalService
from .mock_paypal_service import MockPayPalService

def get_paypal_service():
    """
    Return either real or mock PayPal service based on configuration
    """
    if getattr(settings, 'USE_MOCK_PAYPAL', False):
        return MockPayPalService()
    else:
        return PayPalService()

@ensure_csrf_cookie
def subscription_view(request):
    """
    Display subscription packages
    """
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('annual_price')

    context = {
        'paypal_client_id': getattr(settings, 'PAYPAL_CLIENT_ID', ''),
        'standard_plan_id': getattr(settings, 'PAYPAL_STANDARD_PLAN_ID', ''),
        'paypal_mode': getattr(settings, 'PAYPAL_MODE', 'sandbox'),
        'plans': plans,
    }
    
    # Add trial information if user is authenticated
    if request.user.is_authenticated:
        try:
            from .models import ChurchMember
            member = ChurchMember.objects.filter(user=request.user).first()
            if member and member.church:
                church = member.church
                context.update({
                    'church': church,
                    'is_trial_active': church.is_trial_active,
                    'trial_days_remaining': church.trial_days_remaining,
                    'is_trial_expired': church.is_trial_expired,
                    'trial_end_date': church.trial_end_date,
                    'current_member_count': church.active_member_count,
                    'current_plan': church.subscription_plan,
                })
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting trial info for user {request.user}: {e}")
    
    return render(request, "church_finances/subscription.html", context)

def subscription_select(request):
    """
    Handle subscription package selection — supports all 4 tiers.
    For the custom tier the member_count POST field is required.
    Validates that the selected plan can accommodate the church's current member count.
    """
    if request.method == "POST":
        package = request.POST.get('package', '')
        member_count_raw = request.POST.get('member_count', '').strip()

        valid_slugs = ['starter', 'growth', 'community', 'custom']
        if package not in valid_slugs:
            messages.error(request, "Invalid package selection.")
            return redirect('subscription')

        try:
            plan = SubscriptionPlan.objects.get(slug=package, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            messages.error(
                request,
                "That plan is not currently available. Please contact support."
            )
            return redirect('subscription')

        # --- Custom tier: need declared member count ---------------------------
        declared_count = None
        if plan.is_custom:
            if not member_count_raw or not member_count_raw.isdigit():
                messages.error(request, "Please enter your church's member count for the Custom plan.")
                return redirect('subscription')
            declared_count = int(member_count_raw)
            if declared_count <= 200:
                messages.error(
                    request,
                    "The Custom plan is for churches with more than 200 members. "
                    "Please select the Community plan instead."
                )
                return redirect('subscription')
            price = SubscriptionPlan.calculate_custom_price(declared_count)
        else:
            price = float(plan.annual_price)

        # --- If authenticated, validate current member count vs chosen plan ----
        if request.user.is_authenticated:
            try:
                church_member = ChurchMember.objects.filter(user=request.user).first()
                if church_member and church_member.church:
                    church = church_member.church
                    current_count = church.active_member_count
                    plan_limit = declared_count if plan.is_custom else plan.member_limit
                    if plan_limit and current_count > plan_limit:
                        messages.error(
                            request,
                            f"This plan only allows {plan_limit} members, but your church currently "
                            f"has {current_count} active members. Please choose a larger plan."
                        )
                        return redirect('subscription')
            except Exception:
                pass

        # --- Store in session and proceed -------------------------------------
        request.session['selected_package'] = package
        request.session['package_price'] = str(price)
        request.session['selected_plan_id'] = plan.id
        if declared_count:
            request.session['declared_member_count'] = declared_count

        plan_id = getattr(settings, 'PAYPAL_STANDARD_PLAN_ID', '')
        request.session['paypal_plan_id'] = plan_id

        messages.success(
            request,
            f"You have selected the {plan.name} plan. Please complete your registration to start your free trial."
        )
        return redirect('register')

    return redirect('subscription')

@ensure_csrf_cookie
def payment_selection_view(request):
    """
    Show payment method selection (PayPal online or offline)
    """
    if request.method == "POST":
        payment_method = request.POST.get('payment_method', '')
        
        if payment_method in ['paypal', 'stripe', 'offline', 'bank_transfer']:
            # Store payment method in session
            request.session['payment_method'] = payment_method
            
            # For PayPal payment
            if payment_method in ['paypal', 'stripe']:
                # Preserve whatever package/price was already stored by subscription_select.
                # Only fall back to defaults if nothing is in the session yet.
                if not request.session.get('selected_package'):
                    request.session['selected_package'] = 'starter'
                    request.session['package_price'] = '150'
                plan_id = getattr(settings, 'PAYPAL_STANDARD_PLAN_ID', '')
                request.session['paypal_plan_id'] = plan_id
                
                # Check if user is logged in and has church account
                if request.user.is_authenticated:
                    try:
                        church_member = ChurchMember.objects.get(user=request.user)
                        # User already has account and church - go directly to PayPal
                        messages.success(request, "Proceeding to PayPal payment.")
                        return redirect('paypal_payment_direct')
                    except ChurchMember.DoesNotExist:
                        # User logged in but no church - go to registration first
                        messages.success(request, "Please complete your registration to proceed with payment.")
                        return redirect('registration_form')
                else:
                    # User not logged in - go to registration
                    messages.success(request, "Please register to proceed with PayPal payment.")
                    return redirect('registration_form')
            else:
                # Offline / Bank Transfer payment - requires registration and approval process
                if request.user.is_authenticated:
                    try:
                        church_member = ChurchMember.objects.get(user=request.user)
                        messages.info(request, "Payment selected. Please proceed with payment instructions.")
                        return redirect('offline_payment_form')
                    except ChurchMember.DoesNotExist:
                        messages.info(request, "Payment selected. Please complete your registration for approval.")
                        return redirect('registration_form')
                else:
                    messages.info(request, "Payment selected. Please complete your registration for approval.")
                    return redirect('registration_form')
        else:
            messages.error(request, "Please select a valid payment method.")
    
    # GET request - show payment selection form
    selected_package = request.session.get('selected_package')
    if not selected_package:
        messages.error(request, "Please select a subscription package first.")
        return redirect('subscription')
    
    context = {
        'selected_package': selected_package,
        'package_price': request.session.get('package_price'),
    }
    return render(request, 'church_finances/payment_selection.html', context)

@ensure_csrf_cookie
def registration_form_view(request):
    """
    Show registration form after payment method selection
    """
    if request.method == "POST":
        # Get payment method from session (empty = free trial sign-up)
        payment_method = request.session.get('payment_method', '')
        
        try:
            # Get form data
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip().lower()
            phone_number = request.POST.get('phone_number', '').strip()
            role = request.POST.get('role', '').strip()
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '')
            password_confirm = request.POST.get('password_confirm', '')
            church_name = request.POST.get('church_name', '').strip()
            church_address = request.POST.get('church_address', '').strip()
            church_phone = request.POST.get('church_phone', '').strip()
            church_email = request.POST.get('church_email', '').strip()
            church_website = request.POST.get('church_website', '').strip()
            
            # Validate required fields
            if not all([username, password, email, first_name, last_name, role, church_name, church_address, church_phone, church_email]):
                messages.error(request, "All required fields must be filled out.")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            # Validate role selection
            valid_roles = ['admin', 'pastor', 'bishop', 'assistant_pastor', 'treasurer', 'deacon']
            if role not in valid_roles:
                messages.error(request, "Please select a valid role.")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            # Validate password confirmation
            if password != password_confirm:
                messages.error(request, "Passwords do not match.")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            # Validate password strength
            import re
            if len(password) < 8:
                messages.error(request, "Password must be at least 8 characters long.")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            if not re.search(r'[A-Z]', password):
                messages.error(request, "Password must contain at least one uppercase letter.")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            if not re.search(r'[a-z]', password):
                messages.error(request, "Password must contain at least one lowercase letter.")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            if not re.search(r'[0-9]', password):
                messages.error(request, "Password must contain at least one number.")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;/]', password):
                messages.error(request, "Password must contain at least one special character (!@#$%^&*(),.?\":{}|<>_-+=[];/\\).")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            # Check if username already exists (case-insensitive)
            if User.objects.filter(username__iexact=username).exists():
                messages.error(request, "Username already exists.")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            # Check if email already exists (case-insensitive)
            if User.objects.filter(email__iexact=email).exists():
                messages.error(request, "Email already registered.")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            # Get selected package from session
            selected_package = request.session.get('selected_package')

            if not selected_package:
                messages.error(request, "Please select a subscription package first.")
                return redirect('subscription')
            
            print(f"DEBUG: Creating user account for {username} with payment method: {payment_method}")
            is_free_trial = not payment_method
            
            # Use database transaction to ensure data consistency
            with transaction.atomic():
                # Stripe: user inactive until payment confirmed
                # Offline: user active, church pending admin approval
                # Free trial: user active immediately, church approved, trial clock starts
                is_user_active   = payment_method != 'stripe'
                is_church_approved = is_free_trial
                church_status    = 'pending'
                is_member_active = payment_method != 'stripe'
                
                # Create user account
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    is_active=is_user_active  # User can login immediately
                )
                
                print(f"DEBUG: User created successfully with ID: {user.id}, active: {user.is_active}")
                
                # Create church record
                plan_id_session = request.session.get('selected_plan_id')
                plan_obj = None
                if plan_id_session:
                    try:
                        plan_obj = SubscriptionPlan.objects.get(id=plan_id_session)
                    except SubscriptionPlan.DoesNotExist:
                        pass
                declared_count = request.session.get('declared_member_count')
                sub_amount = float(request.session.get('package_price', 0) or 0)

                church = Church.objects.create(
                    name=church_name,
                    address=church_address,
                    phone=church_phone,
                    email=church_email,
                    website=church_website,
                    subscription_type=selected_package,
                    subscription_status=church_status,
                    is_approved=is_church_approved,
                    payment_method=payment_method if payment_method else 'offline',
                    trial_end_date=timezone.now() + timedelta(days=30) if is_free_trial else None,
                    subscription_plan=plan_obj,
                    declared_member_count=declared_count,
                    subscription_amount=sub_amount if sub_amount else None,
                )
                # Save logo if uploaded
                church_logo = request.FILES.get('church_logo')
                if church_logo:
                    church.save_logo(church_logo)
                
                print(f"DEBUG: Church created successfully with ID: {church.id}, approved: {church.is_approved}")
                
                # Create ChurchMember relationship
                church_member = ChurchMember.objects.create(
                    user=user,
                    church=church,
                    role=role,
                    phone_number=phone_number,
                    is_active=is_member_active
                )
                print(f"DEBUG: ChurchMember created successfully with ID: {church_member.id}, active: {church_member.is_active}")
                
                # Store user ID and church ID in session for later use
                request.session['pending_user_id'] = user.id
                request.session['church_id'] = church.id
            
            # Handle payment method
            if is_free_trial:
                login(request, user)
                messages.success(request, f"Welcome to Church Books! Your 30-day free trial has started. No payment is needed right now — enjoy full access to all features.")
                return redirect('dashboard')

            if payment_method == 'offline':
                # For offline payment, create records - admin approval needed
                messages.success(request, f"Registration successful! Your account '{username}' is pending admin approval. You will receive payment instructions once approved.")
                
                request.session.pop('selected_package', None)
                request.session.pop('package_price', None)
                request.session.pop('payment_method', None)
                
                return redirect('pending_approval')

            # Handle PayPal payment — log user in and redirect to PayPal form
            elif payment_method == 'paypal':
                plan_id = getattr(settings, 'PAYPAL_STANDARD_PLAN_ID', '')
                request.session['paypal_plan_id'] = plan_id
                login(request, user)
                messages.success(request, f"Account created! Please complete your PayPal payment to activate.")
                return redirect('paypal_payment_direct')
            
            # Handle Stripe payment — redirect to Stripe Checkout (legacy, kept for compatibility)
            elif payment_method == 'stripe':
                try:
                    success_url = request.build_absolute_uri('/finances/stripe/success/')
                    cancel_url  = request.build_absolute_uri('/finances/stripe/cancel/')

                    session = create_checkout_session(
                        church_id=church.id,
                        user_id=user.id,
                        email=email,
                        church_name=church_name,
                        success_url=success_url,
                        cancel_url=cancel_url,
                    )
                    return redirect(session.url, permanent=False)
                except Exception as e:
                    print(f"Stripe error: {str(e)}")
                    messages.error(request, f"Could not start Stripe payment: {str(e)}")
                    # Clean up pending records
                    church.delete()
                    user.delete()
                    return redirect('subscription')
                
        except Exception as e:
            print(f"DEBUG: Exception occurred: {str(e)}")
            messages.error(request, f"An error occurred: {str(e)}")
            return redirect('subscription')
    
    # GET request - show registration form
    selected_package = request.session.get('selected_package')
    payment_method = request.session.get('payment_method')
    
    if not selected_package:
        messages.error(request, "Please select a subscription package first.")
        return redirect('subscription')
    
    context = {
        'selected_package': selected_package,
        'package_price': request.session.get('package_price'),
        'payment_method': payment_method,
    }
    return render(request, 'church_finances/registration_form.html', context)

def paypal_payment_direct(request):
    """
    Show the PayPal subscription button page for an authenticated user with a pending church.
    """
    if not request.user.is_authenticated:
        request.session['next_url'] = '/finances/paypal/pay/'
        messages.info(request, "Please log in to complete your PayPal payment.")
        return redirect('login')

    # Get church even if not yet approved/active
    church_member = ChurchMember.objects.filter(user=request.user).first()
    if not church_member:
        messages.info(request, "Please register your church first.")
        return redirect('register')

    church = church_member.church

    # Already paid and active — send to dashboard
    if church.subscription_status == 'active' and church.is_approved:
        return redirect('dashboard')

    paypal_client_id = getattr(settings, 'PAYPAL_CLIENT_ID', '')

    # Resolve plan display info from the church record
    plan = church.subscription_plan
    if plan:
        plan_name = plan.name
        member_limit_display = f"Up to {plan.member_limit} members" if plan.member_limit else "200+ members (custom pricing)"
    else:
        plan_name = "Church Books"
        member_limit_display = "All features included"

    # Use stored amount; fall back to plan base price; final fall back $150
    if church.subscription_amount:
        amount = float(church.subscription_amount)
    elif plan:
        amount = float(plan.annual_price)
    else:
        amount = 150.00

    return render(request, 'church_finances/paypal_checkout.html', {
        'church': church,
        'paypal_client_id': paypal_client_id,
        'plan_name': plan_name,
        'member_limit_display': member_limit_display,
        'amount': f"{amount:.2f}",
    })


@login_required
@require_http_methods(["POST"])
def paypal_activate_subscription(request):
    """
    Called via AJAX from paypal_checkout.html after the PayPal subscription button
    is approved. Receives the subscriptionID and activates the church account.
    """
    try:
        data = json.loads(request.body)
        subscription_id = data.get('subscription_id', '').strip()
    except (json.JSONDecodeError, ValueError):
        subscription_id = request.POST.get('subscription_id', '').strip()

    if not subscription_id:
        return JsonResponse({'success': False, 'error': 'No subscription ID provided.'}, status=400)

    church_member = ChurchMember.objects.filter(user=request.user).first()
    if not church_member:
        return JsonResponse({'success': False, 'error': 'No church account found.'}, status=400)

    church = church_member.church

    # Activate the church
    church.paypal_subscription_id = subscription_id
    church.subscription_status = 'active'
    church.is_approved = True
    church.is_trial_active = False
    church.payment_method = 'paypal'
    if not church.subscription_start_date:
        church.subscription_start_date = timezone.now()
    if not church.subscription_end_date:
        church.subscription_end_date = timezone.now() + timedelta(days=365)
    church.save()

    # Activate the member
    church_member.is_active = True
    church_member.save()

    # Activate the user account if inactive
    if not request.user.is_active:
        request.user.is_active = True
        request.user.save()

    print(f"PayPal subscription activated: church={church.name}, subscription_id={subscription_id}")
    return JsonResponse({'success': True, 'redirect': '/finances/dashboard/'})


@login_required
@require_POST
def paypal_create_order(request):
    """
    AJAX: creates a PayPal one-time order with the church's actual subscription amount.
    Returns { orderID } to the PayPal JS SDK createOrder callback.
    """
    church_member = ChurchMember.objects.filter(user=request.user).first()
    if not church_member:
        return JsonResponse({'error': 'No church account found.'}, status=400)
    church = church_member.church

    # Determine amount and plan name
    plan = church.subscription_plan
    if church.subscription_amount:
        amount = f"{float(church.subscription_amount):.2f}"
    elif plan:
        amount = f"{float(plan.annual_price):.2f}"
    else:
        amount = "150.00"
    plan_name = plan.name if plan else "Church Books"

    from .paypal_service import PayPalService
    paypal = PayPalService()
    result = paypal.create_subscription(
        plan_id=plan.slug if plan else 'standard',
        payer_info={},
        church_id=church.id,
        amount=amount,
        plan_name=plan_name,
    )
    if result.get('success'):
        return JsonResponse({'orderID': result['subscription_id']})
    return JsonResponse({'error': result.get('error', 'Could not create PayPal order. Please try again.')}, status=500)


@login_required
@require_POST
def paypal_capture_order(request):
    """
    AJAX: captures the approved PayPal order server-side, verifies COMPLETED status,
    then activates the church subscription.
    """
    try:
        data = json.loads(request.body)
        order_id = data.get('order_id', '').strip()
    except (json.JSONDecodeError, ValueError):
        order_id = request.POST.get('order_id', '').strip()

    if not order_id:
        return JsonResponse({'success': False, 'error': 'No order ID provided.'}, status=400)

    church_member = ChurchMember.objects.filter(user=request.user).first()
    if not church_member:
        return JsonResponse({'success': False, 'error': 'No church account found.'}, status=400)
    church = church_member.church

    from .paypal_service import PayPalService
    paypal = PayPalService()
    result = paypal.capture_payment(order_id)

    if not result.get('success'):
        return JsonResponse({'success': False, 'error': result.get('error', 'Payment capture failed. Please contact support with your order ID: ' + order_id)})

    order_data = result.get('order', {})
    if order_data.get('status') != 'COMPLETED':
        return JsonResponse({'success': False, 'error': f"Payment not completed (status: {order_data.get('status', 'unknown')}). Please contact support."})

    # Activate the church
    church.paypal_subscription_id = order_id
    church.subscription_status = 'active'
    church.payment_status = 'paid'
    church.is_approved = True
    church.is_trial_active = False
    church.payment_method = 'paypal'
    if not church.subscription_start_date:
        church.subscription_start_date = timezone.now()
    if not church.subscription_end_date:
        church.subscription_end_date = timezone.now() + timedelta(days=365)
    church.save()

    church_member.is_active = True
    church_member.save()

    if not request.user.is_active:
        request.user.is_active = True
        request.user.save()

    print(f"PayPal order captured & church activated: church={church.name}, order_id={order_id}")
    return JsonResponse({'success': True, 'redirect': '/finances/dashboard/'})

@ensure_csrf_cookie
def create_paypal_subscription(request):
    """
    Create PayPal subscription
    """
    if request.method == "POST":
        try:
            # Check if this is an offline payment request
            payment_method = request.POST.get('payment_method', '')
            
            # Get form data
            first_name = request.POST.get('first_name', '')
            last_name = request.POST.get('last_name', '')
            email = request.POST.get('email', '').strip().lower()
            phone_number = request.POST.get('phone_number', '')
            role = request.POST.get('role', '')
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '')
            password_confirm = request.POST.get('password_confirm', '')
            church_name = request.POST.get('church_name', '')
            church_address = request.POST.get('church_address', '')
            church_phone = request.POST.get('church_phone', '')
            church_email = request.POST.get('church_email', '')
            church_website = request.POST.get('church_website', '')
            
            # Debug: Print received data
            print(f"DEBUG: Received form data:")
            print(f"Username: {username}")
            print(f"Email: {email}")
            print(f"First Name: {first_name}")
            print(f"Last Name: {last_name}")
            print(f"Church Name: {church_name}")
            
            # Validate required fields
            if not username or not password or not email or not first_name or not last_name or not role:
                messages.error(request, "All required fields must be filled out.")
                return render(request, 'church_finances/paypal_subscription_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                })
            
            # Validate role selection
            valid_roles = ['admin', 'pastor', 'bishop', 'assistant_pastor', 'treasurer', 'deacon']
            if role not in valid_roles:
                messages.error(request, "Please select a valid role.")
                return render(request, 'church_finances/paypal_subscription_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                })
            
            # Validate password confirmation
            if password != password_confirm:
                messages.error(request, "Passwords do not match.")
                return render(request, 'church_finances/paypal_subscription_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                })
            
            # Check if username already exists (case-insensitive)
            if User.objects.filter(username__iexact=username).exists():
                messages.error(request, "Username already exists.")
                return render(request, 'church_finances/paypal_subscription_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                })
            
            # Check if email already exists (case-insensitive)
            if User.objects.filter(email__iexact=email).exists():
                messages.error(request, "Email already registered.")
                return render(request, 'church_finances/paypal_subscription_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                })
            
            # Get selected package from session
            selected_package = request.session.get('selected_package')
            plan_id = request.session.get('paypal_plan_id')
            
            if not selected_package or not plan_id:
                messages.error(request, "Please select a subscription package first.")
                return redirect('subscription')
            
            print(f"DEBUG: Creating user account for {username}")
            
            # Create user account (inactive for offline payment, active for online payment approval)
            is_active = False if payment_method == 'offline' else False  # Always inactive until payment/approval
            
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_active=is_active
            )
            
            print(f"DEBUG: User created successfully with ID: {user.id}")
            
            # Create church record (not approved yet)
            plan_id_session = request.session.get('selected_plan_id')
            plan_obj = None
            if plan_id_session:
                try:
                    plan_obj = SubscriptionPlan.objects.get(id=plan_id_session)
                except SubscriptionPlan.DoesNotExist:
                    pass
            declared_count = request.session.get('declared_member_count')
            sub_amount = float(request.session.get('package_price', 0) or 0)

            church = Church.objects.create(
                name=church_name,
                address=church_address,
                phone=church_phone,
                email=church_email,
                website=church_website,
                subscription_type=selected_package,
                subscription_status='pending',
                is_approved=False,
                payment_method=('offline' if payment_method == 'offline' else 'paypal'),
                subscription_plan=plan_obj,
                declared_member_count=declared_count,
                subscription_amount=sub_amount if sub_amount else None,
            )
            # Save logo if uploaded
            church_logo = request.FILES.get('church_logo')
            if church_logo:
                church.save_logo(church_logo)
            
            print(f"DEBUG: Church created successfully with ID: {church.id}")
            
            # Create ChurchMember relationship with the selected role and phone number
            church_member = ChurchMember.objects.create(
                user=user,
                church=church,
                role=role,  # Use the role selected by the user
                phone_number=phone_number,
                is_active=False  # Will be activated when admin approves or payment is confirmed
            )
            print(f"DEBUG: ChurchMember created successfully with ID: {church_member.id}")
            
            # Store user ID with church for later activation
            request.session['pending_user_id'] = user.id
            request.session['church_id'] = church.id
            
            # Check if this is offline payment
            if payment_method == 'offline':
                # For offline payment, create records and redirect to pending approval
                messages.success(request, f"Registration submitted successfully! Your church account '{church_name}' and user login '{username}' are pending admin approval and offline payment confirmation. You will receive an email with payment instructions once approved.")
                
                # Clear session data
                request.session.pop('selected_package', None)
                request.session.pop('package_price', None)
                request.session.pop('paypal_plan_id', None)
                
                # Redirect to pending approval page
                return redirect('pending_approval')
            
            # Create PayPal subscription for online payment
            try:
                paypal_service = get_paypal_service()
                payer_info = {
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email
                }
                
                # Use simple plan identifiers
                plan_identifier = f"church_books_{selected_package}_plan"
                session_amount  = request.session.get('package_price')
                
                result = paypal_service.create_subscription(
                    plan_identifier, payer_info, church.id,
                    amount=session_amount
                )
                
                if result['success']:
                    # Store subscription ID for later reference
                    request.session['pending_subscription_id'] = result['subscription_id']
                    
                    # Redirect to PayPal for approval
                    return redirect(result['approval_url'])
                else:
                    # Clean up if PayPal subscription creation failed
                    church.delete()
                    user.delete()
                    messages.error(request, f"Failed to create subscription: {result['error']}")
                    return redirect('subscription')
            except Exception as e:
                # If PayPal fails, redirect to offline payment option
                print(f"PayPal service error: {str(e)}")
                messages.warning(request, "PayPal service temporarily unavailable. Please use offline payment option or try again later.")
                church.delete()
                user.delete()
                return redirect('pending_approval')
                
        except Exception as e:
            print(f"DEBUG: Exception occurred: {str(e)}")
            messages.error(request, f"An error occurred: {str(e)}")
            return redirect('subscription')
    
    # GET request - show the subscription form
    selected_package = request.session.get('selected_package')
    if not selected_package:
        messages.error(request, "Please select a subscription package first.")
        return redirect('subscription')
    
    context = {
        'selected_package': selected_package,
        'package_price': request.session.get('package_price'),
    }
    return render(request, 'church_finances/paypal_subscription_form.html', context)

def paypal_success(request):
    """
    Handle successful PayPal payment approval
    """
    token = request.GET.get('token')  # PayPal order ID
    payer_id = request.GET.get('PayerID')
    
    if not token:
        messages.error(request, "Invalid PayPal response.")
        return redirect('subscription')
    
    try:
        # Get order details and capture payment
        paypal_service = get_paypal_service()
        
        # First get order details
        order_result = paypal_service.get_order_details(token)
        
        if order_result['success']:
            order = order_result['order']
            
            # Capture the payment
            capture_result = paypal_service.capture_payment(token)
            
            if capture_result['success']:
                captured_order = capture_result['order']
                
                # Get church ID from custom_id
                purchase_units = order.get('purchase_units', [])
                if purchase_units:
                    custom_id = purchase_units[0].get('custom_id')
                    if custom_id:
                        church = get_object_or_404(Church, id=custom_id)
                        
                        # Ensure church payment_method is set to paypal
                        if church.payment_method != 'paypal':
                            church.payment_method = 'paypal'
                        # Create PayPalSubscription record
                        paypal_sub, created = PayPalSubscription.objects.get_or_create(
                            subscription_id=token,
                            defaults={
                                'church': church,
                                'plan_id': 'paypal_order',
                                'status': 'ACTIVE',
                                'payer_id': payer_id or '',
                                'payer_email': order.get('payer', {}).get('email_address', ''),
                                'create_time': timezone.now(),
                                'start_time': timezone.now(),
                                'amount': float(purchase_units[0].get('amount', {}).get('value', 0)),
                                'currency': purchase_units[0].get('amount', {}).get('currency_code', 'USD')
                            }
                        )
                        
                        # Approve and activate the church immediately after successful payment
                        church.is_approved = True
                        church.subscription_status = 'active'
                        church.paypal_subscription_id = token
                        church.subscription_start_date = timezone.now()
                        church.subscription_end_date = timezone.now() + timedelta(days=365)
                        church.save()
                        
                        # Activate the user account and church member
                        pending_user_id = request.session.get('pending_user_id')
                        if pending_user_id:
                            try:
                                user = User.objects.get(id=pending_user_id)
                                user.is_active = True
                                user.save()
                                
                                # Also activate the ChurchMember
                                try:
                                    church_member = ChurchMember.objects.get(user=user, church=church)
                                    church_member.is_active = True
                                    church_member.save()
                                    
                                    # Automatically log in the user after successful payment
                                    login(request, user)
                                    
                                    messages.success(request, f"Payment successful! Welcome {user.first_name}! Your church account '{church.name}' and user login '{user.username}' have been approved and activated. You are now logged in.")
                                except ChurchMember.DoesNotExist:
                                    messages.success(request, f"Payment successful! Your church account '{church.name}' has been approved and activated.")
                                    
                            except User.DoesNotExist:
                                messages.success(request, f"Payment successful! Your church account '{church.name}' has been approved and activated.")
                        else:
                            messages.success(request, f"Payment successful! Your church account '{church.name}' has been approved and activated.")
                        
                        # Clear session data
                        request.session.pop('selected_package', None)
                        request.session.pop('package_price', None)
                        request.session.pop('paypal_plan_id', None)
                        request.session.pop('pending_subscription_id', None)
                        request.session.pop('church_id', None)
                        request.session.pop('pending_user_id', None)
                        request.session.pop('payment_method', None)
                        
                        # Redirect to dashboard after payment and login
                        return redirect('dashboard')
                    else:
                        messages.error(request, "Could not find church record.")
                        return redirect('subscription')
                else:
                    messages.error(request, "Invalid order data.")
                    return redirect('subscription')
            else:
                messages.error(request, f"Payment capture failed: {capture_result['error']}")
                return redirect('subscription')
        else:
            messages.error(request, f"Failed to get order details: {order_result['error']}")
            return redirect('subscription')
            
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('subscription')

def paypal_cancel(request):
    """
    Handle cancelled PayPal subscription
    """
    # Clean up any pending data
    church_id = request.session.get('church_id')
    if church_id:
        try:
            church = Church.objects.get(id=church_id)
            church.delete()
        except Church.DoesNotExist:
            pass
    
    # Clean up pending user account
    pending_user_id = request.session.get('pending_user_id')
    if pending_user_id:
        try:
            user = User.objects.get(id=pending_user_id)
            user.delete()
        except User.DoesNotExist:
            pass
    
    # Clear session data
    request.session.pop('selected_package', None)
    request.session.pop('package_price', None)
    request.session.pop('paypal_plan_id', None)
    request.session.pop('pending_subscription_id', None)
    request.session.pop('church_id', None)
    request.session.pop('pending_user_id', None)
    
    messages.warning(request, "Subscription cancelled. You can try again anytime.")
    return redirect('subscription')

@csrf_exempt
@require_http_methods(["POST"])
def paypal_webhook(request):
    """
    Handle PayPal webhook events.
    The webhook URL registered in the PayPal dashboard MUST include a secret
    token query parameter, e.g.:
      https://yoursite.com/finances/paypal/webhook/?token=<PAYPAL_WEBHOOK_TOKEN>
    Set PAYPAL_WEBHOOK_TOKEN in Railway environment variables.
    """
    import logging
    webhook_logger = logging.getLogger(__name__)

    # --- Token verification ---
    expected_token = getattr(settings, 'PAYPAL_WEBHOOK_TOKEN', '')
    if expected_token:
        received_token = request.GET.get('token', '')
        if not received_token or received_token != expected_token:
            webhook_logger.warning(
                f'PayPal webhook rejected: invalid token from {request.META.get("REMOTE_ADDR")}'
            )
            return HttpResponse('Forbidden', status=403)
    else:
        webhook_logger.warning(
            'PAYPAL_WEBHOOK_TOKEN is not set. Webhook received without token verification. '
            'Set PAYPAL_WEBHOOK_TOKEN in Railway env vars and update your PayPal webhook URL.'
        )

    try:
        webhook_data = json.loads(request.body)
        paypal_service = get_paypal_service()
        result = paypal_service.process_webhook(webhook_data)

        if result['success']:
            return HttpResponse("OK", status=200)
        else:
            return HttpResponse("Error processing webhook", status=400)

    except Exception as e:
        return HttpResponse(f"Error: {str(e)}", status=500)


# ---------------------------------------------------------------------------
# STRIPE VIEWS
# ---------------------------------------------------------------------------

@login_required
def stripe_payment_direct(request):
    """
    Initiates Stripe Checkout for an existing church account that still needs to pay.
    """
    try:
        church_member = ChurchMember.objects.get(user=request.user)
        church = church_member.church
    except ChurchMember.DoesNotExist:
        messages.info(request, "Please complete your church registration first.")
        return redirect('register')

    success_url = request.build_absolute_uri('/finances/stripe/success/')
    cancel_url = request.build_absolute_uri('/finances/stripe/cancel/')

    try:
        session = create_checkout_session(
            church_id=church.id,
            user_id=request.user.id,
            email=request.user.email,
            church_name=church.name,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return redirect(session.url, permanent=False)
    except Exception as e:
        messages.error(request, f"Could not start payment: {str(e)}")
        return redirect('dashboard')


@ensure_csrf_cookie
def create_stripe_checkout(request):
    """
    Processes the registration form and creates a Stripe Checkout Session.
    The user and church are created as inactive; they are activated in stripe_success.
    """
    if request.method != "POST":
        selected_package = request.session.get('selected_package')
        if not selected_package:
            messages.error(request, "Please select a subscription package first.")
            return redirect('subscription')
        return render(request, 'church_finances/stripe_checkout_form.html', {
            'selected_package': selected_package,
            'package_price': request.session.get('package_price', '120'),
        })

    try:
        payment_method = request.POST.get('payment_method', 'stripe')
        first_name    = request.POST.get('first_name', '')
        last_name     = request.POST.get('last_name', '')
        email         = request.POST.get('email', '').strip().lower()
        phone_number  = request.POST.get('phone_number', '')
        role          = request.POST.get('role', '')
        username      = request.POST.get('username', '').strip()
        password      = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        church_name   = request.POST.get('church_name', '')
        church_address = request.POST.get('church_address', '')
        church_phone  = request.POST.get('church_phone', '')
        church_email  = request.POST.get('church_email', '')
        church_website = request.POST.get('church_website', '')

        # -- Validation --
        if not all([username, password, email, first_name, last_name, role, church_name, church_address]):
            messages.error(request, "All required fields must be filled out.")
            return redirect('paypal_subscription_form')

        valid_roles = ['admin', 'pastor', 'bishop', 'assistant_pastor', 'treasurer', 'deacon']
        if role not in valid_roles:
            messages.error(request, "Please select a valid role.")
            return redirect('paypal_subscription_form')

        if password != password_confirm:
            messages.error(request, "Passwords do not match.")
            return redirect('paypal_subscription_form')

        if User.objects.filter(username__iexact=username).exists():
            messages.error(request, "Username already exists.")
            return redirect('paypal_subscription_form')

        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, "Email already registered.")
            return redirect('paypal_subscription_form')

        selected_package = request.session.get('selected_package', 'standard')

        # -- Create user (inactive until payment confirmed) --
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            is_active=False,
        )

        # -- Create church (not approved until payment confirmed) --
        church = Church.objects.create(
            name=church_name,
            address=church_address,
            phone=church_phone,
            email=church_email,
            website=church_website,
            subscription_type=selected_package,
            subscription_status='pending',
            is_approved=False,
            payment_method='offline' if payment_method == 'offline' else 'stripe',
        )
        church_logo = request.FILES.get('church_logo')
        if church_logo:
            church.save_logo(church_logo)

        ChurchMember.objects.create(
            user=user,
            church=church,
            role=role,
            phone_number=phone_number,
            is_active=False,
        )

        request.session['pending_user_id'] = user.id
        request.session['church_id'] = church.id

        # -- Offline path --
        if payment_method == 'offline':
            messages.success(request, f"Registration submitted! Your account '{username}' is pending admin approval.")
            request.session.pop('selected_package', None)
            request.session.pop('package_price', None)
            return redirect('pending_approval')

        # -- Stripe path: create checkout session and redirect --
        success_url = request.build_absolute_uri('/finances/stripe/success/')
        cancel_url  = request.build_absolute_uri('/finances/stripe/cancel/')

        session = create_checkout_session(
            church_id=church.id,
            user_id=user.id,
            email=email,
            church_name=church_name,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return redirect(session.url, permanent=False)

    except Exception as e:
        print(f"create_stripe_checkout error: {e}")
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('subscription')


def stripe_success(request):
    """
    Stripe redirects here after successful payment.
    Verifies the session and activates the church account.
    """
    session_id = request.GET.get('session_id')
    if not session_id:
        messages.error(request, "Invalid payment response.")
        return redirect('subscription')

    try:
        session = retrieve_checkout_session(session_id)

        if session.payment_status not in ('paid', 'no_payment_required') and session.status != 'complete':
            messages.error(request, "Payment not completed. Please try again.")
            return redirect('subscription')

        church_id = session.metadata.get('church_id')
        user_id   = session.metadata.get('user_id')

        if not church_id or not user_id:
            messages.error(request, "Could not find account details. Please contact support.")
            return redirect('subscription')

        church = Church.objects.get(id=church_id)
        user   = User.objects.get(id=user_id)

        # Activate church
        church.is_approved = True
        church.subscription_status = 'active'
        church.payment_method = 'stripe'
        church.subscription_start_date = timezone.now()
        church.subscription_end_date = timezone.now() + timedelta(days=365)
        church.is_trial_active = False
        church.save()

        # Activate user and church member
        user.is_active = True
        user.save()

        church_member = ChurchMember.objects.filter(user=user, church=church).first()
        if church_member:
            church_member.is_active = True
            church_member.save()

        # Log the user in
        login(request, user)

        # Clear session
        for key in ['selected_package', 'package_price', 'pending_user_id', 'church_id', 'payment_method']:
            request.session.pop(key, None)

        messages.success(request, f"Payment successful! Welcome {user.first_name}! Your Church Books account is now active.")
        return redirect('dashboard')

    except Church.DoesNotExist:
        messages.error(request, "Church account not found. Please contact support.")
        return redirect('subscription')
    except User.DoesNotExist:
        messages.error(request, "User account not found. Please contact support.")
        return redirect('subscription')
    except Exception as e:
        messages.error(request, f"An error occurred verifying your payment: {str(e)}")
        return redirect('subscription')


def stripe_cancel(request):
    """
    Stripe redirects here when the user cancels the checkout.
    If it was a new registration (inactive user), clean up the pending records.
    If it was an existing trial-expired user, just send them back to the payment page.
    """
    user_id   = request.session.get('pending_user_id')
    church_id = request.session.get('church_id')

    # Only delete if this was a brand-new (inactive) pending registration
    if user_id and church_id:
        try:
            pending_user = User.objects.get(id=user_id, is_active=False)
            Church.objects.filter(id=church_id, subscription_status='pending').delete()
            pending_user.delete()
        except User.DoesNotExist:
            pass  # Active user — don't delete

    for key in ['selected_package', 'package_price', 'pending_user_id', 'church_id', 'payment_method']:
        request.session.pop(key, None)

    # If user is logged in and their trial is expired, send back to payment page
    if request.user.is_authenticated:
        try:
            member = ChurchMember.objects.get(user=request.user)
            if member.church.is_trial_expired and member.church.subscription_status != 'active':
                messages.info(request, "Payment was cancelled. You can try again below.")
                return redirect('trial_expired_payment')
        except ChurchMember.DoesNotExist:
            pass

    messages.info(request, "Payment was cancelled. You can try again when you're ready.")
    return redirect('subscription')

    messages.warning(request, "Payment cancelled. You can try again anytime.")
    return redirect('subscription')


@require_http_methods(["POST"])
def stripe_webhook(request):
    """
    Handles Stripe webhook events for reliable payment confirmation.
    Set the webhook URL in the Stripe dashboard to:
    https://churchbooksmanagement.com/finances/stripe/webhook/
    """
    payload    = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = construct_webhook_event(payload, sig_header)
    except stripe_lib.error.SignatureVerificationError:
        return HttpResponse("Invalid signature", status=400)
    except Exception as e:
        return HttpResponse(f"Webhook error: {str(e)}", status=400)

    # Handle subscription activated
    if event['type'] in ('checkout.session.completed', 'invoice.payment_succeeded'):
        obj = event['data']['object']
        metadata = obj.get('metadata', {})
        church_id = metadata.get('church_id')
        user_id   = metadata.get('user_id')

        if church_id:
            try:
                church = Church.objects.get(id=church_id)
                if church.subscription_status != 'active':
                    church.is_approved = True
                    church.subscription_status = 'active'
                    church.payment_method = 'stripe'
                    church.subscription_start_date = timezone.now()
                    church.subscription_end_date   = timezone.now() + timedelta(days=365)
                    church.is_trial_active = False
                    church.save()
                if user_id:
                    user = User.objects.filter(id=user_id).first()
                    if user and not user.is_active:
                        user.is_active = True
                        user.save()
                        ChurchMember.objects.filter(user=user, church=church).update(is_active=True)
            except Church.DoesNotExist:
                pass

    # Handle subscription cancelled
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        metadata = subscription.get('metadata', {})
        church_id = metadata.get('church_id')
        if church_id:
            Church.objects.filter(id=church_id).update(subscription_status='cancelled')

    return HttpResponse("OK", status=200)
