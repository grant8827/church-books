"""
Custom password reset views to bypass potential Django issues
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.forms import SetPasswordForm
from django.utils.http import urlsafe_base64_decode
from django.contrib import messages
from django.urls import reverse

def custom_password_reset_confirm(request, uidb64, token):
    """Custom password reset confirmation view"""
    try:
        # Decode the uidb64 to get user ID
        uid = urlsafe_base64_decode(uidb64).decode()
        user = get_object_or_404(User, pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    # Check if user exists and token is valid
    if user is not None and default_token_generator.check_token(user, token):
        validlink = True
        
        if request.method == 'POST':
            form = SetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()
                # Auto-login the user after password reset
                from django.contrib.auth import login
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, 'Your password has been reset successfully! You are now logged in.')
                return redirect('password_reset_complete')
        else:
            form = SetPasswordForm(user)
    else:
        validlink = False
        form = None
        
        # Debug information
        debug_info = {
            'user_found': user is not None,
            'token_valid': default_token_generator.check_token(user, token) if user else False,
            'uidb64': uidb64,
            'token': token,
            'user_id': uid if user else 'N/A'
        }
        
        # Add debug info to context for debugging
        return render(request, 'church_finances/password_reset/custom_password_reset_confirm.html', {
            'validlink': validlink,
            'form': form,
            'debug_info': debug_info
        })

    return render(request, 'church_finances/password_reset/custom_password_reset_confirm.html', {
        'validlink': validlink,
        'form': form
    })