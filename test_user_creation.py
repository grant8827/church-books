#!/usr/bin/env python3
import os
import django
from django.test import Client

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'church_finance_project.settings')
django.setup()

from django.contrib.auth.models import User

def test_user_creation():
    print("Starting user creation test...")
    
    # Create a test client
    client = Client()

    # First, let's select a package to set up the session
    response = client.post('/finances/subscription/select/', {
        'package': 'standard',
        'payment_method': 'paypal'
    })
    print(f'Package selection response: {response.status_code}')
    
    if response.status_code == 302:
        print("Package selection successful, redirected to subscription form")
    
    # Now submit the subscription form with username and password
    test_data = {
        'first_name': 'John',
        'last_name': 'Doe',
        'email': 'john.doe@testchurch.com',
        'username': 'johndoe',
        'password': 'password123',
        'password_confirm': 'password123',
        'church_name': 'Test Church',
        'church_address': '123 Test Street',
        'church_phone': '555-1234',
        'church_email': 'info@testchurch.com',
        'church_website': 'https://testchurch.com'
    }

    print('Submitting form with test data...')
    
    # Get initial user count
    initial_count = User.objects.count()
    print(f'Initial user count: {initial_count}')
    
    response = client.post('/finances/paypal/create-subscription/', test_data)
    print(f'Form submission response: {response.status_code}')
    
    if hasattr(response, 'url'):
        print(f'Redirect URL: {response.url}')

    # Check if user was created
    final_count = User.objects.count()
    print(f'Final user count: {final_count}')
    
    if final_count > initial_count:
        print("✅ User was created successfully!")
        new_user = User.objects.get(username='johndoe')
        print(f"New user: {new_user.username}, Email: {new_user.email}, Active: {new_user.is_active}")
    else:
        print("❌ No new user was created")
    
    # List all users
    users = User.objects.all()
    print(f'\nAll users ({users.count()}):')
    for user in users:
        print(f'  - Username: {user.username}, Email: {user.email}, Active: {user.is_active}')

if __name__ == "__main__":
    test_user_creation()
