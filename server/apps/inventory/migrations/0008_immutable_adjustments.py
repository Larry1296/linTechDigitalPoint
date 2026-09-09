from django.db import migrations


SQL = """
CREATE FUNCTION inventory_guard_adjustment() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Posted stock adjustments are immutable; post a correcting adjustment instead';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER immutable_stock_adjustment BEFORE UPDATE OR DELETE ON inventory_stockadjustment
FOR EACH ROW EXECUTE FUNCTION inventory_guard_adjustment();
CREATE TRIGGER immutable_adjustment_movement BEFORE UPDATE OR DELETE ON inventory_movement
FOR EACH ROW WHEN (OLD.movement_type = 'STOCK_ADJUSTMENT' OR OLD.adjustment_id IS NOT NULL)
EXECUTE FUNCTION inventory_guard_adjustment();
"""
REVERSE = """
DROP TRIGGER immutable_adjustment_movement ON inventory_movement;
DROP TRIGGER immutable_stock_adjustment ON inventory_stockadjustment;
DROP FUNCTION inventory_guard_adjustment();
"""


class Migration(migrations.Migration):
    dependencies = [("inventory", "0007_movement_quantity_after_movement_quantity_before_and_more")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
