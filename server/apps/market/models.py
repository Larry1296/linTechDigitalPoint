"""Public market data the platform looks up once and every business shares, such as money market fund rates.

Nothing here belongs to a business, so these are not tenant tables (business data lives in the domain apps).
"""
from django.db import models
from django.utils import timezone


class FundRateCheck(models.Model):
    """One look at a fund's published rate, shared by every business invested in it (see fund_rates.py).

    APPLIED rows are the fund's rate history; UNCONFIRMED is a big jump waiting for a second look to agree; FAILED is a
    check that found nothing usable (the reason is for the platform owner only).
    """
    APPLIED, UNCONFIRMED, FAILED = 'APPLIED', 'UNCONFIRMED', 'FAILED'
    fund = models.CharField(max_length=40)
    status = models.CharField(max_length=12, choices=[(x, x.title()) for x in [APPLIED, UNCONFIRMED, FAILED]])
    # The fund's "daily rate": its yearly rate, worked out daily (÷ 365), after the fund's fees and before withholding tax.
    annual_rate = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    effective_annual_rate = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    as_of = models.DateField(null=True, blank=True)  # the date the fund gave for the rate, else the day it was read
    source_url = models.URLField(max_length=500, blank=True)
    message = models.TextField(blank=True)
    checked_at = models.DateTimeField(default=timezone.now)
    class Meta:
        ordering = ['-checked_at', '-pk']
        indexes = [models.Index(fields=['fund', 'status', '-checked_at'], name='market_fundrate_latest')]
