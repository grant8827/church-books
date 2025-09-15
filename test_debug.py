#!/usr/bin/env python
import os
import sys
import django
from django.http import HttpRequest

# Add the project directory to Python path
sys.path.append('/Users/gregorygrant/Desktop/Websites/Python/Django Web App/church-books')

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'church_finance_project.settings')
django.setup()

# Now import Django modules
from church_finances.debug_paypal import debug_paypal_config

# Create a fake request
request = HttpRequest()
request.method = 'GET'
request.GET = {'debug_key': 'paypal_debug_2025'}

# Test the function
response = debug_paypal_config(request)
print("Status Code:", response.status_code)
print("Content:", response.content.decode('utf-8'))