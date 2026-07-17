from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, logout
from django.contrib.auth.models import User, Group
from django.contrib.messages import success, error, info, warning
from django.db.models import Sum, Q, Count
from decimal import Decimal, InvalidOperation
from django.http import HttpResponseNotAllowed, HttpResponse, JsonResponse
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from functools import wraps
import random
import string
import hashlib
import json
import logging
import time
from datetime import timedelta
from .models import Transaction, Church, ChurchMember, Member, Contribution, Child, ChildAttendance, MemberAttendance, BabyChristening, CertificateTemplate, EmailOTP, SubscriptionPlan, DeletedAccount, ManagedPaymentGateway, WiPayDonationAttempt
from .forms import (
    CustomUserCreationForm, TransactionForm, ChurchRegistrationForm,
    ChurchMemberForm, MemberForm, ContributionForm, DashboardUserRegistrationForm,
    PersonalProfileForm, ChurchDetailForm, WiPaySetupForm
)
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import timezone
from datetime import datetime, date
from calendar import monthrange
from collections import defaultdict
import io
import uuid
import stripe as stripe_lib
from django.template.loader import get_template
from django.views.decorators.http import require_POST, require_http_methods
from . import stripe_service
from .paypal_service import PayPalService


# WeasyPrint PDF generation
try:
    from weasyprint import HTML as WeasyHTML, CSS as WeasyCSS
    PDF_AVAILABLE = True
    PDF_IMPORT_ERROR = None
except Exception as exc:
    # WeasyPrint can fail with OSError when native GTK/Pango libs are missing.
    WeasyHTML = None
    WeasyCSS = None
    PDF_AVAILABLE = False
    PDF_IMPORT_ERROR = str(exc)


def render_to_pdf(request, template_name, context, filename='document.pdf'):
    """Render a Django template to a PDF response using WeasyPrint."""
    if not PDF_AVAILABLE or WeasyHTML is None:
        return HttpResponse(
            "PDF generation is unavailable on this server. Missing WeasyPrint system dependencies.",
            status=503,
            content_type='text/plain',
        )

    html_string = render(request, template_name, context).content.decode('utf-8')
    base_url = request.build_absolute_uri('/')
    pdf_bytes = WeasyHTML(string=html_string, base_url=base_url).write_pdf()
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


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
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        church_name = request.POST.get('church_name', '')
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()

        email_subject = f"Contact Form: {subject or 'New Message'}"
        email_body = (
            "A new message was submitted through the Church Books contact form.\n\n"
            f"Name: {name}\n"
            f"Email: {email}\n"
            f"Church Name: {church_name or 'Not provided'}\n"
            f"Subject: {subject or 'Not provided'}\n\n"
            "Message:\n"
            f"{message}\n"
        )
        
        try:
            contact_email = EmailMessage(
                subject=email_subject,
                body=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=['info@churchbooksmanagement.com'],
                reply_to=[email] if email else None,
            )
            contact_email.send(fail_silently=False)
        except Exception:
            error(request, "Sorry, we couldn't send your message right now. Please email info@churchbooksmanagement.com directly.")
            return redirect('contact')

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


def _ensure_donation_account_number(church):
    if church.donation_account_number:
        return church.donation_account_number

    generated = f"CB{church.id:06d}"
    if Church.objects.exclude(pk=church.pk).filter(donation_account_number=generated).exists():
        generated = f"CB{church.id:06d}{random.randint(100, 999)}"
    church.donation_account_number = generated
    church.save(update_fields=['donation_account_number', 'updated_at'])
    return generated


def get_wipay_endpoint(country_code):
    endpoints = {
        'TT': 'https://tt.wipayfinancial.com/plugins/payments/request',
        'JM': 'https://jm.wipayfinancial.com/plugins/payments/request',
        'BB': 'https://bb.wipayfinancial.com/plugins/payments/request',
        'GY': 'https://gy.wipayfinancial.com/plugins/payments/request',
    }
    return endpoints.get(country_code, 'https://tt.wipayfinancial.com/plugins/payments/request')


def _require_church_admin(request):
    """Return the requesting user's church if they administer it, else raise PermissionDenied."""
    church_member = request.user.churchmember_set.select_related('church').first()
    church = church_member.church if church_member else None
    if not church:
        raise PermissionDenied("Your church account is pending approval.")
    is_church_admin = (
        church_member is not None and church_member.role == 'admin'
    ) or (
        getattr(church, 'registered_by_id', None) == request.user.pk
    )
    if not is_church_admin:
        raise PermissionDenied("Only church admins can manage payment portals.")
    return church


def _gateway_has_saved_connection(gateway):
    """Return whether switching providers could overwrite saved gateway state."""
    return bool(
        gateway.is_active
        or gateway.connected_account_id
        or gateway.paypal_tracking_id
        or gateway.wipay_account_id
        or gateway.wipay_country
    )


def _block_gateway_switch(request, gateway, requested_provider):
    """Require an explicit disconnect before changing payment providers."""
    if gateway.provider != requested_provider and _gateway_has_saved_connection(gateway):
        warning(
            request,
            f'Disconnect {gateway.get_provider_display()} before connecting another payment portal.'
        )
        return True
    return False


def _stripe_configuration_error():
    """Return a safe configuration error, or an empty string when usable."""
    secret_key = (getattr(settings, 'STRIPE_SECRET_KEY', '') or '').strip()
    publishable_key = (getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '') or '').strip()
    if not secret_key:
        return 'STRIPE_SECRET_KEY is not configured.'
    if not secret_key.startswith(('sk_test_', 'sk_live_')):
        return 'STRIPE_SECRET_KEY is not a standard Stripe secret key.'
    if publishable_key:
        secret_mode = 'live' if secret_key.startswith('sk_live_') else 'test'
        expected_prefix = f'pk_{secret_mode}_'
        if not publishable_key.startswith(expected_prefix):
            return 'Stripe publishable and secret keys use different modes.'
    return ''


def _log_stripe_error(stage, exc, church_id=None):
    """Log actionable Stripe diagnostics without logging keys or payment data."""
    request_id = getattr(exc, 'request_id', None)
    if not request_id:
        headers = getattr(exc, 'headers', None) or {}
        request_id = headers.get('request-id') or headers.get('Request-Id')
    logging.getLogger(__name__).error(
        'Stripe %s failed: church_id=%s error_type=%s code=%s http_status=%s request_id=%s message=%s',
        stage,
        church_id,
        type(exc).__name__,
        getattr(exc, 'code', None),
        getattr(exc, 'http_status', None),
        request_id,
        str(exc),
        exc_info=True,
    )
    return request_id


def _configured_url(request, setting_name, fallback_url):
    """Use an explicitly configured absolute URL, otherwise use the request host."""
    configured = (getattr(settings, setting_name, '') or '').strip()
    return configured or request.build_absolute_uri(fallback_url)


