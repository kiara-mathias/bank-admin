from django.contrib import admin
from .models import UsersNew, Account, Transaction

@admin.register(UsersNew)
class UsersNewAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'contact', 'joining_date')

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'account_no', 'current_balance', 'account_status', 'kyc_status')
    list_filter = ('account_status', 'kyc_status')

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('account', 'txn_type', 'amount', 'current_balance', 'txn_datetime')
    list_filter = ('txn_type',)
