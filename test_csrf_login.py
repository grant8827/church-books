#!/usr/bin/env python3
"""
Test script to verify CSRF login functionality
"""
import requests
from bs4 import BeautifulSoup
import re

def test_csrf_login():
    base_url = 'http://127.0.0.1:8000'
    login_url = f'{base_url}/finances/login/'
    
    # Create a session to maintain cookies
    session = requests.Session()
    
    print("Testing CSRF login functionality...")
    print(f"Requesting login page: {login_url}")
    
    # Get the login page
    response = session.get(login_url)
    print(f"Login page status: {response.status_code}")
    
    if response.status_code != 200:
        print(f"Error: Could not access login page. Status code: {response.status_code}")
        return
    
    # Parse the HTML to extract CSRF token
    soup = BeautifulSoup(response.content, 'html.parser')
    csrf_token = soup.find('input', {'name': 'csrfmiddlewaretoken'})
    
    if csrf_token:
        csrf_value = csrf_token.get('value')
        print(f"✓ CSRF token found: {csrf_value[:20]}...")
    else:
        print("✗ CSRF token not found in form")
        return
    
    # Check for CSRF meta tag
    csrf_meta = soup.find('meta', {'name': 'csrf-token'})
    if csrf_meta:
        meta_value = csrf_meta.get('content')
        print(f"✓ CSRF meta tag found: {meta_value[:20]}...")
    else:
        print("✗ CSRF meta tag not found")
    
    # Test login with invalid credentials to verify CSRF is working
    login_data = {
        'username': 'testuser',
        'password': 'wrongpassword',
        'csrfmiddlewaretoken': csrf_value
    }
    
    print("\nTesting login with invalid credentials...")
    login_response = session.post(login_url, data=login_data)
    print(f"Login attempt status: {login_response.status_code}")
    
    if login_response.status_code == 200:
        print("✓ CSRF verification passed (form processed)")
        if 'Enter a valid username and password' in login_response.text or 'Invalid' in login_response.text:
            print("✓ Authentication failed as expected (wrong password)")
        else:
            print("? Unexpected response content")
    elif login_response.status_code == 403:
        print("✗ CSRF verification failed!")
    else:
        print(f"? Unexpected status code: {login_response.status_code}")
    
    print("\nCSRF test completed.")

if __name__ == '__main__':
    test_csrf_login()
