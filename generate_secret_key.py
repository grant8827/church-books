#!/usr/bin/env python3
"""
Generate a secure secret key for Django production deployment
"""
from django.core.management.utils import get_random_secret_key

if __name__ == '__main__':
    print("🔐 Generated SECRET_KEY for production:")
    print(f"SECRET_KEY={get_random_secret_key()}")
    print("\n💡 Copy this value to your Railway environment variables!")
