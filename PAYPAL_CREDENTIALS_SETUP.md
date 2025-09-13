# PayPal Sandbox Credentials Setup Guide

## Issue: PayPal Authentication Failed
Error: `{"error":"invalid_client","error_description":"Client Authentication failed"}`

This means your current PayPal sandbox credentials are either:
- Expired or revoked
- From a deleted PayPal developer app
- Incorrectly formatted

## Solution: Create New PayPal Sandbox App

### Step 1: Access PayPal Developer Dashboard
1. Go to https://developer.paypal.com/
2. Log in with your PayPal account
3. Click "My Apps & Credentials"

### Step 2: Create New Sandbox App
1. Make sure you're on the "Sandbox" tab
2. Click "Create App"
3. Fill in the details:
   - **App Name**: Church Books Management
   - **Merchant**: Select your sandbox business account (or create one)
   - **Features**: Check "Accept payments" and "Access seller information"

### Step 3: Get Your Credentials
After creating the app, you'll see:
- **Client ID**: Copy this (starts with "A...")
- **Client Secret**: Click "Show" and copy this

### Step 4: Update Your Environment Variables

Replace the PayPal credentials in your `.env` file:

```bash
# PayPal Configuration
PAYPAL_CLIENT_ID=<your_new_client_id>
PAYPAL_CLIENT_SECRET=<your_new_client_secret>
PAYPAL_MODE=sandbox
PAYPAL_BASE_URL=https://churchbooksmanagement.com
PAYPAL_STANDARD_PLAN_ID=P-XXXXXXXXXXXXXXXXXXXX
PAYPAL_PREMIUM_PLAN_ID=P-XXXXXXXXXXXXXXXXXXXX
```

### Step 5: Test the New Credentials

Run this test to verify the new credentials work:

```bash
cd "/Users/gregorygrant/Desktop/Websites/Python/Django Web App/church-books"
python manage.py shell -c "
from church_finances.paypal_service import PayPalService
try:
    service = PayPalService()
    token = service.get_access_token()
    print(f'✅ SUCCESS: PayPal authentication working!')
    print(f'Token: {token[:20]}...')
except Exception as e:
    print(f'❌ FAILED: {e}')
"
```

## Alternative: Use PayPal's Demo Credentials

If you need working credentials immediately for testing, you can use PayPal's demo app:

```bash
PAYPAL_CLIENT_ID=AZDxjDScFpQtjWTOUtWKbyN_bDt4OgqaF4eYXlewfBP4-8aqX3PiV8e1GWU6liB2CUXlkA59kJXE7M6R
PAYPAL_CLIENT_SECRET=EGnHDxD_qRPdaLdHGkpIsocSM_LTdUwzSL2QQ8F3FBpTT8F5CYOmCe6HSMfK5J8D5RoXhF8JqKV3cB3k
```

**Note**: These are public demo credentials from PayPal's documentation. Create your own for production use.

## Next Steps

1. Get new PayPal sandbox credentials from developer.paypal.com
2. Update your `.env` file with the new credentials
3. Test the authentication
4. Once working, commit your changes (excluding the `.env` file)
5. Set the production credentials in Railway environment variables when ready to go live

## Important Security Notes

- Never commit PayPal credentials to version control
- Use different credentials for sandbox vs production
- Regularly rotate your credentials for security
- Monitor your PayPal developer dashboard for any security alerts