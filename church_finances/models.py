from django.db import models
from django.contrib.auth.models import User, AbstractUser
from django.conf import settings
from django.utils import timezone

class Church(models.Model):
    SUBSCRIPTION_TYPES = (
        ('standard', 'Standard'),
        ('premium', 'Premium'),
    )
    
    SUBSCRIPTION_STATUS = (
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('suspended', 'Suspended'),
        ('expired', 'Expired'),
    )
    
    name = models.CharField(max_length=200)
    address = models.TextField()
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    website = models.URLField(blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    subscription_type = models.CharField(max_length=20, choices=SUBSCRIPTION_TYPES, default='standard')
    subscription_status = models.CharField(max_length=20, choices=SUBSCRIPTION_STATUS, default='pending')
    paypal_subscription_id = models.CharField(max_length=100, blank=True, null=True)
    subscription_start_date = models.DateTimeField(blank=True, null=True)
    subscription_end_date = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class PayPalSubscription(models.Model):
    """
    Track PayPal subscription details
    """
    STATUS_CHOICES = (
        ('APPROVAL_PENDING', 'Approval Pending'),
        ('APPROVED', 'Approved'),
        ('ACTIVE', 'Active'),
        ('SUSPENDED', 'Suspended'),
        ('CANCELLED', 'Cancelled'),
        ('EXPIRED', 'Expired'),
    )
    
    church = models.OneToOneField(Church, on_delete=models.CASCADE, related_name='paypal_subscription')
    subscription_id = models.CharField(max_length=100, unique=True)
    plan_id = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    payer_id = models.CharField(max_length=100, blank=True)
    payer_email = models.EmailField(blank=True)
    create_time = models.DateTimeField()
    start_time = models.DateTimeField(blank=True, null=True)
    next_billing_time = models.DateTimeField(blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.church.name} - {self.subscription_id}"

class PayPalWebhook(models.Model):
    """
    Store PayPal webhook events for tracking and debugging
    """
    event_id = models.CharField(max_length=100, unique=True)
    event_type = models.CharField(max_length=100)
    resource_type = models.CharField(max_length=100)
    subscription_id = models.CharField(max_length=100, blank=True)
    data = models.JSONField()
    processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_type} - {self.event_id}"

class ChurchMember(models.Model):
    ROLES = (
        ('admin', 'Church Admin'),
        ('treasurer', 'Treasurer'),
        ('pastor', 'Pastor'),
        ('assistant_pastor', 'Assistant Pastor'),
        ('deacon', 'Deacon')
    )

    MARITAL_STATUS = (
        ('single', 'Single'),
        ('married', 'Married'),
        ('widowed', 'Widowed'),
        ('divorced', 'Divorced'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    church = models.ForeignKey(Church, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLES, default='member')
    is_active = models.BooleanField(default=True)
    
    # Additional member details
    date_of_birth = models.DateField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    marital_status = models.CharField(max_length=20, choices=MARITAL_STATUS, blank=True)
    baptism_date = models.DateField(null=True, blank=True)
    membership_date = models.DateField(default=timezone.now)
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'church']

    def __str__(self):
        return f"{self.user.username} - {self.church.name} ({self.role})"


class Contribution(models.Model):
    """
    Model to represent member contributions (tithes and offerings)
    """
    CONTRIBUTION_TYPES = (
        ('tithe', 'Tithe'),
        ('offering', 'Offering'),
        ('special_offering', 'Special Offering'),
        ('building_fund', 'Building Fund'),
        ('missions', 'Missions'),
        ('other', 'Other'),
    )

    PAYMENT_METHODS = (
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('card', 'Credit/Debit Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('mobile_money', 'Mobile Money'),
    )

    member = models.ForeignKey(ChurchMember, on_delete=models.CASCADE)
    church = models.ForeignKey(Church, on_delete=models.CASCADE)
    date = models.DateField()
    contribution_type = models.CharField(max_length=20, choices=CONTRIBUTION_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    reference_number = models.CharField(max_length=50, blank=True, help_text="Check number, transaction ID, etc.")
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.member.user.username} - {self.contribution_type} - ${self.amount} ({self.date})"

class Transaction(models.Model):
    """
    Model to represent a financial transaction (income or expense).
    """
    TRANSACTION_TYPES = (
        ("income", "Income"),
        ("expense", "Expense"),
    )

    # Common categories for church finances
    INCOME_CATEGORIES = (
        ("tithes", "Tithes"),
        ("offerings", "Offerings"),
        ("donations", "Donations"),
        ("fundraising", "Fundraising"),
        ("other_income", "Other Income"),
    )

    EXPENSE_CATEGORIES = (
        ("salaries", "Salaries"),
        ("utilities", "Utilities"),
        ("rent_mortgage", "Rent/Mortgage"),
        ("missions", "Missions"),
        ("benevolence", "Benevolence"),
        ("supplies", "Supplies"),
        ("maintenance", "Maintenance"),
        ("events", "Events"),
        ("other_expense", "Other Expense"),
    )

    date = models.DateField()
    type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    category = models.CharField(
        max_length=50,
        choices=INCOME_CATEGORIES + EXPENSE_CATEGORIES,
        help_text="Select a category for the transaction.",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    church = models.ForeignKey(
        Church, on_delete=models.CASCADE, related_name='transactions',
        null=True, blank=True  # Allow null temporarily for migration
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "-date",
            "-created_at",
        ]  # Order by date descending, then creation time

    def __str__(self):
        return (
            f"{self.date} - {self.get_type_display()}: {self.category} - ${self.amount}"
        )
