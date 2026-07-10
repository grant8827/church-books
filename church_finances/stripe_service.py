"""
Stripe payment service for Church Books.
Uses Stripe Checkout (hosted payment page) for simplicity and security.
"""
import stripe
from django.conf import settings


def get_stripe_client():
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def create_checkout_session(church_id, user_id, email, church_name, success_url, cancel_url):
    """
    Create a Stripe Checkout Session for a $120/year Church Books subscription.
    Returns the session object on success, raises an exception on failure.
    """
    client = get_stripe_client()

    session = client.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {
                    'name': 'Church Books – Annual Subscription',
                    'description': f'Full access for {church_name} – 1 year',
                },
                'unit_amount': 12000,   # $120.00 in cents
                'recurring': {'interval': 'year'},
            },
            'quantity': 1,
        }],
        mode='subscription',
        success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=cancel_url,
        customer_email=email,
        metadata={
            'church_id': str(church_id),
            'user_id': str(user_id),
        },
        subscription_data={
            'metadata': {
                'church_id': str(church_id),
                'user_id': str(user_id),
            }
        }
    )
    return session


def retrieve_checkout_session(session_id):
    """Retrieve a Checkout Session by ID to verify payment status."""
    client = get_stripe_client()
    return client.checkout.Session.retrieve(session_id)


def construct_webhook_event(payload, sig_header, webhook_secret=None):
    """
    Verify and construct a Stripe webhook event.
    Raises stripe.error.SignatureVerificationError if the signature is invalid.
    `webhook_secret` lets callers verify against a different endpoint's secret
    (e.g. the donor-tithing webhook vs. the subscription-billing webhook).
    """
    client = get_stripe_client()
    return client.Webhook.construct_event(
        payload, sig_header, webhook_secret or settings.STRIPE_WEBHOOK_SECRET
    )


# ---------------------------------------------------------------------------
# Stripe Connect (donor-tithing): church onboarding + destination-charge checkout
# ---------------------------------------------------------------------------

def create_connect_account(country, email):
    """Create a Standard Connect account for a church so donor funds route to them."""
    client = get_stripe_client()
    return client.Account.create(type='standard', country=country, email=email)


def create_account_link(account_id, refresh_url, return_url):
    """Create the one-time onboarding link a church admin visits to finish Stripe setup."""
    client = get_stripe_client()
    return client.AccountLink.create(
        account=account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type='account_onboarding',
    )


def retrieve_connect_account(account_id):
    """Retrieve a Connect account to check onboarding status (details_submitted, charges_enabled)."""
    client = get_stripe_client()
    return client.Account.retrieve(account_id)


def create_donation_checkout_session(amount_cents, currency, church_name, destination_account_id,
                                      success_url, cancel_url, metadata):
    """
    Create a Checkout Session for a one-time donation that routes funds directly
    to the church's connected Stripe account via a destination charge.
    """
    client = get_stripe_client()
    return client.checkout.Session.create(
        mode='payment',
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': currency,
                'product_data': {'name': f'Tithe/Offering to {church_name}'},
                'unit_amount': amount_cents,
            },
            'quantity': 1,
        }],
        payment_intent_data={
            'transfer_data': {'destination': destination_account_id},
        },
        metadata=metadata,
        success_url=success_url,
        cancel_url=cancel_url,
    )
