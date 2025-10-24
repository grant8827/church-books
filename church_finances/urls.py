from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views
from . import views_subscription

urlpatterns = [
    # Static page URLs
    path('about/', views.about_view, name='about'),
    path('contact/', views.contact_view, name='contact'),
    path('pricing/', views.pricing_view, name='pricing'),
    path('choose-plan/', views.choose_plan_view, name='choose_plan'),
    
    # Subscription URLs
    path('subscription/', views_subscription.subscription_view, name='subscription'),
    path('subscription/select/', views_subscription.subscription_select, name='subscription_select'),
    path('subscription/payment/', views_subscription.payment_selection_view, name='payment_selection'),
    path('subscription/register/', views_subscription.registration_form_view, name='registration_form'),
    path('pending-approval/', views.pending_approval_view, name='pending_approval'),
    path('account-status/', views.account_status_view, name='account_status'),
    
    # PayPal URLs
    path('paypal/create-subscription/', views_subscription.create_paypal_subscription, name='paypal_create_subscription'),
    path('subscription/success/', views_subscription.paypal_success, name='paypal_success'),
    path('subscription/cancel/', views_subscription.paypal_cancel, name='paypal_cancel'),
    path('paypal/webhook/', views_subscription.paypal_webhook, name='paypal_webhook'),
    # Password Reset URLs
    path('password_reset/', auth_views.PasswordResetView.as_view(
        template_name='church_finances/password_reset/password_reset_form.html',
        email_template_name='church_finances/password_reset/password_reset_email.txt',
        html_email_template_name='church_finances/password_reset/password_reset_email.html',
        success_url=reverse_lazy('password_reset_done'),
        from_email='Church Finance App <info@churchbooksmanagement.com>'
    ), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='church_finances/password_reset/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='church_finances/password_reset/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete')
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='church_finances/password_reset/password_reset_complete.html'
    ), name='password_reset_complete'),
    # Member management URLs
    path("members/", views.member_list_view, name="member_list"),
    path("members/add/", views.member_add_view, name="member_add"),
    path("members/<int:pk>/", views.member_detail_view, name="member_detail"),
    path("members/<int:pk>/edit/", views.member_edit_view, name="member_edit"),
    path("members/<int:pk>/activate/", views.member_activate_view, name="member_activate"),
    path("members/<int:pk>/deactivate/", views.member_deactivate_view, name="member_deactivate"),
    
    # Contribution management URLs
    path("contributions/", views.contribution_list_view, name="contribution_list"),
    path("contributions/add/", views.contribution_add_view, name="contribution_add"),
    path("contributions/<int:pk>/", views.contribution_detail_view, name="contribution_detail"),
    path("contributions/<int:pk>/edit/", views.contribution_edit_view, name="contribution_edit"),
    path("contributions/print/monthly/", views.contribution_print_monthly, name="contribution_print_monthly"),
    path("contributions/print/yearly/", views.contribution_print_yearly, name="contribution_print_yearly"),
    
    # Enhanced Tithes & Offerings Management URLs
    path("tithes-offerings/", views.tithes_offerings_dashboard, name="tithes_offerings_dashboard"),
    path("my-contributions/", views.member_contributions_view, name="member_contributions"),
    path("quick-tithe/", views.quick_tithe_entry, name="quick_tithe_entry"),
    path("contributions/bulk-entry/", views.bulk_contribution_entry, name="bulk_contribution_entry"),
    path("contributions/statement/<int:year>/", views.contribution_statement_pdf, name="contribution_statement_pdf"),
    path("contributions/statement/", views.contribution_statement_pdf, name="contribution_statement_current"),
    # Transaction print views
    path("transactions/print/monthly/", views.transaction_print_monthly, name="transaction_print_monthly"),
    path("transactions/print/yearly/", views.transaction_print_yearly, name="transaction_print_yearly"),
    path("register/", views.register_view, name="register"),
    path("dashboard/register-staff/", views.dashboard_user_register_view, name="dashboard_user_register"),
    path("login/", views.user_login_view, name="login"),
    path("logout/", views.user_logout_view, name="logout"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("transactions/", views.transaction_list_view, name="transaction_list"),
    path("transactions/add/", views.transaction_create_view, name="transaction_create"),
    path(
        "transactions/<int:pk>/",
        views.transaction_detail_view,
        name="transaction_detail",
    ),
    path(
        "transactions/<int:pk>/edit/",
        views.transaction_update_view,
        name="transaction_update",
    ),
    path(
        "transactions/<int:pk>/delete/",
        views.transaction_delete_view,
        name="transaction_delete",
    ),
    # Church approval URLs
    path("churches/pending/", views.church_approval_list, name="church_approval_list"),
    path("churches/<int:church_id>/approve/", views.approve_church, name="approve_church"),
    path("churches/<int:church_id>/reject/", views.reject_church, name="reject_church"),
    path("churches/<int:church_id>/verify-offline/", views.verify_offline_payment, name="verify_offline_payment"),
    path("admin/quick-approve-user/<int:user_id>/", views.quick_approve_user_church, name="quick_approve_user_church"),
    
    # Children Management URLs
    path("children/", views.children_list_view, name="children_list"),
    path("children/add/", views.child_add_view, name="child_add"),
    path("children/<int:child_id>/", views.child_detail_view, name="child_detail"),
    path("children/<int:child_id>/edit/", views.child_edit_view, name="child_edit"),
    path("attendance/record/", views.attendance_record_view, name="attendance_record"),
    
    # Baby Christening URLs
    path("christenings/", views.christenings_list_view, name="christenings_list"),
    path("christenings/add/", views.christening_add_view, name="christening_add"),
    path("christenings/<int:christening_id>/", views.christening_detail_view, name="christening_detail"),
    path("christenings/<int:christening_id>/edit/", views.christening_edit_view, name="christening_edit"),
]
