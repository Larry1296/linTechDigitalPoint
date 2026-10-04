from django.db import migrations

SQL = """
ALTER TABLE accounting_journalentry ADD COLUMN posting_transaction bigint NOT NULL DEFAULT txid_current();
CREATE FUNCTION accounting_immutable_journal() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Posted journals are immutable; post a reversal' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER immutable_journal BEFORE UPDATE OR DELETE ON accounting_journalentry
FOR EACH ROW EXECUTE FUNCTION accounting_immutable_journal();
CREATE TRIGGER immutable_journal_line BEFORE UPDATE OR DELETE ON accounting_journalline
FOR EACH ROW EXECUTE FUNCTION accounting_immutable_journal();

CREATE FUNCTION accounting_check_journal_balance() RETURNS trigger AS $$
DECLARE
    balance numeric;
    line_count integer;
BEGIN
    SELECT COALESCE(SUM(debit-credit), 0), COUNT(*) INTO balance, line_count
    FROM accounting_journalline WHERE entry_id = NEW.id;
    IF balance <> 0 OR line_count < 2 THEN
        RAISE EXCEPTION 'Journal must have at least two balanced lines' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER balanced_journal AFTER INSERT ON accounting_journalentry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting_check_journal_balance();

CREATE FUNCTION accounting_guard_journal_line() RETURNS trigger AS $$
DECLARE
    entry_xid bigint;
BEGIN
    SELECT posting_transaction INTO entry_xid FROM accounting_journalentry WHERE id = NEW.entry_id;
    IF entry_xid IS DISTINCT FROM txid_current() THEN
        RAISE EXCEPTION 'Lines can only be added while creating a journal' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER journal_line_creation BEFORE INSERT ON accounting_journalline
FOR EACH ROW EXECUTE FUNCTION accounting_guard_journal_line();
CREATE TRIGGER tenant_relationships BEFORE INSERT OR UPDATE ON accounting_journalentry
FOR EACH ROW EXECUTE FUNCTION tenancy_check_relationships('branch_id', 'core_store', 'created_by_id', 'auth_user', 'reversal_of_id', 'accounting_journalentry');
CREATE TRIGGER tenant_relationships BEFORE INSERT OR UPDATE ON accounting_journalline
FOR EACH ROW EXECUTE FUNCTION tenancy_check_relationships('entry_id', 'accounting_journalentry', 'account_id', 'accounting_ledgeraccount', 'created_by_id', 'auth_user');
CREATE TRIGGER tenant_relationships BEFORE INSERT OR UPDATE ON accounting_ledgeraccount
FOR EACH ROW EXECUTE FUNCTION tenancy_check_relationships();

CREATE FUNCTION accounting_guard_account() RETURNS trigger AS $$
BEGIN
    IF EXISTS(SELECT 1 FROM accounting_journalline WHERE account_id = OLD.id) THEN
        RAISE EXCEPTION 'Accounts with posted history cannot change classification' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER immutable_used_account BEFORE UPDATE ON accounting_ledgeraccount
FOR EACH ROW WHEN (OLD.kind IS DISTINCT FROM NEW.kind OR OLD.code IS DISTINCT FROM NEW.code OR OLD.is_cash IS DISTINCT FROM NEW.is_cash)
EXECUTE FUNCTION accounting_guard_account();
"""
REVERSE = """
DROP TRIGGER immutable_used_account ON accounting_ledgeraccount;
DROP FUNCTION accounting_guard_account();
DROP TRIGGER tenant_relationships ON accounting_ledgeraccount;
DROP TRIGGER tenant_relationships ON accounting_journalline;
DROP TRIGGER tenant_relationships ON accounting_journalentry;
DROP TRIGGER journal_line_creation ON accounting_journalline;
DROP FUNCTION accounting_guard_journal_line();
DROP TRIGGER balanced_journal ON accounting_journalentry;
DROP FUNCTION accounting_check_journal_balance();
DROP TRIGGER immutable_journal_line ON accounting_journalline;
DROP TRIGGER immutable_journal ON accounting_journalentry;
DROP FUNCTION accounting_immutable_journal();
ALTER TABLE accounting_journalentry DROP COLUMN posting_transaction;
"""

class Migration(migrations.Migration):
    dependencies = [('accounting', '0004_cashentry_branch_journalentry_ledgeraccount_and_more'), ('tenancy', '0005_branch_membership')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
