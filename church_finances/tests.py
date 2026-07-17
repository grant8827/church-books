from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse

from . import views
from .models import Church, ChurchMember, Contribution, Member, Transaction


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


class OnlineContributionRecordingTests(TestCase):
    def setUp(self):
        self.church = Church.objects.create(
            name='Test Church',
            address='1 Test Street',
            phone='555-0100',
            email='church@example.com',
        )

    def record(self, reference, donor_email='member@example.com'):
        return views._record_online_donation(
            church=self.church,
            contribution_type='tithe',
            amount='25.00',
            reference_number=reference,
            provider_label='Stripe',
            donor_name='Test Member',
            donor_email=donor_email,
        )

    def test_online_payment_uses_cbm_online_and_matches_unique_member_email(self):
        member = Member.objects.create(
            church=self.church,
            first_name='Test',
            last_name='Member',
            email='MEMBER@example.com',
        )

        contribution = self.record('portal-1')

        self.assertEqual(contribution.payment_method, 'cbm_online')
        self.assertEqual(contribution.member, member)
        self.assertEqual(Transaction.objects.filter(church=self.church).count(), 1)

    def test_ambiguous_member_email_remains_unassigned(self):
        for first_name in ('First', 'Second'):
            Member.objects.create(
                church=self.church,
                first_name=first_name,
                last_name='Member',
                email='member@example.com',
            )

        contribution = self.record('portal-2')

        self.assertIsNone(contribution.member)
        self.assertEqual(contribution.payment_method, 'cbm_online')

    def test_repeated_gateway_callback_is_idempotent(self):
        first = self.record('portal-3', donor_email='')
        second = self.record('portal-3', donor_email='')

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Contribution.objects.filter(church=self.church).count(), 1)
        self.assertEqual(Transaction.objects.filter(church=self.church).count(), 1)


class ManualContributionDuplicateWarningTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('treasurer', password='test-password')
        self.church = Church.objects.create(
            name='Test Church',
            address='1 Test Street',
            phone='555-0100',
            email='church@example.com',
            is_approved=True,
        )
        ChurchMember.objects.create(user=self.user, church=self.church, role='treasurer')
        self.member = Member.objects.create(
            church=self.church,
            first_name='Test',
            last_name='Member',
            email='member@example.com',
        )
        Contribution.objects.create(
            church=self.church,
            member=self.member,
            date='2026-07-17',
            contribution_type='tithe',
            amount='25.00',
            payment_method='cbm_online',
            reference_number='online-1',
        )
        self.client.force_login(self.user)
        self.form_data = {
            'contrib_category': 'tithe',
            'member': self.member.pk,
            'contributor_name': '',
            'date': '2026-07-17',
            'contribution_type': 'tithe',
            'amount': '25.00',
            'payment_method': 'cash',
            'reference_number': '',
            'notes': '',
        }

    def test_matching_cbm_online_contribution_shows_warning_without_saving(self):
        response = self.client.post(reverse('contribution_add'), self.form_data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Possible duplicate contribution')
        self.assertContains(response, 'Continue')
        self.assertEqual(Contribution.objects.filter(church=self.church).count(), 1)

    def test_continue_confirmation_saves_separate_transaction(self):
        response = self.client.post(reverse('contribution_add'), {
            **self.form_data,
            'confirm_cbm_duplicate': 'yes',
        })

        self.assertRedirects(response, reverse('contribution_list'))
        self.assertEqual(Contribution.objects.filter(church=self.church).count(), 2)

    def test_different_contribution_type_does_not_warn(self):
        response = self.client.post(reverse('contribution_add'), {
            **self.form_data,
            'contrib_category': 'offering',
            'member': '',
            'contributor_name': self.member.full_name,
            'contribution_type': 'offering',
        })

        self.assertRedirects(response, reverse('contribution_list'))
        self.assertEqual(Contribution.objects.filter(church=self.church).count(), 2)
