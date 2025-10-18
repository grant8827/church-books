from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User, Group
from .models import Transaction, Church, ChurchMember, Contribution
from django.db import transaction


class ChurchRegistrationForm(forms.ModelForm):
    """
    Form for registering a new church
    """
    class Meta:
        model = Church
        fields = ['name', 'address', 'phone', 'email', 'website']
        labels = {
            'name': 'Church Name',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input rounded-md shadow-sm'}),
            'address': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea rounded-md shadow-sm'}),
            'phone': forms.TextInput(attrs={'class': 'form-input rounded-md shadow-sm'}),
            'email': forms.EmailInput(attrs={'class': 'form-input rounded-md shadow-sm'}),
            'website': forms.URLInput(attrs={'class': 'form-input rounded-md shadow-sm'}),
        }
        
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Check if the user has already registered a church
        if self.user and self.user.is_authenticated:
            existing_church = Church.objects.filter(registered_by=self.user).first()
            if existing_church:
                raise forms.ValidationError(
                    f"You have already registered a church: {existing_church.name}. "
                    "Each account can only register one church."
                )
        
        return cleaned_data

class CustomUserCreationForm(UserCreationForm):
    """
    A custom user creation form that includes church registration
    """
    first_name = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-input rounded-md shadow-sm'}),
                             label="First Name")
    last_name = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-input rounded-md shadow-sm'}),
                            label="Last Name")
    church_role = forms.ChoiceField(choices=[
        ('admin', 'Church Admin'),
        ('treasurer', 'Treasurer'),
        ('pastor', 'Pastor')  # Changed from 'member' to 'pastor'
    ], required=False, 
    initial='admin',
    widget=forms.Select(attrs={'class': 'form-select rounded-md shadow-sm'}))
    # existing_church = forms.ModelChoiceField(queryset=Church.objects.filter(is_approved=True),
    #                                      required=False,
    #                                      widget=forms.Select(attrs={'class': 'form-select rounded-md shadow-sm'}))

    class Meta(UserCreationForm.Meta):
        fields = UserCreationForm.Meta.fields + ('email', 'first_name', 'last_name')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add CSS classes to form fields
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'


class ChurchMemberForm(forms.ModelForm):
    """
    Form for adding and updating church members
    """
    first_name = forms.CharField(max_length=30)
    last_name = forms.CharField(max_length=30)
    
    class Meta:
        model = ChurchMember
        fields = [
            'first_name', 'last_name', 'phone_number', 'address', 'date_of_birth', 
            'marital_status', 'baptism_date', 'emergency_contact_name', 
            'emergency_contact_phone', 'notes'
        ]
        widgets = {
            'date_of_birth': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-input rounded-md shadow-sm'}
            ),
            'baptism_date': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-input rounded-md shadow-sm'}
            ),
            'phone_number': forms.TextInput(
                attrs={'class': 'form-input rounded-md shadow-sm'}
            ),
            'address': forms.Textarea(
                attrs={'rows': 3, 'class': 'form-textarea rounded-md shadow-sm'}
            ),
            'marital_status': forms.Select(
                attrs={'class': 'form-select rounded-md shadow-sm'}
            ),
            'emergency_contact_name': forms.TextInput(
                attrs={'class': 'form-input rounded-md shadow-sm'}
            ),
            'emergency_contact_phone': forms.TextInput(
                attrs={'class': 'form-input rounded-md shadow-sm'}
            ),
            'notes': forms.Textarea(
                attrs={'rows': 3, 'class': 'form-textarea rounded-md shadow-sm'}
            ),
        }

class ContributionForm(forms.ModelForm):
    """
    Form for recording tithes and offerings
    """
    class Meta:
        model = Contribution
        fields = [
            'member', 'date', 'contribution_type', 'amount',
            'payment_method', 'reference_number', 'notes'
        ]
        widgets = {
            'member': forms.Select(
                attrs={
                    'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm truncate',
                    'style': 'max-width: 100%; overflow: hidden; text-overflow: ellipsis;'
                }
            ),
            'date': forms.DateInput(
                attrs={
                    'type': 'date', 
                    'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
                }
            ),
            'contribution_type': forms.Select(
                attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'}
            ),
            'amount': forms.NumberInput(
                attrs={
                    'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500', 
                    'step': '0.01',
                    'min': '0'
                }
            ),
            'payment_method': forms.Select(
                attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'}
            ),
            'reference_number': forms.TextInput(
                attrs={
                    'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                    'placeholder': 'Check number, transaction ID, etc.'
                }
            ),
            'notes': forms.Textarea(
                attrs={
                    'rows': 4, 
                    'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 resize-y',
                    'style': 'min-height: 100px; max-height: 300px;',
                    'placeholder': 'Enter any additional notes about this contribution...'
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        church = kwargs.pop('church', None)
        super().__init__(*args, **kwargs)
        if church:
            self.fields['member'].queryset = ChurchMember.objects.filter(church=church)

class DashboardUserRegistrationForm(UserCreationForm):
    """
    Form for registering new church staff members from the dashboard
    """
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={
        'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
    }))
    role = forms.ChoiceField(
        choices=[
            ('admin', 'Church Admin'),
            ('treasurer', 'Treasurer'),
            ('pastor', 'Pastor'),
            ('assistant_pastor', 'Assistant Pastor'),
            ('deacon', 'Deacon')
        ],
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
        })
    )
    first_name = forms.CharField(max_length=30, required=True, widget=forms.TextInput(attrs={
        'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
    }))
    last_name = forms.CharField(max_length=30, required=True, widget=forms.TextInput(attrs={
        'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
    }))

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        self.church = kwargs.pop('church', None)
        super().__init__(*args, **kwargs)
        # Add CSS classes to form fields
        for field_name in ['username', 'password1', 'password2']:
            self.fields[field_name].widget.attrs['class'] = 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        
        if commit:
            user.save()
            # Create a ChurchMember instance for this user
            # Users registered through the dashboard by admin/pastor are automatically approved
            ChurchMember.objects.create(
                user=user,
                church=self.church,
                role=self.cleaned_data['role'],
                is_active=True  # Automatically activate the member since they're registered by admin/pastor
            )
            
            # Add user to appropriate group based on role
            role_group, _ = Group.objects.get_or_create(name=self.cleaned_data['role'])
            user.groups.add(role_group)
            
        return user

class TransactionForm(forms.ModelForm):
    """
    Form for creating and updating financial transactions.
    """
    def __init__(self, *args, **kwargs):
        self.church = kwargs.pop('church', None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = Transaction
        fields = ["date", "type", "category", "amount", "description"]
        widgets = {
            "date": forms.DateInput(
                attrs={"type": "date", "class": "form-input rounded-md shadow-sm"}
            ),
            "type": forms.Select(
                attrs={"class": "form-select rounded-md shadow-sm"}
            ),
            "category": forms.Select(
                attrs={"class": "form-select rounded-md shadow-sm"}
            ),
            "amount": forms.NumberInput(
                attrs={"class": "form-input rounded-md shadow-sm", "step": "0.01"}
            ),
            "description": forms.Textarea(
                attrs={"rows": 3, "class": "form-textarea rounded-md shadow-sm"}
            ),
        }
        labels = {
            "date": "Date",
            "type": "Transaction Type",
            "category": "Category",
            "amount": "Amount ($)",
            "description": "Description (Optional)",
        }
        
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.church:
            instance.church = self.church
        if commit:
            instance.save()
        return instance
