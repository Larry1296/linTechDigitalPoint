from django.apps import AppConfig


class MpesaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mpesa"

    def ready(self):
        # A new reading or transaction may change the commission table shared by all agents.
        from django.db.models.signals import post_save
        from .commission_shared import forget
        from .models import MpesaSession, MpesaTransaction
        post_save.connect(forget, sender=MpesaTransaction, dispatch_uid="mpesa-shared-commission-transaction")
        post_save.connect(forget, sender=MpesaSession, dispatch_uid="mpesa-shared-commission-session")
