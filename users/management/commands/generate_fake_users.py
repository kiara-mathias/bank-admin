from django.core.management.base import BaseCommand
from users.models import UsersNew, Account
from faker import Faker
import random

fake = Faker()

class Command(BaseCommand):
    help = 'Create fake users with account info'

    def add_arguments(self, parser):
        parser.add_argument('total', type=int, help='Number of fake users to create')

    def handle(self, *args, **kwargs):
        total = kwargs['total']

        for _ in range(total):
            username = fake.user_name()
            email = fake.email()
            contact = fake.phone_number()
            
            # Create the user
            user = UsersNew.objects.create(
                username=username,
                email=email,
                contact=contact,
            )

            # Create account (balance default handled in model)
            Account.objects.create(
                user=user,
                account_no=fake.random_int(min=10000000, max=99999999)
            )

        self.stdout.write(self.style.SUCCESS(f'Successfully created {total} fake users'))
