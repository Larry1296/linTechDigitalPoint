from django.conf import settings
from django.db import models
class TimeStamped(models.Model):
    created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta: abstract=True
class Store(TimeStamped):
    name=models.CharField(max_length=160); currency=models.CharField(max_length=3,default="KES"); timezone=models.CharField(max_length=50,default="Africa/Nairobi"); measurement_unit=models.CharField(max_length=10,default="ft"); phone=models.CharField(max_length=30,blank=True); email=models.EmailField(blank=True); address=models.TextField(blank=True); receipt_footer=models.CharField(max_length=255,blank=True); reservation_timeout_minutes=models.PositiveIntegerField(default=30)
    def __str__(self): return self.name
class AuditLog(models.Model):
    action=models.CharField(max_length=80); object_type=models.CharField(max_length=80); object_id=models.CharField(max_length=64); user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL); before=models.JSONField(default=dict); after=models.JSONField(default=dict); ip_address=models.GenericIPAddressField(null=True); user_agent=models.CharField(max_length=300,blank=True); created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=["-created_at"]
