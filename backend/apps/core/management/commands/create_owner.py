import getpass
import os
from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand,CommandError
from apps.core.setup import ensure_initial_setup
class Command(BaseCommand):
    help="Create or repair the LinTech Owner account."
    def add_arguments(self,parser):
        parser.add_argument("--username"); parser.add_argument("--email"); parser.add_argument("--first-name"); parser.add_argument("--noinput",action="store_true")
    def handle(self,*args,**options):
        _,groups=ensure_initial_setup(); noinput=options["noinput"]
        username=options["username"] or (os.getenv("OWNER_USERNAME") if noinput else input("Username [larry]: ").strip() or "larry")
        email=options["email"] or (os.getenv("OWNER_EMAIL","") if noinput else input("Email: ").strip())
        first=options["first_name"] or (os.getenv("OWNER_FIRST_NAME","") if noinput else input("First/display name: ").strip())
        user,created=User.objects.get_or_create(username=username,defaults={"email":email,"first_name":first})
        if not created and not noinput:
            self.stdout.write("Existing user found; password will not change unless you confirm.")
        change_password=created or (not noinput and input("Set/change password? [y/N]: ").lower()=="y")
        if change_password:
            if noinput:
                password=os.getenv("OWNER_PASSWORD")
                if not password: raise CommandError("OWNER_PASSWORD is required with --noinput for a new owner.")
            else:
                password=getpass.getpass("Password: "); confirmation=getpass.getpass("Password confirmation: ")
                if password!=confirmation: raise CommandError("Passwords do not match.")
            try: password_validation.validate_password(password,user)
            except ValidationError as exc: raise CommandError(" ".join(exc.messages)) from exc
            user.set_password(password)
        if email:user.email=email
        if first:user.first_name=first
        user.is_active=True; user.is_staff=True; user.is_superuser=True; user.save(); user.groups.add(groups["Owner"])
        self.stdout.write(self.style.SUCCESS(f"Owner '{username}' is correctly configured."))

