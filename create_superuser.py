import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin.settings")

import django

django.setup()

from admin.db.models import Admin, Profile

try:
    email = input("Please provide your email: ")
    password = input("Please provide your password: ")
except IndexError:
    print("Usage: python create_superuser.py <email> <password>")
    sys.exit(1)

profile = Profile.objects.filter(email=email).first()
admin_user = Admin.objects.filter(email=email).first()

if not profile:
    print("User does not exist") 
    sys.exit(1)
elif not admin_user:
    user = Admin.objects.create_superuser(id=profile.id, email=email, password=password, is_active=True)
    print(user, user.id)
    print("superuser created")
else:
    print("user account already exists")
    sys.exit(1)
