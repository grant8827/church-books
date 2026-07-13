from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse

from . import views


class PaymentPortalSwitchingTests(SimpleTestCase):
    def gateway(self, **overrides):
        values = {
            'is_active': False,
            'connected_account_id': None,
            'paypal_tracking_id': None,
            'wipay_account_id': None,
            'wipay_country': None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_empty_gateway_has_no_saved_connection(self):
        self.assertFalse(views._gateway_has_saved_connection(self.gateway()))

    def test_active_gateway_has_saved_connection(self):
        self.assertTrue(views._gateway_has_saved_connection(self.gateway(is_active=True)))

    def test_incomplete_onboarding_has_saved_connection(self):
        self.assertTrue(views._gateway_has_saved_connection(
            self.gateway(paypal_tracking_id='church-1-tracking')
        ))

    def test_disconnect_url_uses_disconnect_view(self):
        match = resolve(reverse('disconnect_payment_portal'))
        self.assertIs(match.func, views.disconnect_payment_portal)


class StripeConfigurationTests(SimpleTestCase):
    @override_settings(STRIPE_SECRET_KEY='', STRIPE_PUBLISHABLE_KEY='')
    def test_missing_secret_key_is_rejected(self):
        self.assertIn('STRIPE_SECRET_KEY', views._stripe_configuration_error())

    @override_settings(
        STRIPE_SECRET_KEY='sk_live_example',
        STRIPE_PUBLISHABLE_KEY='pk_test_example',
    )
    def test_mixed_key_modes_are_rejected(self):
        self.assertIn('different modes', views._stripe_configuration_error())

    @override_settings(
        STRIPE_SECRET_KEY='sk_live_example',
        STRIPE_PUBLISHABLE_KEY='pk_live_example',
    )
    def test_matching_key_modes_are_accepted(self):
        self.assertEqual(views._stripe_configuration_error(), '')

    @override_settings(STRIPE_CONNECT_RETURN_URL='https://example.com/stripe/return')
    def test_configured_stripe_url_is_used(self):
        request = RequestFactory().get('/payment-portals/')
        self.assertEqual(
            views._configured_url(request, 'STRIPE_CONNECT_RETURN_URL', '/fallback/'),
            'https://example.com/stripe/return',
        )
