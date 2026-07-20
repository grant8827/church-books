import hashlib
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core import mail
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse

from . import views
from .forms import HostedPaymentLinkForm, WiPaySetupForm
from .models import Church, ChurchMember, Contribution, HostedDonationAttempt, ManagedPaymentGateway, Member, SupportTicket, SupportTicketReply, Transaction, WiPayDonationAttempt


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


class HostedPaymentLinkFormTests(SimpleTestCase):
    def test_accepts_provider_owned_urls(self):
        self.assertTrue(HostedPaymentLinkForm(
            {'payment_url': 'https://paypal.me/testchurch'}, provider='paypal',
        ).is_valid())
        self.assertTrue(HostedPaymentLinkForm(
            {'payment_url': 'https://buy.stripe.com/test'}, provider='stripe',
        ).is_valid())

    def test_rejects_lookalike_url(self):
        form = HostedPaymentLinkForm(
            {'payment_url': 'https://paypal.com.example.test/church'}, provider='paypal',
        )
        self.assertFalse(form.is_valid())


class HostedDonationWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('portal-admin', password='test-password')
        self.church = Church.objects.create(
            name='Hosted Link Church', address='1 Test Street', phone='555-0100',
            email='hosted@example.com', donation_account_number='CBHOSTED1',
        )
        ChurchMember.objects.create(user=self.admin, church=self.church, role='admin')
        self.gateway = ManagedPaymentGateway.objects.create(
            church=self.church, provider='wipay', is_active=False,
            paypal_payment_url='https://paypal.me/hostedchurch',
            stripe_payment_url='https://buy.stripe.com/hostedchurch',
        )

    def test_donor_chooses_from_church_hosted_links(self):
        response = self.client.post(reverse('donor_payment_portal'), {
            'church_account_number': 'CBHOSTED1', 'amount': '25.00',
            'contribution_type': 'tithe', 'donor_name': 'Test Donor',
            'donor_email': 'donor@example.com',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Continue with Paypal')
        self.assertContains(response, 'Continue with Stripe')

    def test_redirect_creates_pending_attempt_not_contribution(self):
        response = self.client.post(reverse('donor_payment_portal'), {
            'church_account_number': 'CBHOSTED1', 'amount': '25.00',
            'contribution_type': 'tithe', 'donor_name': 'Test Donor',
            'donor_email': 'donor@example.com', 'payment_provider': 'paypal',
        })
        self.assertRedirects(response, 'https://paypal.me/hostedchurch', fetch_redirect_response=False)
        self.assertEqual(HostedDonationAttempt.objects.filter(status='pending').count(), 1)
        self.assertEqual(Contribution.objects.count(), 0)

    def test_admin_confirmation_records_contribution_once(self):
        attempt = HostedDonationAttempt.objects.create(
            church=self.church, provider='stripe', amount='25.00',
            contribution_type='tithe', donor_name='Test Donor',
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse('resolve_hosted_donation', args=[attempt.pk]), {
            'action': 'confirm',
        })
        self.assertRedirects(response, reverse('payment_portals'))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'confirmed')
        self.assertEqual(attempt.contribution.payment_method, 'cbm_online')
        self.assertEqual(Contribution.objects.count(), 1)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SupportTicketWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'support-user', email='user@example.com', password='test-password',
        )
        self.superuser = User.objects.create_superuser(
            'support-admin', email='admin@example.com', password='test-password',
        )

    def test_authenticated_user_can_submit_support_ticket(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('submit_support_ticket'), {
            'category': 'login_problem', 'subject': 'Cannot sign in elsewhere',
            'message': 'Please help me access the account.',
        })
        self.assertRedirects(response, reverse('dashboard'))
        ticket = SupportTicket.objects.get()
        self.assertEqual(ticket.user, self.user)
        self.assertEqual(ticket.contact_email, 'user@example.com')
        self.assertEqual(ticket.status, 'open')

    def test_regular_user_cannot_open_superuser_inbox(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('support_ticket_inbox'))
        self.assertEqual(response.status_code, 403)

    def test_superuser_reply_is_saved_and_emailed(self):
        ticket = SupportTicket.objects.create(
            user=self.user, category='account_error', subject='Account error',
            message='My account shows an error.', contact_email='user@example.com',
        )
        self.client.force_login(self.superuser)
        response = self.client.post(reverse('support_ticket_detail', args=[ticket.pk]), {
            'reply': 'We corrected the account. Please try again.',
        })
        self.assertRedirects(response, reverse('support_ticket_detail', args=[ticket.pk]))
        ticket.refresh_from_db()
        reply = SupportTicketReply.objects.get(ticket=ticket)
        self.assertEqual(ticket.status, 'answered')
        self.assertTrue(reply.email_sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['user@example.com'])


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
            amount=Decimal('25.00'),
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


