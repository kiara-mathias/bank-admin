from django.db import models
from decimal import Decimal
from django.contrib.auth.models import User, Group
from pytz import timezone

# users db table
class UsersNew(models.Model):
    emp_id = models.AutoField(primary_key=True)
    username = models.TextField()
    email = models.TextField(unique=True)
    contact = models.TextField(blank=True, null=True)
    joining_date = models.DateField(auto_now_add=True)
    password = models.TextField(blank=True, null=True)
    ROLE_CHOICES = [
        ('CUSTOMER', 'Customer'),
        ('EMPLOYEE', 'Employee'),
        ('ADMIN', 'Admin'),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='CUSTOMER')
    class Meta:
        managed = False
        db_table = 'users_new'

#account table
class Account(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('FROZEN', 'Frozen'),
        ('CLOSED', 'Closed'),
    ]

    KYC_CHOICES = [
        ('NOT_SUBMITTED', 'Not Submitted'),
        ('PENDING', 'Pending Verification'),
        ('VERIFIED', 'Verified'),
        ('REJECTED', 'Rejected'),
    ]


    account_no = models.PositiveIntegerField(unique=True, editable=False)
    user = models.OneToOneField(UsersNew, on_delete=models.CASCADE, to_field='emp_id', db_constraint=False)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    account_status = models.CharField(max_length=15,choices=STATUS_CHOICES,default='ACTIVE')

    kyc_status = models.CharField(
        max_length=15,
        choices=KYC_CHOICES,
        default='NOT_SUBMITTED'
    )
    def save(self, *args, **kwargs):
        if not self.account_no:
            last_account = Account.objects.exclude(account_no__isnull=True).order_by('-account_no').first()
            if last_account:
                self.account_no = last_account.account_no + 1
            else:
                self.account_no = 100000
        super().save(*args, **kwargs)

    class Meta:
        managed = True
        db_table = 'account'

class Employee(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('FROZEN', 'Frozen'),
    ]

    # NEW (Django-auth based)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    role = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # OLD (KEEP FOR NOW)
    username = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    contact = models.CharField(max_length=15)
    password = models.CharField(max_length=128)

    joining_date = models.DateField(auto_now_add=True)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='ACTIVE'
    )

    def __str__(self):
        return self.username

#transaction table
class Transaction(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    txn_type = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2 , default=0)
    description = models.TextField(blank=True, null=True)
    txn_datetime = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.account.account_status in ['FROZEN', 'CLOSED']:
            raise ValueError(f"Cannot create transaction. Account is {self.account.get_account_status_display()}.")
        super().save(*args, **kwargs)

    class Meta:
        managed = True
        db_table = 'transaction'



class AccountInfo(models.Model):
    txn_id = models.AutoField(primary_key=True)
    emp = models.ForeignKey(UsersNew, models.DO_NOTHING, blank=True, null=True)
    account_no = models.PositiveIntegerField(unique=True, editable=False)
    current_bal = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    txn_type = models.CharField(max_length=10, blank=True, null=True)
    txn_datetime = models.DateTimeField(blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.account_no:
            last_account = (
                AccountInfo.objects
                .exclude(account_no__isnull=True)
                .order_by('-account_no')
                .first()
            )

        if last_account:
            self.account_no = last_account.account_no + 1
        else:
            self.account_no = 100000  # first 6-digit account number

        super().save(*args, **kwargs)


    class Meta:
        managed = False
        db_table = 'account_info'
