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


def construct_webhook_event(payload, sig_header):
    """
    Verify and construct a Stripe webhook event.
    Raises stripe.error.SignatureVerificationError if the signature is invalid.
    """
    client = get_stripe_client()
    return client.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )
