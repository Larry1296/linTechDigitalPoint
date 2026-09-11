from django.db import migrations


SQL = """
CREATE FUNCTION inventory_guard_receipt_correction() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Receipt corrections are immutable; post another correction instead';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER immutable_receipt_correction
BEFORE UPDATE OR DELETE ON inventory_stockreceiptlinecorrection
FOR EACH ROW EXECUTE FUNCTION inventory_guard_receipt_correction();
CREATE TRIGGER immutable_receipt_correction_movement
BEFORE UPDATE OR DELETE ON inventory_movement
FOR EACH ROW WHEN (OLD.receipt_correction_id IS NOT NULL)
EXECUTE FUNCTION inventory_guard_receipt_correction();
"""
REVERSE = """
DROP TRIGGER immutable_receipt_correction_movement ON inventory_movement;
DROP TRIGGER immutable_receipt_correction ON inventory_stockreceiptlinecorrection;
DROP FUNCTION inventory_guard_receipt_correction();
"""


class Migration(migrations.Migration):
    dependencies = [("inventory", "0009_stockreceiptlinecorrection_and_more")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
