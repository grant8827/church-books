from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
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
from .models import Church, PayPalSubscription, ChurchMember
from .paypal_service import PayPalService
from .stripe_service import create_checkout_session, retrieve_checkout_session, construct_webhook_event
from django.utils.decorators import method_decorator
from django.views import View
from django.utils import timezone
from django.contrib.auth.models import User
from datetime import timedelta
import json
from .models import Church, PayPalSubscription, ChurchMember
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
    context = {
        'paypal_client_id': getattr(settings, 'PAYPAL_CLIENT_ID', ''),
        'standard_plan_id': getattr(settings, 'PAYPAL_STANDARD_PLAN_ID', ''),
        'paypal_mode': getattr(settings, 'PAYPAL_MODE', 'sandbox'),
        'package_price': 120
    }
    
    # Add trial information if user is authenticated
    if request.user.is_authenticated:
        try:
            from .models import ChurchMember
            member = ChurchMember.objects.filter(user=request.user).first()
            if member and member.church:
                context.update({
                    'church': member.church,
                    'is_trial_active': member.church.is_trial_active,
                    'trial_days_remaining': member.church.trial_days_remaining,
                    'is_trial_expired': member.church.is_trial_expired,
                    'trial_end_date': member.church.trial_end_date,
                })
        except Exception as e:
            # Log error but don't break the view
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting trial info for user {request.user}: {e}")
    
    return render(request, "church_finances/subscription.html", context)

def subscription_select(request):
    """
    Handle subscription package selection - redirect to payment selection
    """
    if request.method == "POST":
        package = request.POST.get('package', 'standard')  # Default to standard
        if package == 'standard':
            request.session['selected_package'] = package
            request.session['package_price'] = '120'
            
            # Store package selection and redirect to payment selection
            plan_id = getattr(settings, 'PAYPAL_STANDARD_PLAN_ID', '')
            request.session['paypal_plan_id'] = plan_id
            
            messages.success(request, "You have selected Church Books. Please choose your payment method.")
            return redirect('payment_selection')
        else:
            messages.error(request, "Invalid package selection.")
    return redirect('subscription')

