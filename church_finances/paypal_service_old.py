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
                amount = "120.00"
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

    def capture_payment(self, order_id):
        """
        Capture an approved PayPal order
        """
        try:
            access_token = self.get_access_token()
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}',
            }
            
            response = requests.post(
                f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
                headers=headers
            )
            
            if response.status_code == 201:
                return {'success': True, 'order': response.json()}
            else:
                return {'success': False, 'error': f'Capture failed: {response.text}'}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_order_details(self, order_id):
        """
        Get order details from PayPal
        """
        try:
            access_token = self.get_access_token()
            
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            
            response = requests.get(
                f"{self.base_url}/v2/checkout/orders/{order_id}",
                headers=headers
            )
            
            if response.status_code == 200:
                return {'success': True, 'order': response.json()}
            else:
                return {'success': False, 'error': f'Failed to get order: {response.text}'}
                
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

            # Process payment completion
            if event_type == 'CHECKOUT.ORDER.APPROVED':
                self._handle_order_approved(resource)
            elif event_type == 'PAYMENT.CAPTURE.COMPLETED':
                self._handle_payment_completed(resource)

            webhook.processed = True
            webhook.save()
            
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _handle_order_approved(self, resource):
        """
        Handle approved order - approve church account
        """
        try:
            # Get custom_id from purchase units
            purchase_units = resource.get('purchase_units', [])
            if purchase_units:
                custom_id = purchase_units[0].get('custom_id')
                if custom_id:
                    church = Church.objects.get(id=custom_id)
                    
                    # Create PayPal subscription record
                    paypal_sub, created = PayPalSubscription.objects.get_or_create(
                        subscription_id=resource.get('id'),
                        defaults={
                            'church': church,
                            'plan_id': 'paypal_order',
                            'status': 'ACTIVE',
                            'payer_id': resource.get('payer', {}).get('payer_id', ''),
                            'payer_email': resource.get('payer', {}).get('email_address', ''),
                            'create_time': timezone.now(),
                            'start_time': timezone.now(),
                            'amount': float(purchase_units[0].get('amount', {}).get('value', 0)),
                            'currency': purchase_units[0].get('amount', {}).get('currency_code', 'USD')
                        }
                    )
                    
                    # Approve church and update subscription status
                    church.is_approved = True
                    church.subscription_status = 'active'
                    church.paypal_subscription_id = resource.get('id')
                    church.subscription_start_date = timezone.now()
                    church.subscription_end_date = timezone.now() + timedelta(days=365)
                    church.save()
                    
        except Exception as e:
            print(f"Error handling order approval: {e}")

    def _handle_payment_completed(self, resource):
        """
        Handle completed payment
        """
        try:
            # Similar to order approved but for capture events
            pass
        except Exception as e:
            print(f"Error handling payment completion: {e}")

    def _get_subscription_amount(self, plan_id):
        """
        Get subscription amount based on plan ID
        """
        if 'standard' in plan_id.lower():
            return 100.00
        elif 'premium' in plan_id.lower():
            return 120.00
        return 0.00
