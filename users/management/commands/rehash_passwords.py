"""
Management command to re-hash existing user passwords with a faster hasher (MD5).
This speeds up login for existing users in development.

Usage:
    python manage.py rehash_passwords

WARNING: This reduces security! Only use in development.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password


class Command(BaseCommand):
    help = 'Re-hash all user passwords with MD5 for faster development login'

    def add_arguments(self, parser):
        parser.add_argument(
            '--password',
            type=str,
            default='password123',
            help='New password for all users (default: password123)'
        )

    def handle(self, *args, **options):
        new_password = options['password']
        
        self.stdout.write(self.style.WARNING(
            f'\n⚠️  WARNING: This will reset ALL user passwords to "{new_password}"'
        ))
        self.stdout.write(self.style.WARNING(
            '⚠️  Only use this in development!\n'
        ))
        
        users = User.objects.all()
        count = users.count()
        
        if count == 0:
            self.stdout.write(self.style.WARNING('No users found.'))
            return
        
        self.stdout.write(f'Found {count} user(s). Re-hashing passwords...')
        
        for user in users:
            user.set_password(new_password)
            user.save(update_fields=['password'])
            self.stdout.write(f'  ✓ {user.username}')
        
        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Done! All {count} user(s) now have password: "{new_password}"'
        ))
        self.stdout.write(self.style.SUCCESS(
            '   Login should now be fast (<1 second).\n'
        ))
