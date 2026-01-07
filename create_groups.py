# create_groups.py

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crudapp.settings')
django.setup()

from django.contrib.auth.models import Group

groups = ['Manager', 'Supervisor', 'Clerk']

for g in groups:
    group, created = Group.objects.get_or_create(name=g)
    if created:
        print(f"Created group: {g}")
    else:
        print(f"Group already exists: {g}")
