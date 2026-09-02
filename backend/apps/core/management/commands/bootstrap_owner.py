import os
import secrets
from django.contrib.auth.models import Group,User
from django.core.management.base import BaseCommand
class Command(BaseCommand):
    def handle(self,*args,**kwargs):
        username=os.getenv("OWNER_USERNAME","larry"); supplied=os.getenv("OWNER_PASSWORD"); password=supplied or secrets.token_urlsafe(18)
        user,created=User.objects.get_or_create(username=username,defaults={"is_staff":True,"is_superuser":True})
        if created:
            user.set_password(password); user.is_staff=True; user.is_superuser=True; user.save(); user.groups.add(Group.objects.get(name="Owner"))
            self.stdout.write(self.style.SUCCESS(f"Owner created: {username}"))
            if not supplied:self.stdout.write(self.style.WARNING(f"Temporary password (shown once): {password}"))
        else:self.stdout.write(f"Owner {username} already exists; password unchanged.")

