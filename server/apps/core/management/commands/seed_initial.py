from django.core.management.base import BaseCommand
from apps.core.setup import ensure_initial_setup
class Command(BaseCommand):
    def handle(self,*args,**options):
        ensure_initial_setup(); self.stdout.write(self.style.SUCCESS("Initial store, roles, and permissions are ready. Define physical areas in Digital Shop."))
