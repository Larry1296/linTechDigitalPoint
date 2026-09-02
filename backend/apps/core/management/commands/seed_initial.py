from django.contrib.auth.models import Group,Permission,User
from django.core.management.base import BaseCommand
from apps.core.models import Store
from apps.inventory.models import Zone
class Command(BaseCommand):
    def handle(self,*args,**opts):
        store,_=Store.objects.get_or_create(name="LinTech Digital Point",defaults={"currency":"KES","timezone":"Africa/Nairobi"})
        for code,name in [("LEFT","Left Wall"),("BACK","Back Wall"),("RIGHT","Right Wall"),("COUNTER","Counter"),("OTHER","Other Storage")]: Zone.objects.get_or_create(store=store,code=code,defaults={"name":name})
        for name in ["Owner","Manager","Cashier","Stock Controller","Ecommerce Customer"]: Group.objects.get_or_create(name=name)
        owner=Group.objects.get(name="Owner"); owner.permissions.set(Permission.objects.all())
        self.stdout.write(self.style.SUCCESS("Initial store, zones, and roles are ready."))
