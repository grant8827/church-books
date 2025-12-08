import json
from datetime import datetime
from django.conf import settings
from .models import Church

class MockPayPalService:
    """
    Mock PayPal service for development when real credentials are not available.
    Replace this with the real PayPalService once you have working credentials.
    """
    
    def __init__(self):
        self.base_url = 'https://api-m.sandbox.paypal.com'  # Mock URL
        self.is_mock = True
    
    def get_access_token(self):
        """
        Mock access token - always returns a fake token
        """
        return "mock_access_token_12345abcdef"
    
    def create_subscription(self, plan_id, payer_info, church_id):
        """
        Mock subscription creation - returns fake but valid-looking response
        """
        try:
            # Determine amount based on plan
            if 'standard' in plan_id.lower():
                amount = "150.00"
                plan_name = "Standard Plan"
            else:
                amount = "200.00"
                plan_name = "Premium Plan"
            
            # Create mock order ID
            mock_order_id = f"MOCK_ORDER_{church_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Create mock approval URL
            mock_approval_url = f"https://www.sandbox.paypal.com/checkoutnow?token={mock_order_id}"
            
            return {
                'success': True,
                'subscription_id': mock_order_id,
                'approval_url': mock_approval_url,
                'amount': amount,
                'plan_name': plan_name,
                'mock_service': True,
                'message': 'This is a mock PayPal response for development. Replace with real PayPal credentials.'
            }
                
        except Exception as e:
            return {
                'success': False, 
                'error': f'Mock PayPal error: {str(e)}',
                'mock_service': True
            }
    
    def capture_payment(self, order_id):
        """
        Mock payment capture
        """
        return {
            'success': True,
            'payment_id': f'MOCK_PAYMENT_{order_id}',
            'status': 'COMPLETED',
            'amount': '100.00',
            'mock_service': True
        }
    
    def get_order_details(self, order_id):
        """
        Mock order details
        """
        return {
            'success': True,
            'order': {
                'id': order_id,
                'status': 'APPROVED',
                'amount': {
                    'currency_code': 'USD',
                    'value': '150.00'
                },
                'mock_service': True
            }
        }
    
    def process_webhook(self, webhook_data):
        """
        Mock webhook processing
        """
        return {
            'success': True,
            'message': 'Mock webhook processed',
            'mock_service': True
        }