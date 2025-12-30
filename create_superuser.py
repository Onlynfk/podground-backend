import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin.settings")

import django

django.setup()

from admin.db.models import Admin

try:
    email = input("Please provide your email: ")
    password = input("Please provide your password: ")
except IndexError:
    print("Usage: python create_superuser.py <email> <password>")
    sys.exit(1)

if not Admin.objects.filter(email=email).exists():
    user = Admin.objects.create_superuser(email=email, is_active=True)
    user.set_password(password)
    user.save()
    print("superuser created")
else:
    print("superuser already exists")
