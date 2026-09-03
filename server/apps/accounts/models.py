from django.conf import settings
from django.db import models
from apps.core.models import TimeStamped
class CustomerProfile(TimeStamped):
    user=models.OneToOneField(settings.AUTH_USER_MODEL,related_name="customer_profile",on_delete=models.CASCADE); phone=models.CharField(max_length=30,blank=True)
    def __str__(self): return self.user.get_full_name() or self.user.username
class CustomerAddress(TimeStamped):
    profile=models.ForeignKey(CustomerProfile,related_name="addresses",on_delete=models.CASCADE); label=models.CharField(max_length=60,default="Home"); recipient_name=models.CharField(max_length=160); phone=models.CharField(max_length=30); county=models.CharField(max_length=100); town=models.CharField(max_length=100); address_line=models.CharField(max_length=255); directions=models.TextField(blank=True); is_default=models.BooleanField(default=False)
    class Meta: ordering=["-is_default","-updated_at"]

