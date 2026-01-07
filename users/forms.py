from django import forms
from .models import UsersNew , AccountInfo, Account, Transaction , Employee

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
    class Meta:
        model = Employee
        fields = ['username', 'email', 'contact', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter username'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter email'}),
            'contact': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter contact'}),
            'password': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter password'}),
        }
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
