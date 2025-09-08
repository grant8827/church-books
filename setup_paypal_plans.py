#!/usr/bin/env python3
"""
PayPal Subscription Plan Setup Script
Run this script to create subscription plans in PayPal
"""

import paypalrestsdk
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure PayPal SDK
paypalrestsdk.configure({
    "mode": os.getenv('PAYPAL_MODE', 'sandbox'),  # sandbox or live
    "client_id": os.getenv('PAYPAL_CLIENT_ID'),
    "client_secret": os.getenv('PAYPAL_CLIENT_SECRET')
})

def create_standard_plan():
    """Create Standard Plan ($100/year)"""
    plan = paypalrestsdk.BillingPlan({
        "name": "Church Books Standard Plan",
        "description": "Standard church management features - $100/year",
        "type": "INFINITE",
        "payment_definitions": [{
            "name": "Standard Subscription",
            "type": "REGULAR",
            "frequency": "Year",
            "frequency_interval": "1",
            "amount": {
                "value": "100",
                "currency": "USD"
            },
            "cycles": "0"  # Infinite cycles
        }],
        "merchant_preferences": {
            "auto_bill_amount": "YES",
            "cancel_url": f"{os.getenv('PAYPAL_BASE_URL')}/finances/subscription/cancel/",
            "return_url": f"{os.getenv('PAYPAL_BASE_URL')}/finances/subscription/success/",
            "initial_fail_amount_action": "CANCEL",
            "max_fail_attempts": "1"
        }
    })
    
    if plan.create():
        print(f"Standard Plan created successfully!")
        print(f"Plan ID: {plan.id}")
        
        # Activate the plan
        if plan.activate():
            print("Standard Plan activated!")
            return plan.id
        else:
            print(f"Error activating plan: {plan.error}")
    else:
        print(f"Error creating plan: {plan.error}")
    
    return None

def create_premium_plan():
    """Create Premium Plan ($150/year)"""
    plan = paypalrestsdk.BillingPlan({
        "name": "Church Books Premium Plan",
        "description": "Premium church management features - $150/year",
        "type": "INFINITE",
        "payment_definitions": [{
            "name": "Premium Subscription",
            "type": "REGULAR",
            "frequency": "Year",
            "frequency_interval": "1",
            "amount": {
                "value": "150",
                "currency": "USD"
            },
            "cycles": "0"  # Infinite cycles
        }],
        "merchant_preferences": {
            "auto_bill_amount": "YES",
            "cancel_url": f"{os.getenv('PAYPAL_BASE_URL')}/finances/subscription/cancel/",
            "return_url": f"{os.getenv('PAYPAL_BASE_URL')}/finances/subscription/success/",
            "initial_fail_amount_action": "CANCEL",
            "max_fail_attempts": "1"
        }
    })
    
    if plan.create():
        print(f"Premium Plan created successfully!")
        print(f"Plan ID: {plan.id}")
        
        # Activate the plan
        if plan.activate():
            print("Premium Plan activated!")
            return plan.id
        else:
            print(f"Error activating plan: {plan.error}")
    else:
        print(f"Error creating plan: {plan.error}")
    
    return None

if __name__ == "__main__":
    print("Creating PayPal Subscription Plans...")
    print("Make sure you have set your PayPal credentials in .env file")
    print()
    
    # Check if credentials are set
    if not os.getenv('PAYPAL_CLIENT_ID') or os.getenv('PAYPAL_CLIENT_ID') == 'your_paypal_client_id_here':
        print("❌ Please set your PAYPAL_CLIENT_ID in .env file first!")
        exit(1)
    
    if not os.getenv('PAYPAL_CLIENT_SECRET') or os.getenv('PAYPAL_CLIENT_SECRET') == 'your_paypal_client_secret_here':
        print("❌ Please set your PAYPAL_CLIENT_SECRET in .env file first!")
        exit(1)
    
    print("Creating Standard Plan...")
    standard_plan_id = create_standard_plan()
    
    print("\nCreating Premium Plan...")
    premium_plan_id = create_premium_plan()
    
    print("\n" + "="*50)
    print("IMPORTANT: Update your .env file with these Plan IDs:")
    print("="*50)
    if standard_plan_id:
        print(f"PAYPAL_STANDARD_PLAN_ID={standard_plan_id}")
    if premium_plan_id:
        print(f"PAYPAL_PREMIUM_PLAN_ID={premium_plan_id}")
    print("="*50)