@login_required
def payment_portals_view(request):
    church_member = request.user.churchmember_set.select_related('church').first()
    church = church_member.church if church_member else None
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    is_church_admin = (
        church_member is not None and church_member.role == 'admin'
    ) or (
        getattr(church, 'registered_by_id', None) == request.user.pk
    )
    if not is_church_admin:
        raise PermissionDenied("Only church admins can manage payment portals.")

    _ensure_donation_account_number(church)
    gateway, _ = ManagedPaymentGateway.objects.get_or_create(church=church, defaults={'provider': 'wipay'})

    if request.method == 'POST':
        if _block_gateway_switch(request, gateway, 'wipay'):
            return redirect('payment_portals')
        form = WiPaySetupForm(request.POST, instance=gateway)
        if form.is_valid():
            gateway_obj = form.save(commit=False)
            gateway_obj.provider = 'wipay'
            gateway_obj.is_active = True
            gateway_obj.save()
            success(request, 'Payment portal settings saved. WiPay is now active for donor payments.')
            return redirect('payment_portals')
    else:
        form = WiPaySetupForm(instance=gateway)

    return render(request, 'church_finances/payment_portals.html', {
        'church': church,
        'gateway': gateway,
        'form': form,
        'has_saved_gateway': _gateway_has_saved_connection(gateway),
        'stripe_connected': gateway.provider == 'stripe' and gateway.is_active,
        'paypal_connected': gateway.provider == 'paypal' and gateway.is_active,
    })


@login_required
@require_POST
def disconnect_payment_portal(request):
    """Deactivate the church's gateway and remove its saved connection identifiers."""
    church = _require_church_admin(request)
    gateway = getattr(church, 'gateway', None)
    if not gateway or not _gateway_has_saved_connection(gateway):
        info(request, 'No payment portal is currently connected.')
        return redirect('payment_portals')

    provider_label = gateway.get_provider_display()
    gateway.is_active = False
    gateway.connected_account_id = None
    gateway.paypal_tracking_id = None
    gateway.wipay_account_id = None
    gateway.wipay_country = None
    gateway.wipay_account_type = 'business'
    gateway.wipay_api_key_encrypted = ''
    gateway.save(update_fields=[
        'is_active', 'connected_account_id', 'paypal_tracking_id',
        'wipay_account_id', 'wipay_country', 'wipay_account_type',
        'wipay_api_key_encrypted', 'updated_at',
    ])
    logging.getLogger(__name__).info(
        'Payment portal disconnected: church_id=%s provider=%s user_id=%s',
        church.pk, gateway.provider, request.user.pk,
    )
    success(request, f'{provider_label} has been disconnected. You can now connect another payment portal.')
    return redirect('payment_portals')


# ---------------------------------------------------------------------------
# Stripe Connect (donor-tithing): church onboarding
# ---------------------------------------------------------------------------

@login_required
def initiate_stripe_connect(request):
    """Admin clicks 'Connect with Stripe' — create/reuse a Connect account and send them to onboard."""
    church = _require_church_admin(request)
    gateway, _ = ManagedPaymentGateway.objects.get_or_create(church=church, defaults={'provider': 'stripe'})
    if _block_gateway_switch(request, gateway, 'stripe'):
        return redirect('payment_portals')

    config_error = _stripe_configuration_error()
    if config_error:
        logging.getLogger(__name__).error('Stripe configuration invalid: %s', config_error)
        error(request, 'Stripe is not configured correctly. Please contact support.')
        return redirect('payment_portals')

    if not gateway.connected_account_id:
        try:
            account = stripe_service.create_connect_account(
                email=request.user.email,
                country=getattr(settings, 'STRIPE_CONNECTED_ACCOUNT_COUNTRY', '') or None,
            )
        except Exception as exc:
            request_id = _log_stripe_error('connected account creation', exc, church.pk)
            reference = f' Reference: {request_id}' if request_id else ''
            error(request, f'Unable to start Stripe onboarding right now.{reference}')
            return redirect('payment_portals')
        gateway.connected_account_id = account.id
        gateway.provider = 'stripe'
        gateway.save(update_fields=['connected_account_id', 'provider', 'updated_at'])

    try:
        account_link = stripe_service.create_account_link(
            account_id=gateway.connected_account_id,
            refresh_url=_configured_url(request, 'STRIPE_CONNECT_REFRESH_URL', reverse('stripe_connect_refresh')),
            return_url=_configured_url(request, 'STRIPE_CONNECT_RETURN_URL', reverse('stripe_connect_callback')),
        )
    except Exception as exc:
        request_id = _log_stripe_error('account link creation', exc, church.pk)
        reference = f' Reference: {request_id}' if request_id else ''
        error(request, f'Unable to generate the Stripe onboarding link.{reference}')
        return redirect('payment_portals')

    return redirect(account_link.url)


@login_required
def stripe_connect_refresh(request):
    """Stripe sends the admin here if their onboarding link expired — just start again."""
    return redirect('initiate_stripe_connect')


@login_required
def stripe_connect_callback(request):
    """Admin returns here after completing (or abandoning) Stripe onboarding."""
    church = _require_church_admin(request)
    gateway = getattr(church, 'gateway', None)
    if not gateway or not gateway.connected_account_id:
        error(request, 'No Stripe onboarding in progress was found.')
        return redirect('payment_portals')

    try:
        account = stripe_service.retrieve_connect_account(gateway.connected_account_id)
    except Exception as exc:
        request_id = _log_stripe_error('connected account verification', exc, church.pk)
        reference = f' Reference: {request_id}' if request_id else ''
        error(request, f'Unable to verify your Stripe account status.{reference}')
        return redirect('payment_portals')

    if account.details_submitted and account.charges_enabled:
        gateway.provider = 'stripe'
        gateway.is_active = True
        gateway.save(update_fields=['provider', 'is_active', 'updated_at'])
        success(request, 'Stripe is now connected and active for donor payments.')
    else:
        warning(request, 'Stripe onboarding is not finished yet — please complete the remaining steps.')

    return redirect('payment_portals')


# ---------------------------------------------------------------------------
# PayPal Partner Referral / Multiparty (donor-tithing): church onboarding
# ---------------------------------------------------------------------------

@login_required
def initiate_paypal_connect(request):
    """Admin clicks 'Connect with PayPal' — start Partner Referral onboarding."""
    church = _require_church_admin(request)
    gateway, _ = ManagedPaymentGateway.objects.get_or_create(church=church, defaults={'provider': 'paypal'})
    if _block_gateway_switch(request, gateway, 'paypal'):
        return redirect('payment_portals')

    tracking_id = f"church-{church.id}-{uuid.uuid4().hex[:12]}"
    try:
        paypal_service = PayPalService()
        referral = paypal_service.create_partner_referral(
            tracking_id=tracking_id,
            email=request.user.email,
            return_url=request.build_absolute_uri(reverse('paypal_connect_callback')),
        )
    except Exception as exc:
        detail = str(exc)
        if 'NOT_AUTHORIZED' in detail or 'insufficient permissions' in detail.lower():
            error(
                request,
                'PayPal onboarding is blocked: this PayPal app does not have Partner Referrals permissions in live mode yet.'
            )
        else:
            error(request, f'Unable to start PayPal onboarding: {detail}')
        logging.getLogger(__name__).error('PayPal partner referral start failed: %s', detail, exc_info=True)
        return redirect('payment_portals')

    action_url = next((l['href'] for l in referral.get('links', []) if l.get('rel') == 'action_url'), None)
    if not action_url:
        error(request, 'PayPal did not return an onboarding link. Please try again later.')
        return redirect('payment_portals')

    gateway.paypal_tracking_id = tracking_id
    gateway.provider = 'paypal'
    gateway.save(update_fields=['paypal_tracking_id', 'provider', 'updated_at'])

    return redirect(action_url)


