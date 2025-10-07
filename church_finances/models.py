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
    # Payment / billing metadata
    PAYMENT_METHODS = (
        ('paypal', 'PayPal'),
        ('offline', 'Offline'),
    )
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='offline')
    offline_payment_reference = models.CharField(max_length=255, blank=True, null=True, help_text="Reference # / receipt / memo for offline payment")
    offline_verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='offline_verifications', help_text='Admin user who verified offline payment')
    offline_verified_at = models.DateTimeField(blank=True, null=True)
    offline_notes = models.TextField(blank=True, help_text="Internal notes regarding offline payment verification")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @property
    def is_payment_verified(self):
        if self.payment_method == 'paypal':
            return self.subscription_status == 'active' and self.is_approved
        if self.payment_method == 'offline':
            return self.offline_verified_at is not None
        return False

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


class Child(models.Model):
    """
    Model to represent children in the church
    """
    GRADE_LEVELS = (
        ('nursery', 'Nursery (0-2 years)'),
        ('toddler', 'Toddler (2-3 years)'),
        ('preschool', 'Preschool (3-5 years)'),
        ('kindergarten', 'Kindergarten'),
        ('1st_grade', '1st Grade'),
        ('2nd_grade', '2nd Grade'),
        ('3rd_grade', '3rd Grade'),
        ('4th_grade', '4th Grade'),
        ('5th_grade', '5th Grade'),
        ('6th_grade', '6th Grade'),
        ('7th_grade', '7th Grade'),
        ('8th_grade', '8th Grade'),
        ('9th_grade', '9th Grade'),
        ('10th_grade', '10th Grade'),
        ('11th_grade', '11th Grade'),
        ('12th_grade', '12th Grade'),
        ('graduated', 'Graduated'),
    )
    
    SUNDAY_SCHOOL_CLASSES = (
        ('nursery', 'Nursery'),
        ('toddlers', 'Toddlers'),
        ('preschool', 'Preschool'),
        ('elementary', 'Elementary'),
        ('middle_school', 'Middle School'),
        ('high_school', 'High School'),
        ('youth', 'Youth Group'),
    )

    # Basic Information
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    date_of_birth = models.DateField()
    grade_level = models.CharField(max_length=20, choices=GRADE_LEVELS, blank=True)
    
    # Church Relationship
    church = models.ForeignKey(Church, on_delete=models.CASCADE, related_name='children')
    parents = models.ManyToManyField(ChurchMember, related_name='children', blank=True,
                                   help_text="Select the parent(s) or guardian(s) from church members")
    
    # Church Activities
    sunday_school_class = models.CharField(max_length=20, choices=SUNDAY_SCHOOL_CLASSES, blank=True)
    baptism_date = models.DateField(null=True, blank=True)
    
    # Emergency Information
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True, 
                                                    help_text="e.g., Grandmother, Uncle, Family Friend")
    
    # Medical Information
    allergies = models.TextField(blank=True, help_text="List any known allergies or medical conditions")
    medications = models.TextField(blank=True, help_text="List any regular medications")
    medical_notes = models.TextField(blank=True, help_text="Any other important medical information")
    
    # Contact Information
    address = models.TextField(blank=True, help_text="If different from parents' address")
    phone_number = models.CharField(max_length=20, blank=True, help_text="If child has own phone")
    
    # Status and Notes
    is_active = models.BooleanField(default=True, help_text="Is the child currently attending?")
    notes = models.TextField(blank=True, help_text="General notes about the child")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['last_name', 'first_name']
        verbose_name = 'Child'
        verbose_name_plural = 'Children'

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def age(self):
        """Calculate current age from date of birth"""
        from datetime import date
        today = date.today()
        return today.year - self.date_of_birth.year - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
    
    @property
    def parent_names(self):
        """Get a comma-separated list of parent names"""
        return ", ".join([f"{parent.user.first_name} {parent.user.last_name}" for parent in self.parents.all()])