@ensure_csrf_cookie
def payment_selection_view(request):
    """
    Show payment method selection (PayPal online or offline)
    """
    if request.method == "POST":
        payment_method = request.POST.get('payment_method', '')
        
        if payment_method in ['stripe', 'offline', 'bank_transfer']:
            # Store payment method in session
            request.session['payment_method'] = payment_method
            
            # For Stripe payment - redirect to registration (which will then redirect to Stripe Checkout)
            if payment_method == 'stripe':
                request.session['selected_package'] = 'standard'
                request.session['package_price'] = '120'
                
                # Check if user is logged in and has church account
                if request.user.is_authenticated:
                    try:
                        church_member = ChurchMember.objects.get(user=request.user)
                        # User already has account and church - go directly to Stripe
                        messages.success(request, "Proceeding to Stripe payment.")
                        return redirect('stripe_payment_direct')
                    except ChurchMember.DoesNotExist:
                        # User logged in but no church - go to registration first
                        messages.success(request, "Please complete your registration to proceed with payment.")
                        return redirect('registration_form')
                else:
                    # User not logged in - go to registration
                    messages.success(request, "Please register to proceed with Stripe payment.")
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
        # Get payment method from session
        payment_method = request.session.get('payment_method', '')
        
        if not payment_method:
            messages.error(request, "Please select a payment method first.")
            return redirect('payment_selection')
        
        try:
            # Get form data
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
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
            
            # Check if username already exists
            if User.objects.filter(username=username).exists():
                messages.error(request, "Username already exists. Please choose a different username.")
                return render(request, 'church_finances/registration_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                    'payment_method': payment_method,
                })
            
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                messages.error(request, "An account with this email already exists.")
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
            
            # Use database transaction to ensure data consistency
            with transaction.atomic():
                # Stripe: user inactive until payment confirmed
                # Offline: user active, church pending admin approval
                is_user_active   = payment_method != 'stripe'
                is_church_approved = False
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
                church = Church.objects.create(
                    name=church_name,
                    address=church_address,
                    phone=church_phone,
                    email=church_email,
                    website=church_website,
                    subscription_type=selected_package,
                    subscription_status=church_status,
                    is_approved=is_church_approved,
                    payment_method=payment_method
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
            if payment_method == 'offline':
                # For offline payment, create records - admin approval needed
                messages.success(request, f"Registration successful! Your account '{username}' is pending admin approval. You will receive payment instructions once approved.")
                
                request.session.pop('selected_package', None)
                request.session.pop('package_price', None)
                request.session.pop('payment_method', None)
                
                return redirect('pending_approval')
            
            # Handle Stripe payment — redirect to Stripe Checkout
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
    
    if not payment_method:
        messages.error(request, "Please select a payment method first.")
        return redirect('payment_selection')
    
    context = {
        'selected_package': selected_package,
        'package_price': request.session.get('package_price'),
        'payment_method': payment_method,
    }
    return render(request, 'church_finances/registration_form.html', context)

def paypal_payment_direct(request):
    """
    Direct PayPal payment - handles both existing users and new users
    """
    # Set up payment context
    request.session['selected_package'] = 'standard'
    request.session['package_price'] = '120'
    request.session['payment_method'] = 'paypal'
    
    # Check if user is authenticated
    if not request.user.is_authenticated:
        # Store the current path to redirect back after login/registration
        request.session['next_url'] = request.get_full_path()
        messages.info(request, "Please login or register to proceed with PayPal payment. New users get a 30-day free trial!")
        return redirect('login')
    
    try:
        # Check if user has a church membership
        church_member = ChurchMember.objects.get(user=request.user)
        church = church_member.church
        
        if request.method == "GET":
            context = {
                'selected_package': 'standard',
                'package_price': 120,
                'church_name': church.name,
                'user_email': request.user.email,
                'user_first_name': request.user.first_name,
                'user_last_name': request.user.last_name,
                'is_existing_user': True,
            }
            return render(request, 'church_finances/paypal_subscription_form.html', context)
            
        elif request.method == "POST":
            # Handle PayPal payment for existing user
            return create_paypal_subscription(request)
            
    except ChurchMember.DoesNotExist:
        # User is authenticated but doesn't have a church account yet
        # Redirect to registration to complete setup, then come back to PayPal
        request.session['next_url'] = request.get_full_path()
        messages.info(request, "Please complete your church registration to get your 30-day free trial, then proceed with payment.")
        return redirect('register')

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
            email = request.POST.get('email', '')
            phone_number = request.POST.get('phone_number', '')
            role = request.POST.get('role', '')
            username = request.POST.get('username', '')
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
            
            # Check if username already exists
            if User.objects.filter(username=username).exists():
                messages.error(request, "Username already exists. Please choose a different username.")
                return render(request, 'church_finances/paypal_subscription_form.html', {
                    'selected_package': request.session.get('selected_package'),
                    'package_price': request.session.get('package_price'),
                })
            
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                messages.error(request, "An account with this email already exists.")
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
            church = Church.objects.create(
                name=church_name,
                address=church_address,
                phone=church_phone,
                email=church_email,
                website=church_website,
                subscription_type=selected_package,
                subscription_status='pending',
                is_approved=False,
                payment_method=('offline' if payment_method == 'offline' else 'paypal')
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
                
                result = paypal_service.create_subscription(plan_identifier, payer_info, church.id)
                
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
    Handle PayPal webhook events
    """
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
        email         = request.POST.get('email', '')
        phone_number  = request.POST.get('phone_number', '')
        role          = request.POST.get('role', '')
        username      = request.POST.get('username', '')
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

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists. Please choose a different username.")
            return redirect('paypal_subscription_form')

        if User.objects.filter(email=email).exists():
            messages.error(request, "An account with this email already exists.")
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
    Cleans up the pending church and user records.
    """
    church_id = request.session.get('church_id')
    user_id   = request.session.get('pending_user_id')

    if church_id:
        Church.objects.filter(id=church_id, subscription_status='pending').delete()
    if user_id:
        User.objects.filter(id=user_id, is_active=False).delete()

    for key in ['selected_package', 'package_price', 'pending_user_id', 'church_id', 'payment_method']:
        request.session.pop(key, None)

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