@login_required
def paypal_connect_callback(request):
    """Admin returns here after completing (or abandoning) PayPal onboarding."""
    church = _require_church_admin(request)
    gateway = getattr(church, 'gateway', None)
    if not gateway or not gateway.paypal_tracking_id:
        error(request, 'No PayPal onboarding in progress was found.')
        return redirect('payment_portals')

    try:
        paypal_service = PayPalService()
        integration = paypal_service.get_merchant_integration(gateway.paypal_tracking_id)
    except Exception as exc:
        detail = str(exc)
        error(request, f'Unable to verify your PayPal account status: {detail}')
        logging.getLogger(__name__).error('PayPal merchant integration lookup failed: %s', detail, exc_info=True)
        return redirect('payment_portals')

    merchant_id = integration.get('merchant_id')
    payments_receivable = integration.get('payments_receivable', False)
    email_confirmed = integration.get('primary_email_confirmed', False)

    if merchant_id and payments_receivable and email_confirmed:
        gateway.provider = 'paypal'
        gateway.connected_account_id = merchant_id
        gateway.is_active = True
        gateway.save(update_fields=['provider', 'connected_account_id', 'is_active', 'updated_at'])
        success(request, 'PayPal is now connected and active for donor payments.')
    else:
        warning(request, 'PayPal onboarding is not finished yet — please complete the remaining steps.')

    return redirect('payment_portals')


_DONATION_CATEGORY_MAP = {
    'tithe': 'tithes',
    'offering': 'offerings',
    'special_offering': 'offerings',
    'building_fund': 'donations',
    'missions': 'other_income',
    'other': 'other_income',
}


def _record_online_donation(church, contribution_type, amount, reference_number, provider_label,
                             order_id='', donor_name='', donor_email=''):
    """
    Idempotently record an online donation (any gateway) as a Contribution + the
    matching Transaction. Safe to call more than once for the same reference_number
    (e.g. a webhook retry) — returns the existing record instead of duplicating it.
    """
    existing = Contribution.objects.filter(church=church, reference_number=reference_number).first()
    if existing is not None:
        return existing

    contribution_type = contribution_type if contribution_type in dict(Contribution.CONTRIBUTION_TYPES) else 'offering'
    notes = f"Online donation via {provider_label}."
    if order_id:
        notes += f" Order: {order_id}."
    if donor_email:
        notes += f" Donor email: {donor_email}."

    # Public portal payments do not require a member login. Attach the payment
    # only when the submitted email identifies exactly one active member in the
    # selected church; otherwise retain it safely as a guest contribution.
    member = None
    normalized_email = donor_email.strip()
    if normalized_email:
        matching_members = list(
            Member.objects.filter(
                church=church,
                is_active=True,
                email__iexact=normalized_email,
            )[:2]
        )
        if len(matching_members) == 1:
            member = matching_members[0]

    contribution = Contribution.objects.create(
        church=church,
        member=member,
        date=timezone.now().date(),
        contribution_type=contribution_type,
        amount=amount,
        payment_method='cbm_online',
        contributor_name=donor_name,
        reference_number=reference_number,
        notes=notes.strip(),
        recorded_by=None,
    )
    Transaction.objects.create(
        church=church,
        date=contribution.date,
        type='income',
        category=_DONATION_CATEGORY_MAP.get(contribution_type, 'other_income'),
        amount=contribution.amount,
        description=f"Online donation via {provider_label} ({contribution.get_contribution_type_display()}) - Ref {reference_number}",
        recorded_by=None,
    )
    return contribution


def donor_payment_portal(request):
    contribution_types = Contribution.CONTRIBUTION_TYPES
    if request.method == 'GET':
        return render(request, 'church_finances/donor_payment_entry.html', {
            'contribution_types': contribution_types,
        })

    account_num = (request.POST.get('church_account_number') or '').strip().upper()
    amount = (request.POST.get('amount') or '').strip()
    contribution_type = (request.POST.get('contribution_type') or '').strip()
    donor_name = (request.POST.get('donor_name') or '').strip()
    donor_email = (request.POST.get('donor_email') or '').strip()

    if not account_num or not amount:
        error(request, 'Church account number and amount are required.')
        return render(request, 'church_finances/donor_payment_entry.html', {'form_data': request.POST, 'contribution_types': contribution_types})

    try:
        church = Church.objects.get(donation_account_number=account_num)
    except Church.DoesNotExist:
        error(request, 'No church was found for that account number.')
        return render(request, 'church_finances/donor_payment_entry.html', {'form_data': request.POST, 'contribution_types': contribution_types})

    try:
        amount_value = float(amount)
    except ValueError:
        error(request, 'Enter a valid amount.')
        return render(request, 'church_finances/donor_payment_entry.html', {'form_data': request.POST, 'contribution_types': contribution_types})

    if amount_value <= 0:
        error(request, 'Amount must be greater than zero.')
        return render(request, 'church_finances/donor_payment_entry.html', {'form_data': request.POST, 'contribution_types': contribution_types})

    allowed_types = {choice[0] for choice in Contribution.CONTRIBUTION_TYPES}
    if contribution_type not in allowed_types:
        contribution_type = 'offering'

    gateway = getattr(church, 'gateway', None)
    if not gateway or not gateway.is_active:
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'This church has not activated online payment portals yet.',
        })

    if gateway.provider == 'wipay':
        endpoint_url = get_wipay_endpoint(gateway.wipay_country)
        currency_mapping = {'JM': 'JMD', 'TT': 'TTD', 'BB': 'BBD', 'GY': 'GYD'}
        currency = currency_mapping.get(gateway.wipay_country, 'USD')
        order_id = f"DONATION-{church.id}-{uuid.uuid4().hex}"

        WiPayDonationAttempt.objects.create(
            order_id=order_id,
            church=church,
            amount=Decimal(str(amount_value)).quantize(Decimal('0.01')),
            currency=currency,
            contribution_type=contribution_type,
            donor_name=donor_name,
            donor_email=donor_email,
        )

        callback_url = request.build_absolute_uri(reverse('wipay_callback'))
        # WiPay requires the optional `data` field to be a valid JSON string.
        # It returns this value unchanged on the callback.
        payload_data = json.dumps({
            'church_id': str(church.id),
            'contribution_type': contribution_type,
            'donor_name': donor_name,
            'donor_email': donor_email,
        }, separators=(',', ':'))

        wipay_payload = {
            'account_number': gateway.wipay_account_id,
            'country_code': gateway.wipay_country,
            'currency': currency,
            'environment': getattr(settings, 'WIPAY_ENVIRONMENT', 'live'),
            'fee_structure': 'customer_pay',
            'method': 'credit_card',
            'order_id': order_id,
            'origin': 'ChurchBooksManagement',
            'total': f"{amount_value:.2f}",
            'response_url': callback_url,
            'data': payload_data,
        }

        return render(request, 'church_finances/wipay_redirect.html', {
            'payload': wipay_payload,
            'endpoint': endpoint_url,
            'church': church,
        })

    elif gateway.provider == 'stripe':
        order_id = f"DONATION-{church.id}-{int(time.time())}-{random.randint(1000,9999)}"
        success_url = _configured_url(
            request, 'STRIPE_PAYMENT_SUCCESS_URL', reverse('donation_stripe_success')
        )
        if '{CHECKOUT_SESSION_ID}' not in success_url:
            separator = '&' if '?' in success_url else '?'
            success_url += f'{separator}session_id={{CHECKOUT_SESSION_ID}}'
        cancel_url = _configured_url(
            request, 'STRIPE_PAYMENT_CANCEL_URL', reverse('donor_payment_portal')
        )
        try:
            session = stripe_service.create_donation_checkout_session(
                amount_cents=int(round(amount_value * 100)),
                currency=getattr(settings, 'STRIPE_CURRENCY', 'usd'),
                church_name=church.name,
                destination_account_id=gateway.connected_account_id,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'church_account_number': church.donation_account_number,
                    'contribution_type': contribution_type,
                    'donor_name': donor_name,
                    'donor_email': donor_email,
                    'order_id': order_id,
                },
            )
        except Exception as exc:
            request_id = _log_stripe_error('donation checkout creation', exc, church.pk)
            reference = f' Reference: {request_id}' if request_id else ''
            return render(request, 'church_finances/payment_failed.html', {
                'message': f'Unable to start Stripe checkout right now.{reference}',
            })
        return redirect(session.url)

    elif gateway.provider == 'paypal':
        return_url = request.build_absolute_uri(reverse('donation_paypal_capture'))
        cancel_url = request.build_absolute_uri(reverse('donor_payment_portal'))
        try:
            paypal_service = PayPalService()
            order = paypal_service.create_donation_order(
                amount=amount_value,
                currency='USD',
                payee_merchant_id=gateway.connected_account_id,
                custom_id=f"{church.donation_account_number}:{contribution_type}",
                return_url=return_url,
                cancel_url=cancel_url,
            )
        except Exception:
            return render(request, 'church_finances/payment_failed.html', {
                'message': 'Unable to start PayPal checkout right now. Please try again later.',
            })
        approve_link = next((l['href'] for l in order.get('links', []) if l.get('rel') == 'approve'), None)
        if not approve_link:
            return render(request, 'church_finances/payment_failed.html', {
                'message': 'Unable to start PayPal checkout right now. Please try again later.',
            })
        # Stash donor-supplied details keyed by order id so the return leg (same
        # browser session) can attach them to the recorded contribution.
        request.session[f'paypal_donation_{order["id"]}'] = {
            'donor_name': donor_name,
            'donor_email': donor_email,
        }
        return redirect(approve_link)

    return render(request, 'church_finances/payment_failed.html', {
        'message': 'This church does not currently support this payment provider.',
    })


