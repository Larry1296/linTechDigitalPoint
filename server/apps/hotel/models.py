"""Hotels: the eatery's menu and kitchen, and a hotel's rooms, guests and their bills.

An eatery (a Kenyan "hoteli", café or food kiosk) cooks what it sells, so a plate of chapati is never counted in stock:
menu items are priced and always sell. What is counted is the kitchen's stock (flour, oil, meat, sugar), bought in like
any stock; what the kitchen used, typed in or worked out from a count, is the cost of the meals sold.

A hotel with rooms books guests into rooms. A stay runs from booking to check-in to check-out. Its bill is ordinary
sales on the guest's customer account: a sale for each night, food and drinks charged to the room from the till, and
extras such as laundry. A night is charged when the guest checks in, and another each time they are still in after the
hotel's check-out time, so a guest who leaves early never needs a refund for nights not slept. Money paid in advance is
held as the guest's deposit (owed to the guest until used) and is used against the bill as charges arrive.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.models import ProductVariant
from apps.core.models import TimeStamped
from apps.tenancy.base import TenantModel


class MenuItem(TimeStamped):
    """A dish or drink the kitchen makes: priced, sold at the till, never counted in stock."""
    variant = models.OneToOneField(ProductVariant, related_name="menu_item", on_delete=models.PROTECT)
    available = models.BooleanField(default=True)  # off while it has run out today; the till then hides it

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"


class KitchenIngredient(TimeStamped):
    """Stock bought for cooking (flour, oil, meat). Counted like any stock; kept off the till unless it is also sold."""
    variant = models.OneToOneField(ProductVariant, related_name="kitchen_ingredient", on_delete=models.PROTECT)
    sold_at_till = models.BooleanField(default=False)

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"


class KitchenUse(TimeStamped):
    """What the kitchen used on a day: its cost is the cost of the meals sold."""
    USED, COUNTED = "USED", "COUNTED"
    branch = models.ForeignKey("core.Store", null=True, blank=True, on_delete=models.PROTECT, editable=False)
    number = models.CharField(max_length=40)
    used_on = models.DateField()
    way = models.CharField(max_length=8, choices=[(USED, "Typed in what was used"), (COUNTED, "Counted what is left")])
    note = models.CharField(max_length=255, blank=True)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-used_on", "-pk"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "number"], name="hote_kitchenuse_number_org")]


class KitchenUseLine(TenantModel):
    use = models.ForeignKey(KitchenUse, related_name="lines", on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    left = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)  # what was counted, when counted
    cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="hote_kitchenuseline_positive")]


class RoomType(TimeStamped):
    """A kind of room and its price a night (Single, Double, Deluxe). Its nights are sold as this service."""
    variant = models.OneToOneField(ProductVariant, related_name="room_type", on_delete=models.PROTECT)
    sleeps = models.PositiveSmallIntegerField(default=2)
    active = models.BooleanField(default=True)
    # Not a room: what guests are charged for besides their nights (laundry, an extra bed), sold the same way.
    extra = models.BooleanField(default=False)

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"


class Room(TimeStamped):
    READY, DIRTY, OUT_OF_ORDER = "READY", "DIRTY", "OUT"
    branch = models.ForeignKey("core.Store", null=True, blank=True, on_delete=models.PROTECT, editable=False)
    number = models.CharField(max_length=20)
    room_type = models.ForeignKey(RoomType, related_name="rooms", on_delete=models.PROTECT)
    floor = models.CharField(max_length=40, blank=True)
    condition = models.CharField(max_length=5, default=READY,
                                 choices=[(READY, "Ready"), (DIRTY, "Needs cleaning"), (OUT_OF_ORDER, "Out of order")])
    note = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["number"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "branch", "number"], name="hote_room_number_branch")]


class Stay(TimeStamped):
    """A guest's booking and stay in one room, from booking to check-out."""
    BOOKED, IN, OUT, CANCELLED, NO_SHOW = "BOOKED", "IN", "OUT", "CANCELLED", "NO_SHOW"
    STATUSES = [(BOOKED, "Booked"), (IN, "Checked in"), (OUT, "Checked out"), (CANCELLED, "Cancelled"), (NO_SHOW, "Did not come")]
    branch = models.ForeignKey("core.Store", null=True, blank=True, on_delete=models.PROTECT, editable=False)
    number = models.CharField(max_length=40)
    room = models.ForeignKey(Room, related_name="stays", on_delete=models.PROTECT)
    guest = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="hotel_stays", on_delete=models.PROTECT)  # a customer
    guest_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=30, blank=True)
    id_number = models.CharField(max_length=40, blank=True)  # national ID or passport, as hotels record at check-in
    guests = models.PositiveSmallIntegerField(default=1)
    arrival = models.DateField()
    departure = models.DateField()  # the morning the guest is expected to leave
    rate = models.DecimalField(max_digits=14, decimal_places=2)  # agreed price a night
    status = models.CharField(max_length=10, choices=STATUSES, default=BOOKED)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-arrival", "-pk"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "number"], name="hote_stay_number_org"),
                       models.CheckConstraint(condition=Q(departure__gt=models.F("arrival")), name="hote_stay_leaves_after_arriving")]


class StayCharge(TenantModel):
    """A sale on the guest's bill: a night, something charged to the room at the till, or an extra."""
    NIGHT, TILL, EXTRA = "NIGHT", "TILL", "EXTRA"
    stay = models.ForeignKey(Stay, related_name="charges", on_delete=models.PROTECT)
    sale = models.OneToOneField("commerce.Sale", related_name="stay_charge", on_delete=models.PROTECT)
    kind = models.CharField(max_length=5, choices=[(NIGHT, "Night"), (TILL, "From the till"), (EXTRA, "Extra")])
    night = models.DateField(null=True, blank=True)  # the night charged
    description = models.CharField(max_length=120, blank=True)  # an extra's own words: "Laundry", "Extra bed"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["stay", "night"], condition=Q(night__isnull=False), name="hote_staycharge_one_per_night")]


class StayDeposit(TimeStamped):
    """Money the guest paid towards their bill. Held for the guest until used against charges; any left is refunded."""
    stay = models.ForeignKey(Stay, related_name="deposits", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=6, choices=[("CASH", "Cash"), ("MPESA", "M-Pesa"), ("BANK", "Bank")])
    reference = models.CharField(max_length=100, blank=True)
    used = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    refunded = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    @property
    def held(self):
        return self.amount - self.used - self.refunded

    class Meta:
        ordering = ["created_at", "pk"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="hote_staydeposit_positive")]
