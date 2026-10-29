from datetime import date

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.permissions import IsInternalStaff
from apps.tenancy.permissions import has_business_permission

from . import menu, rooms
from .models import KitchenIngredient, KitchenUse, MenuItem, Room, RoomType, Stay

money = lambda: serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0)


def need(request, *permissions):
    if not any(has_business_permission(request.user, permission) for permission in permissions):
        raise PermissionDenied("You don't have access to this.")


def valid(form_class, data, partial=False):
    form = form_class(data=data, partial=partial)
    form.is_valid(raise_exception=True)
    return form.validated_data


# Menu and kitchen ------------------------------------------------------------------------------------------------

def item_data(item):
    variant = item.variant
    return {"id": item.pk, "variant_id": variant.pk, "name": variant.product.name, "group": variant.product.category.name,
            "price": variant.selling_price, "available": item.available, "active": variant.product.active}


class MenuInput(serializers.Serializer):
    name = serializers.CharField(max_length=180)
    price = money()
    group = serializers.CharField(max_length=120, required=False, allow_blank=True)
    available = serializers.BooleanField(required=False)
    active = serializers.BooleanField(required=False)


@api_view(["GET", "POST"])
@permission_classes([IsInternalStaff])
def menu_items(request):
    if request.method == "GET":
        need(request, "hotel.view_menuitem", "commerce.add_sale")
        items = MenuItem.objects.select_related("variant__product__category").order_by("variant__product__category__name", "variant__product__name")
        return Response([item_data(item) for item in items])
    need(request, "hotel.add_menuitem")
    data = valid(MenuInput, request.data)
    return Response(item_data(menu.add_item(name=data["name"], price=data["price"], group=data.get("group") or "Menu")), status=201)


@api_view(["PATCH"])
@permission_classes([IsInternalStaff])
def menu_item(request, pk):
    item = get_object_or_404(MenuItem.objects.select_related("variant__product__category"), pk=pk)
    data = valid(MenuInput, request.data, partial=True)
    # Marking a dish as run out is the kitchen's and cashier's everyday job; changing the menu is a manager's.
    need(request, "hotel.change_menuitem", *(["commerce.add_sale"] if set(data) <= {"available"} else []))
    menu.change_item(item, name=data.get("name"), price=data.get("price"), group=data.get("group") or None,
                     available=data.get("available"), active=data.get("active"))
    item.refresh_from_db()
    return Response(item_data(MenuItem.objects.select_related("variant__product__category").get(pk=item.pk)))


def ingredient_data(ingredient):
    from apps.inventory.models import StockBalance
    from django.db.models import DecimalField, ExpressionWrapper, F, Sum
    variant = ingredient.variant
    rows = StockBalance.objects.filter(lot__variant=variant)
    value = rows.aggregate(v=Sum(ExpressionWrapper(F("quantity") * F("lot__unit_cost"), output_field=DecimalField())))["v"] or 0
    return {"id": ingredient.pk, "variant_id": variant.pk, "name": variant.product.name, "unit": "" if variant.name == "Standard" else variant.name,
            "in_store": menu.in_store(variant), "value": round(value, 2), "minimum": variant.minimum_stock, "sold_at_till": ingredient.sold_at_till,
            "active": variant.product.active}


class IngredientInput(serializers.Serializer):
    name = serializers.CharField(max_length=180, required=False, allow_blank=True)
    unit = serializers.CharField(max_length=40, required=False, allow_blank=True)
    variant_id = serializers.IntegerField(required=False)
    sold_at_till = serializers.BooleanField(required=False, default=False)


@api_view(["GET", "POST"])
@permission_classes([IsInternalStaff])
def ingredients(request):
    if request.method == "GET":
        need(request, "hotel.view_kitchenuse", "hotel.add_kitchenuse")
        rows = KitchenIngredient.objects.select_related("variant__product").filter(variant__product__active=True).order_by("variant__product__name")
        return Response([ingredient_data(row) for row in rows])
    need(request, "hotel.add_kitcheningredient")
    data = valid(IngredientInput, request.data)
    if not data.get("variant_id") and not (data.get("name") or "").strip():
        raise ValidationError("Enter the ingredient's name.")
    return Response(ingredient_data(menu.add_ingredient(name=data.get("name"), unit=data.get("unit"), variant_id=data.get("variant_id"),
                                                        sold_at_till=data.get("sold_at_till"))), status=201)