def wipay_callback(request):
    status = (request.GET.get('status') or '').lower()
    transaction_id = (request.GET.get('transaction_id') or '').strip()
    total = (request.GET.get('total') or '').strip()
    order_id = (request.GET.get('order_id') or '').strip()
    returned_hash = (request.GET.get('hash') or '').strip().lower()
    if not order_id or not transaction_id or not total:
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'The WiPay response is missing required transaction details.',
        })

    attempt = WiPayDonationAttempt.objects.select_related('church', 'contribution').filter(
        order_id=order_id,
    ).first()
    if attempt is None:
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'This payment could not be matched to a Church Books payment request.',
        })

    if status != 'success':
        if attempt.status == 'pending':
            attempt.status = 'failed'
            attempt.save(update_fields=['status', 'updated_at'])
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'Payment was not successful. Please try again.',
        })

    try:
        returned_total = Decimal(total).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'WiPay returned an invalid payment amount.',
        })

    # With fee_structure=customer_pay, WiPay may return the cardholder's
    # fee-inclusive total. The contribution amount remains the original amount
    # stored before redirect, and WiPay requires that original total for the
    # response-hash calculation.
    if returned_total != attempt.amount:
        logging.getLogger(__name__).info(
            'WiPay callback total includes an adjustment: order_id=%s requested=%s returned=%s',
            attempt.order_id, attempt.amount, returned_total,
        )

    gateway = getattr(attempt.church, 'gateway', None)
    secret = gateway.get_wipay_api_key() if gateway and gateway.provider == 'wipay' else ''
    if not secret:
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'This church has not completed verified WiPay Business Account setup.',
        })

    original_total = f"{attempt.amount:.2f}"
    generated_hash = hashlib.md5(
        f"{transaction_id}{original_total}{secret}".encode('utf-8')
    ).hexdigest()
    if generated_hash != returned_hash:
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'Payment verification failed. Please contact support if your card was charged.',
        })
    verification_method = 'wipay_hash'

    with transaction.atomic():
        attempt = WiPayDonationAttempt.objects.select_for_update().select_related('church').get(
            pk=attempt.pk,
        )
        if attempt.status == 'completed' and attempt.contribution_id:
            contribution = attempt.contribution
        else:
            transaction_in_use = WiPayDonationAttempt.objects.filter(
                transaction_id=transaction_id,
            ).exclude(pk=attempt.pk).exists()
            if transaction_in_use:
                return render(request, 'church_finances/payment_failed.html', {
                    'message': 'This WiPay transaction has already been used for another contribution.',
                })

            contribution = _record_online_donation(
                church=attempt.church,
                contribution_type=attempt.contribution_type,
                amount=attempt.amount,
                reference_number=transaction_id,
                provider_label='WiPay',
                order_id=attempt.order_id,
                donor_name=attempt.donor_name,
                donor_email=attempt.donor_email,
            )
            attempt.status = 'completed'
            attempt.transaction_id = transaction_id
            attempt.verification_method = verification_method
            attempt.contribution = contribution
            attempt.completed_at = timezone.now()
            attempt.save(update_fields=[
                'status', 'transaction_id', 'verification_method', 'contribution',
                'completed_at', 'updated_at',
            ])

    return render(request, 'church_finances/payment_success.html', {
        'church': attempt.church,
        'total': attempt.amount,
        'transaction_id': transaction_id,
        'order_id': order_id,
        'contribution': contribution,
    })


def donation_stripe_success(request):
    """Donor lands here immediately after a successful Stripe Checkout redirect."""
    session_id = request.GET.get('session_id', '')
    if not session_id:
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'Missing payment session reference.',
        })

    try:
        session = stripe_service.retrieve_checkout_session(session_id)
    except Exception as exc:
        request_id = _log_stripe_error('checkout session retrieval', exc)
        reference = f' Reference: {request_id}' if request_id else ''
        return render(request, 'church_finances/payment_failed.html', {
            'message': f'Unable to verify your payment.{reference} Please contact support if you were charged.',
        })

    if session.payment_status != 'paid':
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'Payment was not completed.',
        })

    metadata = session.metadata or {}
    church_account_number = metadata.get('church_account_number', '')
    church = get_object_or_404(Church, donation_account_number=church_account_number)

    contribution = _record_online_donation(
        church=church,
        contribution_type=metadata.get('contribution_type', 'offering'),
        amount=Decimal(session.amount_total) / 100,
        reference_number=session.payment_intent or session_id,
        provider_label='Stripe',
        order_id=metadata.get('order_id', ''),
        donor_name=metadata.get('donor_name', ''),
        donor_email=metadata.get('donor_email', ''),
    )

    return render(request, 'church_finances/payment_success.html', {
        'church': church,
        'total': f"{contribution.amount:.2f}",
        'transaction_id': session.payment_intent or session_id,
        'order_id': metadata.get('order_id', ''),
        'contribution': contribution,
    })


