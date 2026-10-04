"""A virtual stock location makes physical shelving optional without losing FIFO."""
from django.db import transaction
from apps.accounting.ledger import resolve_branch
from .models import Zone, Shelf


@transaction.atomic
def unplaced_shelf():
    branch = resolve_branch()
    zone, _ = Zone.objects.get_or_create(store=branch, code='__UNPLACED__', defaults={'name':'Unplaced stock'})
    shelf, _ = Shelf.objects.get_or_create(zone=zone, code='__UNPLACED__', defaults={
        'display_name':'Not assigned to a shelf', 'is_virtual':True, 'x':0, 'y':0, 'width':1, 'height':1})
    return shelf
