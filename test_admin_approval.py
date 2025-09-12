#!/usr/bin/env python
import os
import sys
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'church_finance_project.settings')
django.setup()

from django.contrib.auth.models import User
from church_finances.models import Church, ChurchMember

def test_admin_approval():
    print("Testing admin approval functionality...")
    
    # Test 1: Check if test pending church exists
    try:
        test_church = Church.objects.get(name="Test Community Church")
        print(f"✓ Test church found: {test_church.name}")
        print(f"  - Is approved: {test_church.is_approved}")
        print(f"  - Subscription status: {test_church.subscription_status}")
    except Church.DoesNotExist:
        print("✗ Test church not found")
        return False
    
    # Test 2: Check if test user exists and is inactive
    try:
        test_user = User.objects.get(username="testchurch")
        print(f"✓ Test user found: {test_user.username}")
        print(f"  - Is active: {test_user.is_active}")
        print(f"  - Is superuser: {test_user.is_superuser}")
    except User.DoesNotExist:
        print("✗ Test user not found")
        return False
    
    # Test 3: Check if test member exists
    try:
        test_member = ChurchMember.objects.get(user=test_user)
        print(f"✓ Test member found: {test_member.user.username}")
        print(f"  - Is active: {test_member.is_active}")
        print(f"  - Role: {test_member.role}")
        print(f"  - Church: {test_member.church.name}")
    except ChurchMember.DoesNotExist:
        print("✗ Test member not found")
        return False
    
    # Test 4: Simulate approval process
    print("\n--- Simulating Approval Process ---")
    
    # Approve church
    test_church.is_approved = True
    test_church.subscription_status = 'active'
    test_church.save()
    print(f"✓ Church approved: {test_church.is_approved}")
    
    # Activate user
    test_user.is_active = True
    test_user.save()
    print(f"✓ User activated: {test_user.is_active}")
    
    # Activate member
    test_member.is_active = True
    test_member.save()
    print(f"✓ Member activated: {test_member.is_active}")
    
    print("\n--- Testing Admin Access Function ---")
    from church_finances.views import is_superadmin
    
    # Test admin function with regular user
    print(f"✓ is_superadmin(test_user): {is_superadmin(test_user)}")
    
    # Test with actual superuser
    try:
        admin_user = User.objects.filter(is_superuser=True).first()
        if admin_user:
            print(f"✓ is_superadmin(admin_user): {is_superadmin(admin_user)}")
        else:
            print("! No superuser found in database")
    except Exception as e:
        print(f"✗ Error testing admin user: {e}")
    
    print("\n--- All Tests Complete ---")
    return True

if __name__ == "__main__":
    test_admin_approval()