@csrf_exempt
@require_http_methods(["POST"])
def donation_stripe_webhook(request):
    """
    Authoritative record-keeping path for Stripe donations — the donor-facing
    success view above records it too, but this is idempotent so whichever
    fires first wins and the other is a no-op.
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe_service.construct_webhook_event(
            payload, sig_header, webhook_secret=settings.STRIPE_DONATION_WEBHOOK_SECRET,
        )
    except stripe_lib.error.SignatureVerificationError:
        return HttpResponse("Invalid signature", status=400)
    except Exception as e:
        return HttpResponse(f"Webhook error: {str(e)}", status=400)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        metadata = session.get('metadata', {})
        church_account_number = metadata.get('church_account_number')
        if church_account_number:
            church = Church.objects.filter(donation_account_number=church_account_number).first()
            if church:
                _record_online_donation(
                    church=church,
                    contribution_type=metadata.get('contribution_type', 'offering'),
                    amount=Decimal(session.get('amount_total', 0)) / 100,
                    reference_number=session.get('payment_intent') or session.get('id'),
                    provider_label='Stripe',
                    order_id=metadata.get('order_id', ''),
                    donor_name=metadata.get('donor_name', ''),
                    donor_email=metadata.get('donor_email', ''),
                )

    return HttpResponse("OK", status=200)


def donation_paypal_capture(request):
    """Donor lands here after approving payment on PayPal; capture + record it."""
    order_id = request.GET.get('token', '')
    if not order_id:
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'Missing payment reference.',
        })

    paypal_service = PayPalService()
    result = paypal_service.capture_payment(order_id)
    if not result.get('success'):
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'Unable to complete your PayPal payment. Please contact support if you were charged.',
        })

    order = result['order']
    purchase_unit = (order.get('purchase_units') or [{}])[0]
    captures = (purchase_unit.get('payments') or {}).get('captures') or []
    if not captures or captures[0].get('status') != 'COMPLETED':
        return render(request, 'church_finances/payment_failed.html', {
            'message': 'Payment was not completed.',
        })

    capture = captures[0]
    custom_id = purchase_unit.get('custom_id', '')
    account_number, _, contribution_type = custom_id.partition(':')
    church = get_object_or_404(Church, donation_account_number=account_number)

    donor_info = request.session.pop(f'paypal_donation_{order_id}', {})

    contribution = _record_online_donation(
        church=church,
        contribution_type=contribution_type or 'offering',
        amount=capture['amount']['value'],
        reference_number=capture['id'],
        provider_label='PayPal',
        order_id=order_id,
        donor_name=donor_info.get('donor_name', ''),
        donor_email=donor_info.get('donor_email', ''),
    )

    return render(request, 'church_finances/payment_success.html', {
        'church': church,
        'total': f"{contribution.amount:.2f}",
        'transaction_id': capture['id'],
        'order_id': order_id,
        'contribution': contribution,
    })

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
                    church.subscription_type = selected_package
                    church.subscription_status = 'pending'
                    church.registered_by = user
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
                    # Start the 30-day trial only if the selected plan has it enabled
                    trial_enabled = (
                        church.subscription_plan is not None
                        and church.subscription_plan.free_trial_enabled
                    )
                    if trial_enabled:
                        church.is_approved = True
                        church.is_trial_active = True
                        church.trial_end_date = timezone.now() + timedelta(days=30)
                    else:
                        church.is_approved = False
                        church.is_trial_active = False
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
                    # Create church member record
                    ChurchMember.objects.create(
                        user=user,
                        church=church,
                        role='admin',
                        is_active=True
                    )
                    # Clear the subscription session data
                    request.session.pop('selected_package', None)
                    request.session.pop('package_price', None)
                    request.session.pop('selected_plan_id', None)
                    request.session.pop('declared_member_count', None)
                    # Clear OTP session data after successful registration
                    request.session.pop('otp_verified', None)
                    request.session.pop('otp_email', None)
                    if trial_enabled:
                        success(request, f"Welcome to Church Books! Your 30-day free trial has started. You have {church.trial_days_remaining} days to explore all features.")
                    else:
                        success(request, "Registration successful! Please complete payment to activate your account.")
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


@admin_required
@require_POST
def admin_suspend_church(request, church_id):
    """Toggle a church between suspended and pending."""
    church = get_object_or_404(Church, id=church_id)
    if church.subscription_status == 'suspended':
        church.subscription_status = 'pending'
        church.is_approved = False
        church.save(update_fields=['subscription_status', 'is_approved'])
        success(request, f"'{church.name}' has been unsuspended (set to Pending).")
    else:
        church.subscription_status = 'suspended'
        church.is_approved = False
        church.save(update_fields=['subscription_status', 'is_approved'])
        success(request, f"'{church.name}' has been suspended.")
    return redirect('church_approval_list')


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

        username = (request.POST.get('username', '') or '').strip()
        password = request.POST.get('password', '')

        # Allow login by username or email, case-insensitive.
        matched_user = User.objects.filter(username__iexact=username).first()
        if matched_user is None and username:
            matched_user = User.objects.filter(email__iexact=username).first()

        auth_data = request.POST.copy()
        if matched_user is not None:
            auth_data['username'] = matched_user.username
            username = matched_user.username  # normalize for lockout key below

        # 2. Per-username lockout: locked after 5 failed attempts for 15 minutes
        username_fail_key = f'login_fail_user_{username.lower()}'
        if _get_fail_count(username_fail_key) >= 5:
            error(request, 'This account has been temporarily locked due to too many failed attempts. Please try again in 15 minutes or reset your password.')
            return render(request, 'church_finances/login.html', {'form': AuthenticationForm()})


        # Check if user exists but is inactive
        try:
            user = matched_user or User.objects.get(username=username)
            if not user.is_active:
                if DeletedAccount.objects.filter(user=user).exists():
                    error(request, "This account has been deleted. Please contact support if you believe this is a mistake.")
                else:
                    error(request, f"Your account '{username}' is inactive. Please contact an administrator or check if your church account is pending approval.")
                form = AuthenticationForm()
                return render(request, "church_finances/login.html", {"form": form})
        except User.DoesNotExist:
            pass  # Will be handled by AuthenticationForm

        form = AuthenticationForm(request, data=auth_data)
        if form.is_valid():
            user = form.get_user()

            # Additional check for church member status
            try:
                member = ChurchMember.objects.get(user=user)
                if not member.is_active:
                    error(request, "Your account has been suspended. Please contact your church administrator.")
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
            non_field_errors = form.non_field_errors()
            if non_field_errors:
                error(request, non_field_errors[0])
            else:
                error(request, "Unable to sign in. Please check your username/email and password.")
    else:
        form = AuthenticationForm()

    response = render(request, "church_finances/login.html", {
        "form": form,
    })
    return response


@login_required
@require_POST
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

    search_query = request.GET.get("q", "").strip()
    members = Member.objects.filter(church=church)

    if search_query:
        for term in search_query.split():
            members = members.filter(
                Q(first_name__icontains=term) |
                Q(last_name__icontains=term) |
                Q(email__icontains=term) |
                Q(phone_number__icontains=term)
            )

    return render(request, "church_finances/member_list.html", {
        "members": members,
        "church": church,
        "search_query": search_query,
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
def member_attendance_record_view(request):
    """
    Take attendance for congregation members (one flat roster — members have no class grouping).
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
        attendance_data = request.POST.getlist('attendance')

        try:
            members = Member.objects.filter(church=church, is_active=True)
            for member in members:
                present = str(member.id) in attendance_data
                MemberAttendance.objects.update_or_create(
                    member=member,
                    church=church,
                    date=date,
                    activity_type=activity_type,
                    defaults={
                        'activity_name': activity_name,
                        'present': present,
                        'recorded_by': request.user,
                    }
                )
            success(request, f"Attendance recorded for {activity_type} on {date}.")
            return redirect('member_attendance_record')
        except Exception as e:
            error(request, f"Error recording attendance: {str(e)}")

    roster = Member.objects.filter(church=church, is_active=True).order_by('last_name', 'first_name')

    context = {
        'church': church,
        'roster': roster,
        'activity_types': MemberAttendance.ACTIVITY_TYPES,
    }
    return render(request, "church_finances/member_attendance_record.html", context)


