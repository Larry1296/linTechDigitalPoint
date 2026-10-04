from apps.tenancy.commands import LintechCommand
from django.core.management.base import BaseCommand
from apps.core.setup import ensure_initial_setup
class Command(LintechCommand):
    def handle(self,*args,**options):
        ensure_initial_setup(); self.stdout.write(self.style.SUCCESS("Initial store, internal roles, and permissions are ready. Define physical areas in Shelf Management."))
