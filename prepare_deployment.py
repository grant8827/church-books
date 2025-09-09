#!/usr/bin/env python3
"""
Final deployment preparation script for Railway
"""
import os
import subprocess
import sys

def run_command(command, description):
    """Run a command and return its result"""
    print(f"\n🔄 {description}...")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=os.getcwd())
        if result.returncode == 0:
            print(f"✅ {description} - SUCCESS")
            return True
        else:
            print(f"❌ {description} - FAILED")
            print(f"Error: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ {description} - ERROR: {e}")
        return False

def main():
    print("🚀 Railway Deployment Preparation")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not os.path.exists('manage.py'):
        print("❌ Error: manage.py not found. Please run this script from your Django project root.")
        sys.exit(1)
    
    checks_passed = 0
    total_checks = 4
    
    # 1. Check for migrations
    if run_command("python manage.py makemigrations --dry-run", "Checking for pending migrations"):
        checks_passed += 1
    
    # 2. Run Django system check
    if run_command("python manage.py check", "Running Django system check"):
        checks_passed += 1
    
    # 3. Collect static files
    if run_command("python manage.py collectstatic --noinput", "Collecting static files"):
        checks_passed += 1
    
    # 4. Test Django configuration
    if run_command("python manage.py shell -c 'from church_finances.models import Church; print(\"Models imported successfully\")'", "Testing Django configuration"):
        checks_passed += 1
    
    print("\n" + "=" * 50)
    print(f"📊 Deployment Check Results: {checks_passed}/{total_checks} passed")
    
    if checks_passed == total_checks:
        print("🎉 ALL CHECKS PASSED! Your app is ready for Railway deployment!")
        print("\n📋 Next Steps:")
        print("1. Commit your changes: git add . && git commit -m 'Ready for deployment'")
        print("2. Push to GitHub: git push origin main")
        print("3. Deploy to Railway with the environment variables from DEPLOYMENT_SUMMARY.md")
        print("4. Use this SECRET_KEY for production:")
        from django.core.management.utils import get_random_secret_key
        print(f"   SECRET_KEY={get_random_secret_key()}")
    else:
        print("⚠️  Some checks failed. Please review the errors above before deploying.")
        sys.exit(1)

if __name__ == '__main__':
    main()