@login_required
def member_attendance_history_view(request):
    """
    View past attendance sessions for congregation members.
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    church_member = ChurchMember.objects.filter(user=request.user, church=church).first()
    if not church_member or church_member.role not in ['admin', 'pastor', 'bishop', 'assistant_pastor', 'deacon']:
        error(request, "You don't have permission to view attendance records.")
        return redirect('dashboard')

    activity_type = request.GET.get('activity_type', '')
    date = request.GET.get('date', '')

    records = MemberAttendance.objects.filter(church=church)
    if activity_type:
        records = records.filter(activity_type=activity_type)
    if date:
        records = records.filter(date=date)

    sessions_qs = (
        records.values('date', 'activity_type', 'activity_name')
        .annotate(total=Count('id'), present_count=Count('id', filter=Q(present=True)))
        .order_by('-date', 'activity_type')
    )
    if not (activity_type or date):
        sessions_qs = sessions_qs[:100]

    activity_type_labels = dict(MemberAttendance.ACTIVITY_TYPES)
    sessions = [
        {
            'date': s['date'],
            'activity_type': s['activity_type'],
            'activity_type_display': activity_type_labels.get(s['activity_type'], s['activity_type']),
            'activity_name': s['activity_name'],
            'total': s['total'],
            'present_count': s['present_count'],
        }
        for s in sessions_qs
    ]

    context = {
        'church': church,
        'activity_types': MemberAttendance.ACTIVITY_TYPES,
        'selected_activity_type': activity_type,
        'selected_date': date,
        'sessions': sessions,
    }
    return render(request, "church_finances/member_attendance_history.html", context)


@login_required
def member_attendance_session_detail_view(request):
    """
    Per-member breakdown for one attendance-taking session (date + activity).
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    church_member = ChurchMember.objects.filter(user=request.user, church=church).first()
    if not church_member or church_member.role not in ['admin', 'pastor', 'bishop', 'assistant_pastor', 'deacon']:
        error(request, "You don't have permission to view attendance records.")
        return redirect('dashboard')

    date = request.GET.get('date', '')
    activity_type = request.GET.get('activity_type', '')
    activity_name = request.GET.get('activity_name', '')

    if not date or not activity_type:
        error(request, "Missing session reference.")
        return redirect('member_attendance_history')

    records = MemberAttendance.objects.filter(
        church=church, date=date, activity_type=activity_type, activity_name=activity_name,
    ).select_related('member').order_by('member__last_name', 'member__first_name')

    if not records.exists():
        error(request, "No attendance session found for that date/activity.")
        return redirect('member_attendance_history')

    context = {
        'church': church,
        'date': date,
        'activity_type': activity_type,
        'activity_type_display': dict(MemberAttendance.ACTIVITY_TYPES).get(activity_type, activity_type),
        'activity_name': activity_name,
        'records': records,
        'present_count': records.filter(present=True).count(),
        'total_count': records.count(),
    }
    return render(request, "church_finances/member_attendance_session_detail.html", context)


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

            duplicate = Contribution.objects.filter(
                church=church,
                member=contribution.member,
                amount=contribution.amount,
                date=contribution.date,
                contribution_type=contribution.contribution_type,
                payment_method='cbm_online',
            ).order_by('-created_at').first() if contribution.member_id else None

            if duplicate and request.POST.get('confirm_cbm_duplicate') != 'yes':
                return render(request, "church_finances/contribution_form.html", {
                    "form": form,
                    "cbm_duplicate": duplicate,
                })

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
def manage_users_view(request):
    church = get_user_church(request.user)
    if not church or church.registered_by_id != request.user.pk:
        raise PermissionDenied("Only the account owner can manage users.")

    staff_members = (
        ChurchMember.objects
        .filter(church=church)
        .exclude(user=request.user)
        .select_related('user')
        .order_by('role', 'user__first_name')
    )
    return render(request, 'church_finances/manage_users.html', {
        'church': church,
        'staff_members': staff_members,
    })


@login_required
def remove_staff_user_view(request, member_id):
    church = get_user_church(request.user)
    if not church or church.registered_by_id != request.user.pk:
        raise PermissionDenied("Only the account owner can remove users.")

    church_member = get_object_or_404(ChurchMember, pk=member_id, church=church)
    if church_member.user_id == request.user.pk:
        error(request, "You cannot remove yourself.")
        return redirect('manage_users')

    if request.method == 'POST':
        user_to_remove = church_member.user
        name = user_to_remove.get_full_name() or user_to_remove.username
        church_member.delete()
        if not ChurchMember.objects.filter(user=user_to_remove).exists():
            user_to_remove.delete()
        success(request, f"{name} has been removed.")
        return redirect('manage_users')

    return render(request, 'church_finances/confirm_remove_user.html', {
        'church_member': church_member,
        'church': church,
    })