class ChildAttendance(models.Model):
    """
    Track attendance for children in various church activities
    """
    ACTIVITY_TYPES = (
        ('sunday_service', 'Sunday Service'),
        ('sunday_school', 'Sunday School'),
        ('vbs', 'Vacation Bible School'),
        ('youth_group', 'Youth Group'),
        ('special_event', 'Special Event'),
        ('camp', 'Church Camp'),
        ('other', 'Other Activity'),
    )
    
    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name='attendance_records')
    church = models.ForeignKey(Church, on_delete=models.CASCADE)
    date = models.DateField()
    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPES)
    activity_name = models.CharField(max_length=100, blank=True, help_text="Name of specific activity or event")
    present = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']
        unique_together = ['child', 'date', 'activity_type']

    def __str__(self):
        status = "Present" if self.present else "Absent"
        return f"{self.child.full_name} - {self.activity_type} - {self.date} ({status})"


class BabyChristening(models.Model):
    """Model to track baby christenings/baptisms at the church"""
    
    # Basic Information
    baby_first_name = models.CharField(max_length=100, help_text="Baby's first name")
    baby_last_name = models.CharField(max_length=100, help_text="Baby's last name")
    baby_date_of_birth = models.DateField(null=True, blank=True, help_text="Baby's date of birth")
    
    # Christening Details
    christening_date = models.DateField(help_text="Date of christening ceremony")
    christening_time = models.TimeField(null=True, blank=True, help_text="Time of ceremony")
    pastor = models.CharField(max_length=200, help_text="Pastor who performed the christening")
    ceremony_notes = models.TextField(blank=True, help_text="Special notes about the ceremony")
    
    # Parents Information
    father_name = models.CharField(max_length=200, blank=True, help_text="Father's full name")
    mother_name = models.CharField(max_length=200, blank=True, help_text="Mother's full name")
    parent_members = models.ManyToManyField(ChurchMember, blank=True, related_name='christened_babies', help_text="Parents who are church members")
    
    # Godparents Information
    godfather_name = models.CharField(max_length=200, blank=True, help_text="Godfather's full name")
    godmother_name = models.CharField(max_length=200, blank=True, help_text="Godmother's full name")
    other_godparents = models.TextField(blank=True, help_text="Additional godparents")
    
    # Contact Information
    contact_address = models.TextField(blank=True, help_text="Family contact address")
    contact_phone = models.CharField(max_length=20, blank=True, help_text="Primary contact phone")
    contact_email = models.EmailField(blank=True, help_text="Contact email address")
    
    # Church Information
    church = models.ForeignKey(Church, on_delete=models.CASCADE, related_name='christened_babies')
    certificate_number = models.CharField(max_length=50, blank=True, help_text="Christening certificate number")
    
    # Administrative
    is_active = models.BooleanField(default=True, help_text="Active record")
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, help_text="Person who recorded this christening")
    date_recorded = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-christening_date']
        unique_together = ['baby_first_name', 'baby_last_name', 'christening_date', 'church']
    
    @property
    def baby_full_name(self):
        """Return baby's full name"""
        return f"{self.baby_first_name} {self.baby_last_name}"
    
    @property
    def baby_age_at_christening(self):
        """Calculate baby's age at christening in days/months"""
        if self.baby_date_of_birth and self.christening_date:
            delta = self.christening_date - self.baby_date_of_birth
            days = delta.days
            if days < 30:
                return f"{days} days"
            elif days < 365:
                months = days // 30
                return f"{months} months"
            else:
                years = days // 365
                return f"{years} years"
        return "Unknown"
    
    @property 
    def parents_list(self):
        """Return formatted list of parents"""
        parents = []
        if self.father_name:
            parents.append(self.father_name)
        if self.mother_name:
            parents.append(self.mother_name)
        return " & ".join(parents) if parents else "Not specified"
    
    @property
    def godparents_list(self):
        """Return formatted list of godparents"""
        godparents = []
        if self.godfather_name:
            godparents.append(f"Godfather: {self.godfather_name}")
        if self.godmother_name:
            godparents.append(f"Godmother: {self.godmother_name}")
        if self.other_godparents:
            godparents.append(f"Other: {self.other_godparents}")
        return "; ".join(godparents) if godparents else "Not specified"
    
    def __str__(self):
        return f"{self.baby_full_name} - Christened {self.christening_date}"