class WiPayCorrelatedCallbackTests(TestCase):
    def setUp(self):
        self.church = Church.objects.create(
            name='Test Church',
            address='1 Test Street',
            phone='555-0100',
            email='church@example.com',
        )
        self.attempt = WiPayDonationAttempt.objects.create(
            order_id='DONATION-test-order',
            church=self.church,
            amount=Decimal('25.00'),
            currency='TTD',
            contribution_type='tithe',
            donor_name='Test Member',
            donor_email='member@example.com',
        )
        self.gateway = ManagedPaymentGateway.objects.create(
            church=self.church,
            provider='wipay',
            is_active=True,
            wipay_account_id='1234567890',
            wipay_country='TT',
            wipay_account_type='business',
        )
        self.gateway.set_wipay_api_key('test-api-key')
        self.gateway.save(update_fields=['wipay_api_key_encrypted'])

    def callback(self, **overrides):
        params = {
            'status': 'success',
            'transaction_id': 'WIPAY-TRANSACTION-1',
            'total': '25.00',
            'order_id': self.attempt.order_id,
        }
        params.update(overrides)
        params.setdefault(
            'hash',
            hashlib.md5(
                f"{params['transaction_id']}{self.attempt.amount:.2f}test-api-key".encode('utf-8')
            ).hexdigest(),
        )
        return self.client.get(reverse('wipay_callback'), params)

    def test_matching_success_callback_records_contribution(self):
        response = self.callback()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Successful')
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'completed')
        self.assertEqual(self.attempt.verification_method, 'wipay_hash')
        self.assertEqual(self.attempt.transaction_id, 'WIPAY-TRANSACTION-1')
        self.assertEqual(self.attempt.contribution.payment_method, 'cbm_online')

    def test_fee_inclusive_returned_total_uses_original_amount_for_verification(self):
        response = self.callback(total='30.00')

        self.assertContains(response, 'Payment Successful')
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'completed')
        self.assertEqual(self.attempt.contribution.amount, self.attempt.amount)

    def test_unknown_order_is_rejected(self):
        response = self.callback(order_id='UNKNOWN-ORDER')

        self.assertContains(response, 'could not be matched')
        self.assertFalse(Contribution.objects.filter(church=self.church).exists())

    def test_repeat_callback_does_not_duplicate_contribution(self):
        first = self.callback()
        second = self.callback()

        self.assertContains(first, 'Payment Successful')
        self.assertContains(second, 'Payment Successful')
        self.assertEqual(Contribution.objects.filter(church=self.church).count(), 1)
        self.assertEqual(Transaction.objects.filter(church=self.church).count(), 1)

    def test_invalid_hash_is_rejected(self):
        response = self.callback(hash='not-the-correct-hash')

        self.assertContains(response, 'Payment verification failed')
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'pending')
        self.assertFalse(Contribution.objects.filter(church=self.church).exists())


class WiPayBusinessSetupTests(TestCase):
    def setUp(self):
        self.church = Church.objects.create(
            name='Test Church',
            address='1 Test Street',
            phone='555-0100',
            email='church@example.com',
        )
        self.gateway = ManagedPaymentGateway(church=self.church, provider='wipay')

    def test_business_api_key_is_encrypted_and_not_rendered_back(self):
        form = WiPaySetupForm({
            'wipay_account_type': 'business',
            'wipay_account_id': '1234567890',
            'wipay_country': 'TT',
            'wipay_api_key': 'secret-payment-api-key',
        }, instance=self.gateway)

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertNotIn('secret-payment-api-key', saved.wipay_api_key_encrypted)
        self.assertEqual(saved.get_wipay_api_key(), 'secret-payment-api-key')
        self.assertNotIn('secret-payment-api-key', WiPaySetupForm(instance=saved).as_p())

    def test_personal_account_is_rejected(self):
        form = WiPaySetupForm({
            'wipay_account_type': 'personal',
            'wipay_account_id': '1234567890',
            'wipay_country': 'TT',
            'wipay_api_key': '',
        }, instance=self.gateway)

        self.assertFalse(form.is_valid())
        self.assertIn('verified Business Account', form.errors['wipay_account_type'][0])

    def test_existing_encrypted_key_can_be_kept_when_form_is_resaved(self):
        self.gateway.set_wipay_api_key('existing-api-key')
        self.gateway.save()
        form = WiPaySetupForm({
            'wipay_account_type': 'business',
            'wipay_account_id': '1234567890',
            'wipay_country': 'TT',
            'wipay_api_key': '',
        }, instance=self.gateway)

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.get_wipay_api_key(), 'existing-api-key')