@login_required
def suspend_staff_user_view(request, member_id):
    church = get_user_church(request.user)
    if not church or church.registered_by_id != request.user.pk:
        raise PermissionDenied("Only the account owner can suspend users.")

    church_member = get_object_or_404(ChurchMember, pk=member_id, church=church)
    if church_member.user_id == request.user.pk:
        error(request, "You cannot suspend yourself.")
        return redirect('manage_users')

    if request.method == 'POST':
        name = church_member.user.get_full_name() or church_member.user.username
        church_member.is_active = not church_member.is_active
        church_member.save(update_fields=['is_active'])
        if church_member.is_active:
            success(request, f"{name} has been reactivated.")
        else:
            success(request, f"{name} has been suspended.")
        return redirect('manage_users')

    return redirect('manage_users')


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
def delete_account_view(request):
    if request.method != 'POST':
        return redirect('profile')

    password = request.POST.get('password', '')
    if not request.user.check_password(password):
        error(request, 'Incorrect password. Account was not deleted.')
        return redirect('profile')

    user = request.user
    DeletedAccount.objects.get_or_create(user=user)
    ChurchMember.objects.filter(user=user).update(is_active=False)
    user.is_active = False
    user.save(update_fields=['is_active'])
    logout(request)
    return redirect('login')


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
        # Subscription expiry warning (14-day window)
        "is_subscription_expiring_soon": church.is_subscription_expiring_soon,
        "subscription_days_remaining": church.subscription_days_remaining,
        "subscription_end_date": church.subscription_end_date,
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

    month_name = start_date.strftime('%B')
    context = {
        'church': church,
        'contributions': contributions,
        'totals': totals,
        'month': month,
        'month_name': month_name,
        'year': year,
        'current_year': timezone.now().year,
        'print_date': timezone.now()
    }

    if request.GET.get('pdf'):
        return render_to_pdf(request, "church_finances/print/monthly_contributions.html", context,
                             filename=f"contributions_{month_name}_{year}.pdf")
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
        date__year=year,
        member__isnull=False
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

    if request.GET.get('pdf'):
        return render_to_pdf(request, "church_finances/print/member_annual_contributions.html", context,
                             filename=f"member_contributions_{year}.pdf")
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

    if request.GET.get('pdf'):
        return render_to_pdf(request, "church_finances/print/member_contribution_detail.html", context,
                             filename=f"{member.full_name.replace(' ', '_')}_contributions_{year}.pdf")
    return render(request, "church_finances/print/member_contribution_detail.html", context)