@api_view(["PATCH"])
@permission_classes([IsInternalStaff])
def ingredient(request, pk):
    need(request, "hotel.change_kitcheningredient")
    row = get_object_or_404(KitchenIngredient.objects.select_related("variant__product"), pk=pk)
    if "sold_at_till" in request.data:
        row.sold_at_till = bool(request.data.get("sold_at_till"))
        row.save(update_fields=["sold_at_till", "updated_at"])
    return Response(ingredient_data(row))


def use_data(use):
    return {"id": use.pk, "number": use.number, "used_on": use.used_on, "way": use.way, "note": use.note, "total_cost": use.total_cost,
            "recorded_by": use.recorded_by.get_full_name() or use.recorded_by.username if use.recorded_by else "",
            "lines": [{"name": line.variant.product.name, "unit": "" if line.variant.name == "Standard" else line.variant.name,
                       "quantity": line.quantity, "left": line.left, "cost": line.cost} for line in use.lines.all()]}


class UseInput(serializers.Serializer):
    way = serializers.ChoiceField(choices=[KitchenUse.USED, KitchenUse.COUNTED])
    used_on = serializers.DateField(required=False)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)
    lines = serializers.ListField(child=serializers.DictField(), allow_empty=False)


@api_view(["GET", "POST"])
@permission_classes([IsInternalStaff])
def kitchen_use(request):
    if request.method == "GET":
        need(request, "hotel.view_kitchenuse")
        rows = KitchenUse.objects.select_related("recorded_by").prefetch_related("lines__variant__product")[:60]
        return Response([use_data(row) for row in rows])
    need(request, "hotel.add_kitchenuse")
    data = valid(UseInput, request.data)
    use = menu.record_use(user=request.user, way=data["way"], lines=data["lines"], used_on=data.get("used_on"), note=data.get("note", ""))
    return Response(use_data(use), status=201)


# Rooms ------------------------------------------------------------------------------------------------------------

def type_data(room_type):
    return {"id": room_type.pk, "name": room_type.variant.product.name, "rate": room_type.variant.selling_price, "sleeps": room_type.sleeps,
            "active": room_type.active, "rooms": room_type.rooms.filter(active=True).count()}


class RoomTypeInput(serializers.Serializer):
    name = serializers.CharField(max_length=180)
    rate = money()
    sleeps = serializers.IntegerField(min_value=1, max_value=20, required=False, default=2)
    active = serializers.BooleanField(required=False)


@api_view(["GET", "POST"])
@permission_classes([IsInternalStaff])
def room_types(request):
    if request.method == "GET":
        need(request, "hotel.view_stay", "hotel.view_room")
        return Response([type_data(t) for t in RoomType.objects.filter(extra=False).select_related("variant__product").order_by("variant__selling_price")])
    need(request, "hotel.add_roomtype")
    data = valid(RoomTypeInput, request.data)
    return Response(type_data(rooms.add_room_type(name=data["name"], rate=data["rate"], sleeps=data["sleeps"])), status=201)


@api_view(["PATCH"])
@permission_classes([IsInternalStaff])
def room_type(request, pk):
    need(request, "hotel.change_roomtype")
    row = get_object_or_404(RoomType.objects.select_related("variant__product"), pk=pk, extra=False)
    data = valid(RoomTypeInput, request.data, partial=True)
    rooms.change_room_type(row, name=data.get("name"), rate=data.get("rate"), sleeps=data.get("sleeps"), active=data.get("active"))
    return Response(type_data(row))


class RoomInput(serializers.Serializer):
    number = serializers.CharField(max_length=20)
    room_type = serializers.IntegerField()
    floor = serializers.CharField(max_length=40, required=False, allow_blank=True)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)
    condition = serializers.ChoiceField(choices=[Room.READY, Room.DIRTY, Room.OUT_OF_ORDER], required=False)
    active = serializers.BooleanField(required=False)


