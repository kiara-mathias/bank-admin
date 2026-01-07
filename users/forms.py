from django import forms
from django.contrib.auth.models import User, Group
from django.db import transaction
from .models import UsersNew, AccountInfo, Account, Transaction, Employee

class UsersNewForm(forms.ModelForm):
    class Meta:
        model = UsersNew
        fields = ['username', 'email', 'contact', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter username'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter email'}),
            'contact': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter contact'}),
            # 'joining_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'password': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter password'}),
        }

class EmployeeForm(forms.ModelForm):
    # This form is used for updates mainly
    role = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        required=False,
        empty_label="Select Role",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        required=False, 
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter password (leave blank to keep current)'})
    )
    
    class Meta:
        model = Employee
        fields = ['username', 'email', 'contact', 'status', 'role'] # Removed password from model binding
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter username'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter email'}),
            'contact': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter contact'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }

    def save(self, commit=True):
        emp = super().save(commit=False)
        if self.cleaned_data.get('password'):
            emp.password = self.cleaned_data['password']
        if commit:
            emp.save()
        return emp

class EmployeeCreationForm(forms.ModelForm):
    role = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        required=True,
        empty_label="Select Role",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = Employee
        fields = ['username', 'email', 'contact', 'password', 'status', 'role']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter username'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter email'}),
            'contact': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter contact'}),
            'password': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter password'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(f"Username '{username}' is already taken.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
             raise forms.ValidationError(f"Email '{email}' is already registered.")
        if Employee.objects.filter(email=email).exists():
            raise forms.ValidationError(f"Email '{email}' is already registered for an employee.")
        return email

    def save(self, commit=True):
        employee = super().save(commit=False)
        username = self.cleaned_data['username']
        email = self.cleaned_data['email']
        password = self.cleaned_data['password']
        role = self.cleaned_data['role']

        if commit:
            with transaction.atomic():
                # Create Django User
                user = User.objects.create_user(username=username, email=email, password=password)
                
                # Sync role
                user.groups.add(role)
                
                # Link user to employee
                employee.user = user
                employee.save()
        return employee

# Form for Account model
class AccountInfoForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ['user', 'current_balance']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-control'}),
            'current_balance': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Enter current balance'}),
        }

TXN_CHOICES = [
    ('deposit', 'Deposit'),
    ('withdraw', 'Withdraw'),
]

class TransactionForm(forms.ModelForm):
    txn_type = forms.ChoiceField(
        choices=TXN_CHOICES,
        label='Transaction Type',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    amount = forms.DecimalField(
        label='Amount (₹)',
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    description = forms.CharField(
        label='Description',
        required=False,  # optional
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional description...'})
    )

    class Meta:
        model = Transaction
        fields = ['txn_type', 'amount', 'description']

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than 0")
        return amount
