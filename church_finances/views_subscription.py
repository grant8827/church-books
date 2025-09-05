from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings

def subscription_view(request):
    """
    Display subscription packages
    """
    return render(request, "church_finances/subscription.html")

def subscription_select(request):
    """
    Handle subscription package selection
    """
    if request.method == "POST":
        package = request.POST.get('package')
        if package in ['standard', 'premium']:
            request.session['selected_package'] = package
            request.session['package_price'] = '10000' if package == 'standard' else '15000'
            messages.success(request, f"You have selected the {package.title()} package. Please proceed with registration.")
            return redirect('register')
        else:
            messages.error(request, "Invalid package selection.")
    return redirect('subscription')
