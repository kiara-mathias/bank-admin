import os
import django

# Tell Django where the settings are
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crudapp.settings")
django.setup()  # Initialize Django

from django.contrib.auth.models import User
from users.models import Employee

for emp in Employee.objects.all():
    if emp.user:
        print(f"Skipping {emp.username} (already linked)")
        continue

    user = User.objects.create_user(
        username=emp.email,
        email=emp.email,
        password=emp.password
    )

    emp.user = user
    emp.save()

    print(f"Linked {emp.username} → {user.username}")
