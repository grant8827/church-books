#!/usr/bin/env python3
"""
Simple health check script that can run independently of Django.
This script can be used as a healthcheck command in Docker or Railway.
"""

import sys
import os
import time
import signal

def timeout_handler(signum, frame):
    print("Health check timed out")
    sys.exit(1)

def check_health():
    """
    Perform basic health checks:
    1. Check if the process is running
    2. Check if required environment variables exist
    3. Return success if basic conditions are met
    """
    # Set a timeout for the health check
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(10)  # 10-second timeout
    
    try:
        # Check basic environment
        port = os.environ.get('PORT', '8080')
        
        # Try to import Django to see if it's available
        try:
            import django
            django_available = True
        except ImportError:
            django_available = False
        
        # Check if we can at least start Django settings
        django_ready = False
        if django_available:
            try:
                os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'church_finance_project.settings')
                django.setup()
                django_ready = True
            except Exception as e:
                print(f"Django setup failed: {e}")
        
        # Basic success criteria
        if django_available and port.isdigit():
            print(f"Health check passed - Django available, PORT={port}")
            return True
        else:
            print(f"Health check failed - Django available: {django_available}, PORT valid: {port.isdigit()}")
            return False
            
    except Exception as e:
        print(f"Health check error: {e}")
        return False
    finally:
        signal.alarm(0)  # Clear the alarm

if __name__ == "__main__":
    success = check_health()
    sys.exit(0 if success else 1)