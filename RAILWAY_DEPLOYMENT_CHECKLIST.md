# 🚀 Railway PostgreSQL Fix - Deployment Checklist

## Current Issue: PostgreSQL Not Working in Production

**Problem**: Backend not connected to database in Railway, causing login failures.

## Step-by-Step Solution

### Step 1: Check Railway PostgreSQL Service

1. **Login to Railway Dashboard**: https://railway.app/dashboard
2. **Navigate to your project**: church-books
3. **Check Services**: You should see:
   - ✅ **Django App Service** (your main application)
   - ✅ **PostgreSQL Service** (database)

### Step 2: Add PostgreSQL Service (if missing)

If PostgreSQL service is missing:
1. Click **"New Service"**
2. Select **"Database"** 
3. Choose **"PostgreSQL"**
4. Railway will automatically provision the database

### Step 3: Verify Environment Variables

In Railway dashboard, go to your **Django app service** → **Variables** tab.

#### Required Variables (Railway automatically sets these):
```bash
DATABASE_URL=postgresql://postgres:password@host:port/railway
```

#### Alternative Variables (if DATABASE_URL missing):
```bash
PGHOST=your-postgresql-host.railway.app
PGPORT=5432
PGDATABASE=railway
PGUSER=postgres
PGPASSWORD=your-generated-password
```

### Step 4: Set Missing Environment Variables

If variables are missing, add them manually:

#### Method A: Railway Web Interface
1. Go to your Django service
2. Click **"Variables"** tab
3. Click **"Add Variable"**
4. Add these one by one:

```bash
# Primary database connection (Railway should provide this)
DATABASE_URL=postgresql://postgres:PASSWORD@HOST:5432/railway

# Backup individual variables
PGHOST=your-host.railway.app
PGPORT=5432
PGDATABASE=railway
PGUSER=postgres
PGPASSWORD=your-password

# Django settings
SECRET_KEY=qjje4s-^(m9)+f%6jgfy%d92hwfhm08%u465=(y-0)xtcybm1*
DEBUG=False
ALLOWED_HOSTS=*.up.railway.app,churchbooksmanagement.com
```

#### Method B: Railway CLI
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and link to your project
railway login
railway link

# Set environment variables
railway variables set DATABASE_URL=postgresql://postgres:password@host:port/railway
railway variables set PGHOST=your-host
railway variables set PGPORT=5432
railway variables set PGDATABASE=railway
railway variables set PGUSER=postgres
railway variables set PGPASSWORD=your-password
```

### Step 5: Get Actual Database Credentials

To get the real database credentials:

1. **Go to PostgreSQL service** in Railway dashboard
2. **Click "Variables" tab**
3. **Copy the values** of:
   - `PGHOST`
   - `PGPORT` 
   - `PGDATABASE`
   - `PGUSER`
   - `PGPASSWORD`
   - `DATABASE_URL`

4. **Set these in your Django app service**

### Step 6: Connect Services

1. **In Railway dashboard**, go to your Django app service
2. **Click "Settings" tab**
3. **Look for "Service Connections"** or **"Connect"**
4. **Connect to PostgreSQL service** if not already connected

### Step 7: Update Code for Railway

The current `settings.py` is already configured to handle Railway, but let's verify:

```python
# This code is already in your settings.py and should work
database_url = os.getenv('DATABASE_URL')
if not database_url:
    # Fallback to individual variables
    db_host = os.getenv('PGHOST') or os.getenv('POSTGRES_HOST')
    # ... etc
```

### Step 8: Debug in Production

Use the debug endpoints to diagnose the issue:

1. **Database Debug**: `https://churchbooksmanagement.com/debug/database/?debug_key=railway_db_debug_2025`
2. **Auth Debug**: `https://churchbooksmanagement.com/debug/auth/?debug_key=railway_auth_debug_2025`

**Remove these endpoints after fixing the issue for security!**

### Step 9: Deploy and Test

1. **Trigger Deployment**:
   - Make any small change to trigger redeploy
   - Or use Railway CLI: `railway up`

2. **Check Deployment Logs**:
   - Go to Railway dashboard → your Django service → "Deployments"
   - Look for database connection messages in logs

3. **Test Endpoints**:
   - Health check: `https://churchbooksmanagement.com/healthz`
   - Admin login: `https://churchbooksmanagement.com/admin/`
   - App login: `https://churchbooksmanagement.com/finances/login/`

### Step 10: Verify Database Connection

Expected log messages in Railway deployment:
```
✅ Using DATABASE_URL for database connection
✅ Database: railway @ your-host.railway.app
✅ System check identified no issues
```

## Common Railway PostgreSQL Issues & Solutions

### Issue 1: No PostgreSQL Service
**Solution**: Add PostgreSQL service in Railway dashboard

### Issue 2: Services Not Connected
**Solution**: Connect Django app to PostgreSQL service in Railway

### Issue 3: Missing DATABASE_URL
**Solution**: Set DATABASE_URL manually with correct credentials

### Issue 4: Wrong Environment Variable Names
**Solution**: Use Railway's standard names (PGHOST, PGPORT, etc.)

### Issue 5: SSL Connection Issues
**Solution**: Already handled in settings with `sslmode: 'prefer'`

## Expected Results After Fix

1. ✅ **Health Check Works**: `/healthz` returns "OK"
2. ✅ **Admin Login Works**: Can login to `/admin/`
3. ✅ **User Login Works**: Can login to `/finances/login/`
4. ✅ **Database Operations**: All CRUD operations functional
5. ✅ **No Connection Errors**: Clean deployment logs

## Security Notes

- **Remove debug endpoints** after fixing the issue
- **Keep environment variables secure** in Railway dashboard
- **Don't commit credentials** to version control
- **Use Railway's generated credentials** rather than custom ones

## Troubleshooting Commands

If the issue persists, run these in Railway logs:

```bash
# Check if database is accessible
python manage.py check --database default

# Test migrations
python manage.py showmigrations

# Create superuser (if needed)
python manage.py createsuperuser
```

## Final Verification

After implementing the fix:

1. **Test Admin Login**: https://churchbooksmanagement.com/admin/
2. **Test User Registration**: https://churchbooksmanagement.com/finances/register/
3. **Test Subscription Flow**: https://churchbooksmanagement.com/finances/subscription/
4. **Check Database Debug**: Use debug endpoint temporarily

**The PostgreSQL connection should now be working in Railway production!** 🎉