def _room_type(pk):
    found = RoomType.objects.filter(pk=pk, extra=False).first()
    if not found:
        raise ValidationError("Choose a kind of room.")
    return found


@api_view(["GET", "POST"])
@permission_classes([IsInternalStaff])
def room_list(request):
    if request.method == "GET":
        need(request, "hotel.view_stay", "hotel.view_room")
        day = request.query_params.get("date")
        try:
            day = date.fromisoformat(day) if day else None
        except ValueError:
            raise ValidationError("Choose a valid date.")
        rooms.bring_up_to_date()
        return Response(rooms.board(day))
    need(request, "hotel.add_room")
    data = valid(RoomInput, request.data)
    room = rooms.add_room(number=data["number"], room_type=_room_type(data["room_type"]), floor=data.get("floor", ""), note=data.get("note", ""))
    return Response({"id": room.pk, "number": room.number}, status=201)


@api_view(["PATCH"])
@permission_classes([IsInternalStaff])
def room_detail(request, pk):
    room = get_object_or_404(Room, pk=pk)
    data = valid(RoomInput, request.data, partial=True)
    # Cleaning a room (its condition) is the front desk's job; renaming or re-pricing it is the owner's.
    need(request, "hotel.change_room", *(["hotel.change_stay"] if set(data) <= {"condition", "note"} else []))
    if "room_type" in data:
        data["room_type"] = _room_type(data["room_type"])
    rooms.change_room(room, **data)
    return Response({"id": room.pk, "number": room.number, "condition": room.condition})


def stay_data(stay, with_bill=False):
    data = {"id": stay.pk, "number": stay.number, "room": {"id": stay.room_id, "number": stay.room.number,
                                                           "type": stay.room.room_type.variant.product.name},
            "guest_id": stay.guest_id, "guest": stay.guest_name, "phone": stay.phone, "id_number": stay.id_number, "guests": stay.guests,
            "arrival": stay.arrival, "departure": stay.departure, "nights": (stay.departure - stay.arrival).days, "rate": stay.rate,
            "status": stay.status, "status_label": stay.get_status_display(), "checked_in_at": stay.checked_in_at,
            "checked_out_at": stay.checked_out_at, "note": stay.note}
    if with_bill:
        data["bill"] = rooms.bill(stay)
    return data


class BookInput(serializers.Serializer):
    room = serializers.IntegerField()
    arrival = serializers.DateField(required=False)
    departure = serializers.DateField()
    guest_id = serializers.IntegerField(required=False)
    guest_name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    id_number = serializers.CharField(max_length=40, required=False, allow_blank=True)
    guests = serializers.IntegerField(min_value=1, max_value=40, required=False, default=1)
    rate = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)
    check_in_now = serializers.BooleanField(required=False, default=False)
    # Paid now, with the booking (a deposit) or on checking in.
    paid = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    method = serializers.ChoiceField(choices=["CASH", "MPESA", "BANK"], required=False)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)


@api_view(["GET", "POST"])
@permission_classes([IsInternalStaff])
def stays(request):
    if request.method == "GET":
        need(request, "hotel.view_stay")
        rows = rooms.find(request.query_params.get("q")).select_related("room__room_type__variant__product")
        status = request.query_params.get("status")
        if status:
            rows = rows.filter(status__in=status.split(","))
        return Response([stay_data(s) for s in rows[:100]])
    need(request, "hotel.add_stay")
    data = valid(BookInput, request.data)
    with transaction.atomic():
        stay = rooms.book(user=request.user, room=get_object_or_404(Room, pk=data["room"]), arrival=data.get("arrival"),
                          departure=data["departure"], guest_id=data.get("guest_id"), guest_name=data.get("guest_name", ""),
                          phone=data.get("phone", ""), id_number=data.get("id_number", ""), guests=data.get("guests"),
                          rate=data.get("rate"), note=data.get("note", ""), check_in_now=data.get("check_in_now"))
        if data.get("paid"):
            need(request, "hotel.add_staydeposit")
            rooms.receive(stay, user=request.user, amount=data["paid"], method=data.get("method") or "CASH", reference=data.get("reference", ""))
    stay.refresh_from_db()
    return Response(stay_data(stay, with_bill=True), status=201)