@login_required
def contribution_all_members_report(request):
    """
    Combined report: all members' individual contribution details on one page/PDF
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    year = int(request.GET.get('year', timezone.now().year))

    members_with_contributions = Member.objects.filter(
        church=church,
        contribution__date__year=year
    ).distinct().order_by('last_name', 'first_name')

    members_data = []
    for member in members_with_contributions:
        contributions = Contribution.objects.filter(
            church=church, member=member, date__year=year
        ).order_by('date')
        total_tithe = contributions.filter(contribution_type='tithe').aggregate(Sum('amount'))['amount__sum'] or 0
        total_offering = contributions.filter(contribution_type='offering').aggregate(Sum('amount'))['amount__sum'] or 0
        grand_total = contributions.aggregate(Sum('amount'))['amount__sum'] or 0
        members_data.append({
            'member': member,
            'contributions': contributions,
            'total_tithe': total_tithe,
            'total_offering': total_offering,
            'grand_total': grand_total,
        })

    context = {
        'church': church,
        'members_data': members_data,
        'year': year,
        'current_year': timezone.now().year,
        'print_date': timezone.now(),
    }

    if request.GET.get('pdf'):
        return render_to_pdf(request, "church_finances/print/all_members_report.html", context,
                             filename=f"all_member_contributions_{year}.pdf")
    return render(request, "church_finances/print/all_members_report.html", context)

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
    
    if request.GET.get('pdf'):
        return render_to_pdf(request, "church_finances/print/yearly_contributions.html", context,
                             filename=f"contributions_{year}.pdf")
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

    month_name = start_date.strftime('%B')
    context = {
        'church': church,
        'transactions': transactions,
        'totals': totals,
        'month': month,
        'month_name': month_name,
        'year': year,
        'current_year': timezone.now().year,
        'print_date': timezone.now()
    }

    if request.GET.get('pdf'):
        return render_to_pdf(request, "church_finances/print/monthly_transactions.html", context,
                             filename=f"transactions_{month_name}_{year}.pdf")
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
    
    if request.GET.get('pdf'):
        return render_to_pdf(request, "church_finances/print/yearly_transactions.html", context,
                             filename=f"transactions_{year}.pdf")
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

    try:
        name = member.full_name.replace(' ', '_')
        return render_to_pdf(request, 'church_finances/contribution_statement.html', context,
                             filename=f"contribution_statement_{year}_{name}.pdf")
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
    
    members_data = [{'id': cm.id, 'name': cm.full_name} for cm in church_members]

    from datetime import date

    context = {
        'member': member,
        'church': church,
        'church_members': church_members,
        'contribution_types': Contribution.CONTRIBUTION_TYPES,
        'payment_methods': Contribution.PAYMENT_METHODS,
        'members_data': members_data,
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
        guardian_names = request.POST.get('guardian_names', '').strip()
        
        # Emergency contact info
        emergency_contact_name = request.POST.get('emergency_contact_name', '')
        emergency_contact_phone = request.POST.get('emergency_contact_phone', '')
        emergency_contact_relationship = request.POST.get('emergency_contact_relationship', '')
        
        # Additional info
        address = request.POST.get('address', '')
        street_address = request.POST.get('street_address', '')
        city = request.POST.get('city', '')
        state = request.POST.get('state', '')
        zip_code = request.POST.get('zip_code', '')
        country = request.POST.get('country', 'United States')
        phone_number = request.POST.get('phone_number', '')
        notes = request.POST.get('notes', '')
        is_active = request.POST.get('is_active', 'on') == 'on'
        
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
                guardian_names=guardian_names,
                address=address,
                street_address=street_address,
                city=city,
                state=state,
                zip_code=zip_code,
                country=country,
                phone_number=phone_number,
                notes=notes,
                is_active=is_active,
                added_by=request.user
            )
            
            # Add parent links for selected/autocompleted church members.
            if parent_ids or guardian_names:
                parents = Member.objects.filter(id__in=parent_ids, church=church)
                typed_names = [name.strip().lower() for name in guardian_names.splitlines() if name.strip()]
                if typed_names:
                    matched_parents = [
                        member.id for member in Member.objects.filter(church=church, is_active=True)
                        if member.full_name.lower() in typed_names
                    ]
                    parents = parents | Member.objects.filter(id__in=matched_parents, church=church)
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
        child.guardian_names = request.POST.get('guardian_names', '').strip()
        
        # Emergency contact info
        child.emergency_contact_name = request.POST.get('emergency_contact_name')
        child.emergency_contact_phone = request.POST.get('emergency_contact_phone')
        child.emergency_contact_relationship = request.POST.get('emergency_contact_relationship')
        
        # Additional info
        child.address = request.POST.get('address', '')
        child.street_address = request.POST.get('street_address', '')
        child.city = request.POST.get('city', '')
        child.state = request.POST.get('state', '')
        child.zip_code = request.POST.get('zip_code', '')
        child.country = request.POST.get('country', 'United States')
        child.phone_number = request.POST.get('phone_number')
        child.notes = request.POST.get('notes')
        child.is_active = request.POST.get('is_active') == 'on'
        
        try:
            child.save()
            
            # Update parent links for selected/autocompleted church members.
            parent_ids = request.POST.getlist('parents')
            if parent_ids or child.guardian_names:
                parents = Member.objects.filter(id__in=parent_ids, church=church)
                typed_names = [name.strip().lower() for name in child.guardian_names.splitlines() if name.strip()]
                if typed_names:
                    matched_parents = [
                        member.id for member in Member.objects.filter(church=church, is_active=True)
                        if member.full_name.lower() in typed_names
                    ]
                    parents = parents | Member.objects.filter(id__in=matched_parents, church=church)
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


def _children_for_class(church, class_value):
    """Return active children for one Sunday School class ('unassigned' = no class set)."""
    qs = Child.objects.filter(church=church, is_active=True).order_by('last_name', 'first_name')
    if class_value == 'unassigned':
        return qs.exclude(sunday_school_class__in=[v for v, _ in Child.SUNDAY_SCHOOL_CLASSES])
    return qs.filter(sunday_school_class=class_value)


def _class_choices(church):
    """Sunday School class choices with live headcounts, for the class-picker dropdown."""
    children = Child.objects.filter(church=church, is_active=True)
    counts = {value: 0 for value, _ in Child.SUNDAY_SCHOOL_CLASSES}
    unassigned_count = 0
    for child in children:
        if child.sunday_school_class in counts:
            counts[child.sunday_school_class] += 1
        else:
            unassigned_count += 1

    choices = [
        {'value': value, 'label': label, 'count': counts[value]}
        for value, label in Child.SUNDAY_SCHOOL_CLASSES
        if counts[value]
    ]
    if unassigned_count:
        choices.append({'value': 'unassigned', 'label': 'Unassigned', 'count': unassigned_count})
    return choices


@login_required
def attendance_record_view(request):
    """
    Take attendance for one Sunday School class at a time.
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
        selected_class = request.POST.get('sunday_school_class', '')

        attendance_data = request.POST.getlist('attendance')  # List of child IDs who were present

        try:
            children = _children_for_class(church, selected_class)

            for child in children:
                present = str(child.id) in attendance_data
                ChildAttendance.objects.update_or_create(
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
            return redirect(f"{reverse('attendance_record')}?sunday_school_class={selected_class}")

        except Exception as e:
            error(request, f"Error recording attendance: {str(e)}")

    selected_class = request.GET.get('sunday_school_class', '')
    class_choices = _class_choices(church)
    roster = list(_children_for_class(church, selected_class)) if selected_class else []

    context = {
        'church': church,
        'class_choices': class_choices,
        'selected_class': selected_class,
        'roster': roster,
        'activity_types': ChildAttendance.ACTIVITY_TYPES,
    }
    return render(request, "church_finances/attendance_record.html", context)


@login_required
def attendance_history_view(request):
    """
    View past attendance records for a class/date/activity.
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    church_member = ChurchMember.objects.filter(user=request.user, church=church).first()
    if not church_member or church_member.role not in ['admin', 'pastor', 'bishop', 'assistant_pastor', 'deacon']:
        error(request, "You don't have permission to view attendance records.")
        return redirect('dashboard')

    selected_class = request.GET.get('sunday_school_class', '')
    activity_type = request.GET.get('activity_type', '')
    date = request.GET.get('date', '')

    records = ChildAttendance.objects.filter(church=church)

    if selected_class == 'unassigned':
        records = records.exclude(child__sunday_school_class__in=[v for v, _ in Child.SUNDAY_SCHOOL_CLASSES])
    elif selected_class:
        records = records.filter(child__sunday_school_class=selected_class)

    if activity_type:
        records = records.filter(activity_type=activity_type)

    if date:
        records = records.filter(date=date)

    # One attendance-taking submission = one (date, activity_type, activity_name) group.
    sessions_qs = (
        records.values('date', 'activity_type', 'activity_name')
        .annotate(total=Count('id'), present_count=Count('id', filter=Q(present=True)))
        .order_by('-date', 'activity_type')
    )
    if not (selected_class or activity_type or date):
        sessions_qs = sessions_qs[:100]  # No filters yet — show the most recent sessions only.

    activity_type_labels = dict(ChildAttendance.ACTIVITY_TYPES)
    class_labels = dict(Child.SUNDAY_SCHOOL_CLASSES)
    sessions = []
    for s in sessions_qs:
        classes_in_session = (
            ChildAttendance.objects.filter(
                church=church, date=s['date'], activity_type=s['activity_type'], activity_name=s['activity_name'],
            )
            .values_list('child__sunday_school_class', flat=True)
            .distinct()
        )
        labels = [class_labels.get(v, 'Unassigned') if v else 'Unassigned' for v in classes_in_session]
        class_label = labels[0] if len(labels) == 1 else ('Mixed Classes' if len(labels) > 1 else 'Unassigned')

        sessions.append({
            'date': s['date'],
            'activity_type': s['activity_type'],
            'activity_type_display': activity_type_labels.get(s['activity_type'], s['activity_type']),
            'activity_name': s['activity_name'],
            'class_label': class_label,
            'total': s['total'],
            'present_count': s['present_count'],
        })

    context = {
        'church': church,
        'class_choices': _class_choices(church),
        'selected_class': selected_class,
        'activity_types': ChildAttendance.ACTIVITY_TYPES,
        'selected_activity_type': activity_type,
        'selected_date': date,
        'sessions': sessions,
    }
    return render(request, "church_finances/attendance_history.html", context)


@login_required
def attendance_session_detail_view(request):
    """
    Per-child breakdown for one attendance-taking session (date + activity).
    """
    church = get_user_church(request.user)
    if not church:
        info(request, "Your church account is pending approval.")
        return render(request, "church_finances/pending_approval.html")

    church_member = ChurchMember.objects.filter(user=request.user, church=church).first()
    if not church_member or church_member.role not in ['admin', 'pastor', 'bishop', 'assistant_pastor', 'deacon']:
        error(request, "You don't have permission to view attendance records.")
        return redirect('dashboard')

    date = request.GET.get('date', '')
    activity_type = request.GET.get('activity_type', '')
    activity_name = request.GET.get('activity_name', '')

    if not date or not activity_type:
        error(request, "Missing session reference.")
        return redirect('attendance_history')

    records = ChildAttendance.objects.filter(
        church=church, date=date, activity_type=activity_type, activity_name=activity_name,
    ).select_related('child').order_by('child__last_name', 'child__first_name')

    if not records.exists():
        error(request, "No attendance session found for that date/activity.")
        return redirect('attendance_history')

    context = {
        'church': church,
        'date': date,
        'activity_type': activity_type,
        'activity_type_display': dict(ChildAttendance.ACTIVITY_TYPES).get(activity_type, activity_type),
        'activity_name': activity_name,
        'records': records,
        'present_count': records.filter(present=True).count(),
        'total_count': records.count(),
    }
    return render(request, "church_finances/attendance_session_detail.html", context)


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
    name = christening.baby_full_name.replace(' ', '_')
    return render_to_pdf(request, "church_finances/christening_certificate.html", context,
                         filename=f"christening_{name}.pdf")


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
    name = member.full_name.replace(' ', '_')
    return render_to_pdf(request, "church_finances/baptism_certificate.html", context,
                         filename=f"baptism_{name}.pdf")
