import requests
import json
import base64
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from .models import Church, PayPalSubscription, PayPalWebhook

class PayPalService:
    def __init__(self):
        # PayPal API URLs
        if settings.PAYPAL_MODE == 'sandbox':
            self.base_url = 'https://api-m.sandbox.paypal.com'
            self.checkout_url = 'https://www.sandbox.paypal.com'
        else:
            self.base_url = 'https://api-m.paypal.com'
            self.checkout_url = 'https://www.paypal.com'

    def get_access_token(self):
        """
        Get OAuth access token from PayPal
        """
        url = f"{self.base_url}/v1/oauth2/token"
        
        # Create basic auth header
        credentials = f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            'Accept': 'application/json',
            'Accept-Language': 'en_US',
            'Authorization': f'Basic {encoded_credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = 'grant_type=client_credentials'
        
        response = requests.post(url, headers=headers, data=data)
        
        if response.status_code == 200:
            return response.json().get('access_token')
        else:
            raise Exception(f"Failed to get access token: {response.text}")

    def create_subscription(self, plan_id, payer_info, church_id):
        """
        Create a simple PayPal payment (one-time payment for annual subscription)
        This is more reliable than subscription APIs
        """
        try:
            # Determine amount based on plan
            if 'standard' in plan_id.lower():
                amount = "100.00"
                plan_name = "Standard Plan"
            else:
                amount = "150.00"
                plan_name = "Premium Plan"
            
            # Create a simple PayPal checkout URL
            # We'll use the Express Checkout API which is more reliable
            
            access_token = self.get_access_token()
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}',
            }
            
            payment_data = {
                "intent": "CAPTURE",
                "purchase_units": [{
                    "amount": {
                        "currency_code": "USD",
                        "value": amount
                    },
                    "description": f"Church Books {plan_name} - Annual Subscription",
                    "custom_id": str(church_id)
                }],
                "application_context": {
                    "return_url": f"{settings.PAYPAL_BASE_URL}/finances/subscription/success/",
                    "cancel_url": f"{settings.PAYPAL_BASE_URL}/finances/subscription/cancel/",
                    "brand_name": "Church Books",
                    "landing_page": "BILLING",
                    "user_action": "PAY_NOW"
                }
            }
            
            response = requests.post(
                f"{self.base_url}/v2/checkout/orders",
                headers=headers,
                json=payment_data
            )
            
            if response.status_code == 201:
                order = response.json()
                
                # Find the approval URL
                approval_url = None
                for link in order.get('links', []):
                    if link.get('rel') == 'approve':
                        approval_url = link.get('href')
                        break
                
                if approval_url:
                    return {
                        'success': True,
                        'subscription_id': order['id'],
                        'approval_url': approval_url
                    }
                else:
                    return {'success': False, 'error': 'No approval URL found'}
            else:
                return {'success': False, 'error': f'PayPal API error: {response.text}'}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _get_approval_url(self, links):
        """
        Extract approval URL from PayPal links
        """
        for link in links:
            if link.rel == "approve":
                return link.href
        return None

    def activate_subscription(self, subscription_id, reason="Activating subscription"):
        """
        Activate a PayPal subscription
        """
        try:
            subscription = paypalrestsdk.Subscription.find(subscription_id)
            activate_response = subscription.activate({
                "reason": reason
            })
            return {'success': True, 'response': activate_response}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_subscription_details(self, subscription_id):
        """
        Get subscription details from PayPal
        """
        try:
            subscription = paypalrestsdk.Subscription.find(subscription_id)
            return {
                'success': True,
                'subscription': subscription
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def cancel_subscription(self, subscription_id, reason="User requested cancellation"):
        """
        Cancel a PayPal subscription
        """
        try:
            subscription = paypalrestsdk.Subscription.find(subscription_id)
            cancel_response = subscription.cancel({
                "reason": reason
            })
            return {'success': True, 'response': cancel_response}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def process_webhook(self, webhook_data):
        """
        Process PayPal webhook events
        """
        try:
            event_type = webhook_data.get('event_type')
            resource = webhook_data.get('resource', {})
            
            # Store webhook event
            webhook = PayPalWebhook.objects.create(
                event_id=webhook_data.get('id'),
                event_type=event_type,
                resource_type=resource.get('resource_type', ''),
                subscription_id=resource.get('id', ''),
                data=webhook_data
            )

            # Process different event types
            if event_type == 'BILLING.SUBSCRIPTION.ACTIVATED':
                self._handle_subscription_activated(resource)
            elif event_type == 'BILLING.SUBSCRIPTION.CANCELLED':
                self._handle_subscription_cancelled(resource)
            elif event_type == 'BILLING.SUBSCRIPTION.SUSPENDED':
                self._handle_subscription_suspended(resource)
            elif event_type == 'PAYMENT.SALE.COMPLETED':
                self._handle_payment_completed(resource)

            webhook.processed = True
            webhook.save()
            
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _handle_subscription_activated(self, resource):
        """
        Handle subscription activation
        """
        try:
            subscription_id = resource.get('id')
            custom_id = resource.get('custom_id')
            
            if custom_id:
                church = Church.objects.get(id=custom_id)
                
                # Update or create PayPal subscription record
                paypal_sub, created = PayPalSubscription.objects.get_or_create(
                    subscription_id=subscription_id,
                    defaults={
                        'church': church,
                        'plan_id': resource.get('plan_id'),
                        'status': 'ACTIVE',
                        'payer_id': resource.get('subscriber', {}).get('payer_id', ''),
                        'payer_email': resource.get('subscriber', {}).get('email_address', ''),
                        'create_time': timezone.now(),
                        'start_time': self._parse_paypal_datetime(resource.get('start_time')),
                        'next_billing_time': self._parse_paypal_datetime(resource.get('billing_info', {}).get('next_billing_time')),
                        'amount': self._get_subscription_amount(resource.get('plan_id')),
                        'currency': 'USD'
                    }
                )
                
                if not created:
                    paypal_sub.status = 'ACTIVE'
                    paypal_sub.start_time = self._parse_paypal_datetime(resource.get('start_time'))
                    paypal_sub.next_billing_time = self._parse_paypal_datetime(resource.get('billing_info', {}).get('next_billing_time'))
                    paypal_sub.save()

                # Approve church and update subscription status
                church.is_approved = True
                church.subscription_status = 'active'
                church.paypal_subscription_id = subscription_id
                church.subscription_start_date = paypal_sub.start_time
                # Set end date to 1 year from start
                if paypal_sub.start_time:
                    church.subscription_end_date = paypal_sub.start_time + timedelta(days=365)
                church.save()
                
        except Exception as e:
            print(f"Error handling subscription activation: {e}")

    def _handle_subscription_cancelled(self, resource):
        """
        Handle subscription cancellation
        """
        try:
            subscription_id = resource.get('id')
            paypal_sub = PayPalSubscription.objects.get(subscription_id=subscription_id)
            paypal_sub.status = 'CANCELLED'
            paypal_sub.save()
            
            # Update church status
            church = paypal_sub.church
            church.subscription_status = 'cancelled'
            church.save()
            
        except PayPalSubscription.DoesNotExist:
            pass
        except Exception as e:
            print(f"Error handling subscription cancellation: {e}")

    def _handle_subscription_suspended(self, resource):
        """
        Handle subscription suspension
        """
        try:
            subscription_id = resource.get('id')
            paypal_sub = PayPalSubscription.objects.get(subscription_id=subscription_id)
            paypal_sub.status = 'SUSPENDED'
            paypal_sub.save()
            
            # Update church status
            church = paypal_sub.church
            church.subscription_status = 'suspended'
            church.save()
            
        except PayPalSubscription.DoesNotExist:
            pass
        except Exception as e:
            print(f"Error handling subscription suspension: {e}")

    def _handle_payment_completed(self, resource):
        """
        Handle completed payment
        """
        try:
            # You can add payment tracking logic here if needed
            billing_agreement_id = resource.get('billing_agreement_id')
            if billing_agreement_id:
                # Update last payment date or other tracking
                pass
        except Exception as e:
            print(f"Error handling payment completion: {e}")

    def _parse_paypal_datetime(self, datetime_str):
        """
        Parse PayPal datetime string to Django datetime
        """
        if not datetime_str:
            return None
        try:
            # PayPal uses ISO format: 2023-12-01T10:00:00Z
            return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        except:
            return None

    def _get_subscription_amount(self, plan_id):
        """
        Get subscription amount based on plan ID
        """
        if plan_id == settings.PAYPAL_STANDARD_PLAN_ID:
            return 150.00
        elif plan_id == settings.PAYPAL_PREMIUM_PLAN_ID:
            return 200.00
        return 0.00
