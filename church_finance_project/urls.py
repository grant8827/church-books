"""
URL configuration for church_finance_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView # For a simple home page
from church_finances.admin_site import church_admin_site
from church_finances.views_health import health_check
from church_finances.railway_health import railway_health_check
from church_finances.railway_db_health import railway_db_health_check, railway_env_debug
from church_finances.debug_views import debug_database, debug_auth
from church_finances.debug_paypal import debug_paypal_config

urlpatterns = [
    path('admin/', church_admin_site.urls),
    path('accounts/', include('django.contrib.auth.urls')), # Django's built-in auth URLs
    path('', TemplateView.as_view(template_name='home.html'), name='home'), # Simple home page
    path('finances/', include('church_finances.urls')), # Include your app's URLs
    path('health/', health_check, name='health_check'), # Health check endpoint
    path('healthz', railway_health_check, name='railway_health'), # Railway-specific health check
    path('health/db/', railway_db_health_check, name='railway_db_health'), # Database health check
    path('debug/env/', railway_env_debug, name='railway_env_debug'), # Environment debug (dev only)
    path('debug/database/', debug_database, name='debug_database'), # Database debug endpoint
    path('debug/auth/', debug_auth, name='debug_auth'), # Auth system debug endpoint
    path('debug/paypal/', debug_paypal_config, name='debug_paypal'), # PayPal configuration debug endpoint
]
