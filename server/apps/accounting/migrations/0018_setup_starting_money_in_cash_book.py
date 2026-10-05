"""Starting money entered at business setup was posted to the books only, not the cash book, so Money check, the
drawer and net worth left it out. Add the matching cash-book entry for each business; its journal already exists."""
from django.db import migrations

METHODS = {"1000": "CASH", "1010": "BANK"}


def add_cash_book_entries(apps, schema_editor):
    JournalEntry = apps.get_model("accounting", "JournalEntry")
    JournalLine = apps.get_model("accounting", "JournalLine")
    CashAccount = apps.get_model("accounting", "CashAccount")
    CashEntry = apps.get_model("accounting", "CashEntry")
    for entry in JournalEntry.objects.filter(source_key="setup:opening"):
        org = entry.organization_id
        for line in JournalLine.objects.filter(entry_id=entry.pk, account__code__in=METHODS, debit__gt=0):
            method = METHODS[line.account.code]
            key = f"opening:setup-{method.lower()}"
            if CashEntry.objects.filter(organization_id=org, source_key=key).exists():
                continue
            account = CashAccount.objects.filter(organization_id=org, business_unit="SHOP", payment_method=method).order_by("pk").first()
            if account is None:
                account = CashAccount.objects.create(organization_id=org, name=f"SHOP {method}", business_unit="SHOP", payment_method=method)
            CashEntry.objects.create(organization_id=org, account_id=account.pk, business_unit="SHOP", kind="OPENING", amount=line.debit,
                                     reference="Starting money entered at setup", source_key=key, branch_id=entry.branch_id,
                                     occurred_at=entry.created_at, created_at=entry.created_at, created_by_id=entry.created_by_id)


class Migration(migrations.Migration):
    dependencies = [("accounting", "0017_net_worth_snapshots")]
    operations = [migrations.RunPython(add_cash_book_entries, migrations.RunPython.noop)]
