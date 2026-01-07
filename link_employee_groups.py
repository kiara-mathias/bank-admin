# link_employee_groups.py

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crudapp.settings')
django.setup()

from django.contrib.auth.models import User
from users.models import Employee

for emp in Employee.objects.all():
    if not emp.user:
        # Create a User object if not linked
        user = User.objects.create_user(
            username=emp.username,
            email=emp.email,
            password=emp.password
        )
        emp.user = user
        print(f"Created user for employee: {emp.username}")
    
    # Assign to group based on emp.role
    if emp.role:
        emp.user.groups.add(emp.role)
    
    # Staff status to allow admin login
    emp.user.is_staff = True
    emp.user.save()
    emp.save()
    print(f"{emp.username} linked to {emp.role} and set as staff.")