def _stay(pk):
    return get_object_or_404(Stay.objects.select_related("room__room_type__variant__product"), pk=pk)


@api_view(["GET", "PATCH"])
@permission_classes([IsInternalStaff])
def stay_detail(request, pk):
    stay = _stay(pk)
    if request.method == "GET":
        need(request, "hotel.view_stay")
        if stay.status == Stay.IN:
            rooms.charge_due_nights(stay)
        return Response(stay_data(stay, with_bill=True))
    need(request, "hotel.change_stay")
    data = request.data
    parse = lambda key: date.fromisoformat(data[key]) if data.get(key) else None
    try:
        arrival, departure = parse("arrival"), parse("departure")
    except ValueError:
        raise ValidationError("Choose a valid date.")
    rooms.change_stay(stay, user=request.user, room=get_object_or_404(Room, pk=data["room"]) if data.get("room") else None,
                      arrival=arrival, departure=departure, rate=data.get("rate"), guests=data.get("guests"),
                      id_number=data.get("id_number"), phone=data.get("phone"))
    return Response(stay_data(_stay(pk), with_bill=True))


@api_view(["POST"])
@permission_classes([IsInternalStaff])
def stay_action(request, pk, action):
    stay = _stay(pk)
    data = request.data
    if action == "check-in":
        need(request, "hotel.change_stay")
        with transaction.atomic():
            rooms.check_in(stay, user=request.user, id_number=data.get("id_number"))
            if data.get("paid") not in (None, "", 0, "0"):
                need(request, "hotel.add_staydeposit")
                rooms.receive(stay, user=request.user, amount=data["paid"], method=data.get("method") or "CASH", reference=data.get("reference", ""))
    elif action == "payments":
        need(request, "hotel.add_staydeposit")
        rooms.receive(stay, user=request.user, amount=data.get("amount"), method=data.get("method") or "CASH", reference=data.get("reference", ""))
    elif action == "extras":
        need(request, "hotel.change_stay")
        rooms.add_extra(stay, user=request.user, description=data.get("description"), amount=data.get("amount"), key=data.get("idempotency_key"))
    elif action == "check-out":
        need(request, "hotel.change_stay")
        if data.get("leave_owing"):
            need(request, "commerce.change_sale")  # letting a guest leave owing is a manager's decision
        payment = data.get("payment") or None
        if payment:
            need(request, "hotel.add_staydeposit")
        rooms.check_out(stay, user=request.user, payment=payment, give_back_by=data.get("give_back_by") or None,
                        leave_owing=bool(data.get("leave_owing")))
    elif action == "cancel":
        need(request, "hotel.change_stay")
        rooms.cancel(stay, user=request.user, reason=str(data.get("reason") or "")[:200], no_show=bool(data.get("no_show")),
                     keep_paid=bool(data.get("keep_paid")), give_back_by=data.get("give_back_by") or None)
    else:
        raise ValidationError("Unknown action.")
    return Response(stay_data(_stay(pk), with_bill=True))


@api_view(["GET"])
@permission_classes([IsInternalStaff])
def in_house(request):
    need(request, "hotel.view_stay")
    return Response(rooms.in_house())


@api_view(["GET", "PATCH"])
@permission_classes([IsInternalStaff])
def hotel_settings(request):
    from apps.tenancy.models import Organization
    organization = Organization.objects.get(pk=request.organization.pk)
    if request.method == "PATCH":
        need(request, "hotel.change_room")
        value = str(request.data.get("checkout_time") or "").strip()
        try:
            from datetime import time
            time.fromisoformat(value)
        except ValueError:
            raise ValidationError("Enter the check-out time as hh:mm, for example 10:00.")
        organization.settings = {**(organization.settings or {}), "checkout_time": value[:5]}
        organization.save(update_fields=["settings"])
    return Response({"checkout_time": rooms.checkout_time(organization).strftime("%H:%M")})
