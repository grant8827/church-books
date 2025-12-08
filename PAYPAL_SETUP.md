# PayPal Integration Setup Guide

## Step 1: Get PayPal Credentials

### For Testing (Sandbox):
1. Go to https://developer.paypal.com/
2. Sign in with your PayPal account
3. Go to "My Apps & Credentials"
4. Click "Create App"
5. Fill in:
   - App Name: "Church Books App"
   - Select your sandbox business account
   - Features: Check "Subscriptions"
6. Click "Create App"
7. Copy the Client ID and Client Secret

### For Production (Live):
1. Switch to "Live" in the PayPal Developer Dashboard
2. Create a new app for live environment
3. Get live Client ID and Client Secret

## Step 2: Update .env File

Replace the placeholder values in your `.env` file:

```
PAYPAL_CLIENT_ID=your_actual_client_id_from_paypal
PAYPAL_CLIENT_SECRET=your_actual_client_secret_from_paypal
PAYPAL_MODE=sandbox
```

For production, change `PAYPAL_MODE=live`

## Step 3: Create Subscription Plans

### Option A: Use the Setup Script
1. Update your .env file with real credentials
2. Run: `python3 setup_paypal_plans.py`
3. Copy the Plan IDs to your .env file

### Option B: Manual Setup via PayPal Dashboard
1. Go to PayPal Developer Dashboard
2. Go to "Subscriptions" > "Plans"
3. Create two plans:
   - Standard Plan: $150/year
   - Premium Plan: $200/year
4. Copy the Plan IDs to your .env file

## Step 4: Configure Webhooks

1. In PayPal Developer Dashboard, go to your app
2. Click "Add Webhook"
3. Set Webhook URL to: `https://yourdomain.com/finances/paypal/webhook/`
4. Select these events:
   - BILLING.SUBSCRIPTION.ACTIVATED
   - BILLING.SUBSCRIPTION.CANCELLED
   - BILLING.SUBSCRIPTION.SUSPENDED
   - PAYMENT.SALE.COMPLETED

## Step 5: Test the Integration

1. Run your Django server: `python3 manage.py runserver`
2. Go to: http://127.0.0.1:8000/finances/subscription/
3. Select a plan and test with PayPal sandbox accounts

## Production Deployment

When deploying to Railway or another platform:

1. Set environment variables in your hosting platform
2. Change `PAYPAL_MODE=live`
3. Use live PayPal credentials
4. Update webhook URL to your live domain
5. Test thoroughly with small amounts first

## Security Notes

- Never commit credentials to version control
- Use environment variables for all sensitive data
- Test thoroughly in sandbox before going live
- Monitor webhook events for any issues
