# Railway Deployment Guide

This guide will help you deploy your Django Church Finance application to Railway with a MySQL database.

## Prerequisites

1. A Railway account (sign up at https://railway.app)
2. Your code pushed to a GitHub repository
3. Railway CLI installed (optional but recommended)

## Deployment Steps

### 1. Create a New Railway Project

1. Go to https://railway.app/new
2. Select "Deploy from GitHub repo"
3. Connect your GitHub account and select your repository
4. Railway will automatically detect your Django app

### 2. Add MySQL Database

1. In your Railway project dashboard, click "New Service"
2. Select "Database" → "MySQL"
3. Railway will provision a MySQL database and provide connection details

### 3. Configure Environment Variables

In your Railway project settings, add these environment variables:

```
SECRET_KEY=your-production-secret-key-here
DEBUG=False
ALLOWED_HOSTS=your-app-name.railway.app
CSRF_TRUSTED_ORIGINS=https://your-app-name.railway.app
```

**Important:** Railway will automatically provide the `DATABASE_URL` environment variable for MySQL.

### 4. Generate a New Secret Key

Run this command locally to generate a new secret key:

```python
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copy the output and use it as your `SECRET_KEY` environment variable.

### 5. Deploy

1. Push your code to GitHub
2. Railway will automatically deploy your application
3. The first deployment may take a few minutes as it installs dependencies

### 6. Run Initial Setup

After deployment, you may need to create a superuser account. You can do this using Railway's terminal:

1. Go to your project dashboard
2. Click on your web service
3. Go to the "Settings" tab
4. Scroll down to find the "One-click Commands" or use the terminal
5. Run: `python manage.py createsuperuser`

## Local Development with MySQL (Optional)

If you want to test with MySQL locally:

1. Install MySQL on your local machine
2. Create a `.env` file based on `.env.example`
3. Set your local MySQL credentials in the `.env` file

## Troubleshooting

### Common Issues:

1. **Static files not loading**: Make sure `STATIC_ROOT` is set and `collectstatic` is run during deployment
2. **Database connection errors**: Check that `DATABASE_URL` is properly set by Railway
3. **CSRF errors**: Ensure `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` include your Railway domain

### Useful Commands:

```bash
# Check logs
railway logs

# Run migrations manually
railway run python manage.py migrate

# Create superuser
railway run python manage.py createsuperuser

# Collect static files
railway run python manage.py collectstatic
```

## Security Notes

- Never commit your `.env` file to version control
- Use strong, unique secret keys for production
- Enable HTTPS in production (Railway provides this automatically)
- Regularly update your dependencies for security patches

## Support

For Railway-specific issues, check:
- Railway Documentation: https://docs.railway.app/
- Railway Discord: https://discord.gg/railway
