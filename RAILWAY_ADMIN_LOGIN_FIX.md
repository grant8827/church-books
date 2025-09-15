# 🚨 Railway Admin Login Troubleshooting Guide

## Issue: Unable to login to admin after Railway deployment

### 🔍 Diagnosis Steps

#### Step 1: Check Admin URL
Your admin is using a custom admin site. Make sure you're accessing:
- **Production**: `https://your-app.up.railway.app/admin/`
- **NOT**: `https://your-app.up.railway.app/django-admin/` (default Django admin)

#### Step 2: Verify Database Connection in Production
Use the debug endpoint to check database status:
```
https://your-app.up.railway.app/debug/database/?debug_key=railway_db_debug_2025
```

#### Step 3: Check User Accounts in Production
Use the auth debug endpoint:
```
https://your-app.up.railway.app/debug/auth/?debug_key=railway_auth_debug_2025
```

## 🛠️ Common Solutions

### Solution 1: Create Superuser in Production Database

The local database and Railway database are separate. You need to create a superuser in the Railway database:

1. **Access Railway Console**:
   - Go to https://railway.app/dashboard
   - Select your project
   - Click on your Django service
   - Go to "Console" tab

2. **Create Superuser**:
   ```bash
   python manage.py createsuperuser
   ```

3. **Enter details**:
   - Username: `admin`
   - Email: `your-email@gmail.com`
   - Password: [choose a strong password]

### Solution 2: Verify Environment Variables

Check if Railway has the correct environment variables:

1. **Go to Railway Dashboard** → Your Service → **Variables**
2. **Verify these are set**:
   ```
   DATABASE_URL=postgresql://...
   SECRET_KEY=your-secret-key
   DEBUG=False
   ALLOWED_HOSTS=*.up.railway.app,your-domain.com
   ```

### Solution 3: Check Database Migrations

Ensure all migrations were applied in production:

1. **Railway Console**:
   ```bash
   python manage.py showmigrations
   ```

2. **If migrations missing**:
   ```bash
   python manage.py migrate
   ```

### Solution 4: Check Static Files

If admin CSS/JS is broken:

1. **Railway Console**:
   ```bash
   python manage.py collectstatic --noinput
   ```

## 🔧 Debug Commands for Railway Console

Access Railway Console and run these commands:

### Check Database Connection
```bash
python manage.py check --database default
```

### List All Users
```bash
python manage.py shell -c "from django.contrib.auth.models import User; [print(f'User: {u.username}, Email: {u.email}, Superuser: {u.is_superuser}') for u in User.objects.all()]"
```

### Create Superuser if None Exist
```bash
python manage.py createsuperuser --username admin --email your-email@gmail.com
```

### Test Admin Site
```bash
python manage.py shell -c "from church_finances.admin_site import church_admin_site; print('Admin site URL:', church_admin_site.name)"
```

## 🌐 Access URLs

After creating superuser, try these URLs:

1. **Main Admin** (Custom):
   ```
   https://your-app.up.railway.app/admin/
   ```

2. **Health Check**:
   ```
   https://your-app.up.railway.app/healthz
   ```

3. **Database Debug** (temporary):
   ```
   https://your-app.up.railway.app/debug/database/?debug_key=railway_db_debug_2025
   ```

## 🚨 Emergency Admin Access

If custom admin isn't working, you can temporarily enable Django's default admin:

1. **Add to urls.py** (temporarily):
   ```python
   from django.contrib import admin
   
   urlpatterns = [
       path('django-admin/', admin.site.urls),  # Add this line
       path('admin/', church_admin_site.urls),
       # ... rest of URLs
   ]
   ```

2. **Access default admin**:
   ```
   https://your-app.up.railway.app/django-admin/
   ```

## 🔍 Common Error Messages & Solutions

### "CSRF verification failed"
- **Cause**: CSRF settings issue
- **Solution**: Verify CSRF_TRUSTED_ORIGINS in settings

### "Invalid login credentials"
- **Cause**: No superuser in production database
- **Solution**: Create superuser via Railway console

### "Server Error (500)"
- **Cause**: Database connection or static files issue
- **Solution**: Check debug endpoints and Railway logs

### "Page not found (404)"
- **Cause**: Wrong admin URL
- **Solution**: Use `/admin/` not `/django-admin/`

## 📊 Expected Workflow

1. ✅ **Create superuser** in Railway console
2. ✅ **Verify database** connection via debug endpoint
3. ✅ **Access admin** at `https://your-app.up.railway.app/admin/`
4. ✅ **Login** with created credentials
5. ✅ **Remove debug endpoints** after fixing

## ⚡ Quick Fix Commands

Run these in Railway Console:

```bash
# 1. Check if database is connected
python manage.py check --database default

# 2. Apply any missing migrations
python manage.py migrate

# 3. Create superuser
python manage.py createsuperuser

# 4. Collect static files
python manage.py collectstatic --noinput

# 5. Test admin access
python manage.py shell -c "from django.contrib.auth.models import User; print('Superusers:', User.objects.filter(is_superuser=True).count())"
```

After running these commands, you should be able to access the admin panel!

---

**Most likely cause**: No superuser account exists in the Railway production database. Create one using the Railway console and you should be able to login.