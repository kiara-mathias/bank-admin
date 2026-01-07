from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import UsersNew, AccountInfo
from django.utils import timezone

@receiver(post_save, sender=UsersNew)
def create_account_for_user(sender, instance, created, **kwargs):
    if created:
        AccountInfo.objects.create(
            emp=instance,
            current_bal=500,   # initial balance
            txn_type='deposit',
            amount=500,
            txn_datetime=timezone.now()
        )
