# Kyama (chama) management

A Pro tool for business owners who are also the treasurer (or another leader) of a kyama: a savings group whose
members contribute an agreed amount every day, week or month, and usually take turns receiving the money
(merry-go-round). It can be chosen as a tool at registration, which adds a **Your kyama** step, or set up later from
the dashboard (**Set up a kyama**) or the **Kyama** menu. Both use the same form (`client/src/modules/kyama/KyamaSetupFields.jsx`).
Setting it up from the dashboard turns the `kyama` module on for the business, within its plan.

## Kept apart from the shop

The kyama's money belongs to its members. Nothing in `apps/kyama` posts to the shop's cash book (`CashEntry`) or
ledger (`JournalEntry`), so the shop's sales, profit, money check, net worth and reports never include it. The kyama
keeps its own records and shows its own figures: money the treasurer holds = everything paid in − everything given out.

Members' ID numbers and the kyama's money are private to the kyama: only the owner and administrators get kyama
permissions by default. Managers, read-only staff and other roles get them only when granted one by one.

## Rules

- **Schedule.** Contributions fall on the first contribution date and then every day, week or month after it. A
  monthly kyama starting on the 31st falls on the last day of shorter months. Frequency and the first date cannot
  change once contributions have started; the amount, grace days and fine can, and apply to later contributions only.
- **Who has paid.** Each member owes each contribution from the day they joined until the day after they leave.
  A payment pays the member's oldest unpaid contributions first, then unpaid fines, then up to 12 contributions ahead.
- **Fines.** Once a contribution's deadline (its date + the grace days) has passed, the fine rule is applied to it
  exactly once: if less than the full contribution was paid on or before the deadline, the kyama's fine at that moment
  is charged. Contributions that fell due before the kyama (or a member) was added are never fined. If a payment that
  was made on time is recorded after the fine, the fine is cancelled automatically. The treasurer can waive a fine
  with a reason.
- **Excuses.** A member who says they will pay late (in advance or before the deadline) gives a reason and a date
  they promise to pay by (up to 90 days later). They are fined only if they have not paid in full by that date.
- **Turns.** In a rotating kyama, a turn is one or more contributions (`periods_per_round`). Members receive the
  money in turn order, once per cycle; the order can be changed and a payout can go to a different member (a swap),
  which the schedule then follows. Payouts are recorded in turn order and only the latest can be reversed.
- **Corrections.** Nothing is deleted. A payment or payout entered by mistake is reversed with a reason; reversing a
  payment makes the member owe it again and re-applies the fine rule. Changes are written to the audit log.

## API (`/api/v1/kyama/`)

| Path | Use |
| --- | --- |
| `setup/` | GET whether the business can set up a kyama; POST to set one up (turns the module on) |
| `` (root) | GET every kyama at a glance |
| `<id>/` | GET the full kyama (board, members, turns, fines, excuses, money record); PATCH its rules |
| `<id>/members/`, `<id>/members/<m>/`, `.../leave/` | add, change, see a statement, or record a member leaving |
| `<id>/turns/` | POST `{order: [member ids]}` |
| `<id>/payments/`, `payments/<p>/reverse/` | money in, and its correction |
| `<id>/excuses/` | POST `{member, period_date, pay_by, reason}` |
| `dues/<d>/waive-fine/` | waive a fine with a reason |
| `<id>/payouts/`, `payouts/<p>/reverse/` | money given out, and its correction |
