from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views import View
from django.utils import timezone
from django.contrib.auth.models import User
from datetime import timedelta
import json
from .models import Church, PayPalSubscription, ChurchMember
from .paypal_service import PayPalService

@ensure_csrf_cookie
def subscription_view(request):
    """
    Display subscription packages
    """
    context = {
        'paypal_client_id': settings.PAYPAL_CLIENT_ID,
        'standard_plan_id': settings.PAYPAL_STANDARD_PLAN_ID,
        'premium_plan_id': settings.PAYPAL_PREMIUM_PLAN_ID,
        'paypal_mode': settings.PAYPAL_MODE
    }
    return render(request, "church_finances/subscription.html", context)

def subscription_select(request):
    """
    Handle subscription package selection - redirect to PayPal
    """
    if request.method == "POST":
        package = request.POST.get('package')
        if package in ['standard', 'premium']:
            request.session['selected_package'] = package
            request.session['package_price'] = '10000' if package == 'standard' else '15000'
            
            # Store package selection and redirect to PayPal payment
            plan_id = settings.PAYPAL_STANDARD_PLAN_ID if package == 'standard' else settings.PAYPAL_PREMIUM_PLAN_ID
            request.session['paypal_plan_id'] = plan_id
            
            messages.success(request, f"You have selected the {package.title()} package. You will now be redirected to PayPal for payment.")
            return redirect('paypal_create_subscription')
        else:
            messages.error(request, "Invalid package selection.")
    return redirect('subscription')

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
            if not username or not password or not email:
                messages.error(request, "Username, password, and email are required.")
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
            
            # Create user account (inactive until payment is confirmed)
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_active=False  # Activate after payment confirmation
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
                is_approved=False
            )
            
            print(f"DEBUG: Church created successfully with ID: {church.id}")
            
            # Create ChurchMember relationship
            church_member = ChurchMember.objects.create(
                user=user,
                church=church,
                role='admin'  # First user is the admin
            )
            print(f"DEBUG: ChurchMember created successfully with ID: {church_member.id}")
            
            # Store user ID with church for later activation
            request.session['pending_user_id'] = user.id
            request.session['church_id'] = church.id
            
            # Check if this is offline payment
            if payment_method == 'offline':
                # For offline payment, create records and redirect to pending approval
                messages.success(request, f"Registration submitted successfully! Your church account '{church_name}' and user login '{username}' are pending admin approval and offline payment confirmation.")
                
                # Clear session data
                request.session.pop('selected_package', None)
                request.session.pop('package_price', None)
                request.session.pop('paypal_plan_id', None)
                
                # Redirect to pending approval page
                return redirect('pending_approval')
            
            # Create PayPal subscription for online payment
            try:
                paypal_service = PayPalService()
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
        paypal_service = PayPalService()
        
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
                        
                        # Approve the church immediately after successful payment
                        church.is_approved = True
                        church.subscription_status = 'active'
                        church.paypal_subscription_id = token
                        church.subscription_start_date = timezone.now()
                        church.subscription_end_date = timezone.now() + timedelta(days=365)
                        church.save()
                        
                        # Activate the user account if it exists
                        pending_user_id = request.session.get('pending_user_id')
                        if pending_user_id:
                            try:
                                user = User.objects.get(id=pending_user_id)
                                user.is_active = True
                                user.save()
                                messages.success(request, f"Payment successful! Your church account and user login '{user.username}' have been approved and activated.")
                            except User.DoesNotExist:
                                messages.success(request, "Payment successful! Your church account has been approved and activated.")
                        else:
                            messages.success(request, "Payment successful! Your church account has been approved and activated.")
                        
                        # Clear session data
                        request.session.pop('selected_package', None)
                        request.session.pop('package_price', None)
                        request.session.pop('paypal_plan_id', None)
                        request.session.pop('pending_subscription_id', None)
                        request.session.pop('church_id', None)
                        request.session.pop('pending_user_id', None)
                        
                        # Redirect to dashboard after payment
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
    request.session.pop('pending_subscription_id', None)
    request.session.pop('church_id', None)
    
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
        paypal_service = PayPalService()
        result = paypal_service.process_webhook(webhook_data)
        
        if result['success']:
            return HttpResponse("OK", status=200)
        else:
            return HttpResponse("Error processing webhook", status=400)
            
    except Exception as e:
        return HttpResponse(f"Error: {str(e)}", status=500)
