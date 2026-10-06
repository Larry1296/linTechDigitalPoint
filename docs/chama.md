# Chama management

A Pro tool for business owners who are also the treasurer (or another leader) of a chama: a savings group whose
members contribute an agreed amount every day, week or month, and usually take turns receiving the money
(merry-go-round). It can be chosen as a tool at registration, which adds a **Your chama** step, or set up later from
the dashboard (**Set up a chama**) or the **Chama** menu. Both use the same form (`client/src/modules/chama/ChamaSetupFields.jsx`).
Setting it up from the dashboard turns the `chama` module on for the business, within its plan.

## Kept apart from the shop

The chama's money belongs to its members. Nothing in `apps/chama` posts to the shop's cash book (`CashEntry`) or
ledger (`JournalEntry`), so the shop's sales, profit, money check, net worth and reports never include it. The chama
keeps its own records and shows its own figures: money the treasurer holds = everything paid in − everything given out.

Members' ID numbers and the chama's money are private to the chama: only the owner and administrators get chama
permissions by default. Managers, read-only staff and other roles get them only when granted one by one.

## Rules

- **Schedule.** Contributions fall on the first contribution date and then every day, week or month after it. A
  monthly chama starting on the 31st falls on the last day of shorter months. Frequency and the first date cannot
  change once contributions have started; the amount, grace days and fine can, and apply to later contributions only.
- **Who has paid.** Each member owes each contribution from the day they joined until the day after they leave.
  A payment pays the member's oldest unpaid contributions first, then unpaid fines, then up to 12 contributions ahead.
- **Fines.** Once a contribution's deadline (its date + the grace days) has passed, the fine rule is applied to it
  exactly once: if less than the full contribution was paid on or before the deadline, the chama's fine at that moment
  is charged. Contributions that fell due before the chama (or a member) was added are never fined. If a payment that
  was made on time is recorded after the fine, the fine is cancelled automatically. The treasurer can waive a fine
  with a reason.
- **Excuses.** A member who says they will pay late (in advance or before the deadline) gives a reason and a date
  they promise to pay by (up to 90 days later). They are fined only if they have not paid in full by that date.
- **Turns.** In a rotating chama, a turn is one or more contributions (`periods_per_round`). Members receive the
  money in turn order, once per cycle; the order can be changed and a payout can go to a different member (a swap),
  which the schedule then follows. Payouts are recorded in turn order and only the latest can be reversed.
- **Who receives next.** A chama chooses either *in the order listed* or *the members agree who receives next*. A
  common chama: everyone gives 100 every day, and after a week (7 contributions per turn) one member receives; the
  members then agree who receives the next week. The treasurer records the agreed member (with a note) under
  Turns, or picks the first receiver at set-up. Only members who have not yet received in the current round of
  turns can be chosen; each member receives once before anyone receives again. In listed order, an agreement lets
  a member go next out of order. When the members agree each turn, the money cannot be given out until the next
  receiver is recorded. The agreement is cleared once that turn is given out.
- **Corrections.** Nothing is deleted. A payment or payout entered by mistake is reversed with a reason; reversing a
  payment makes the member owe it again and re-applies the fine rule. Changes are written to the audit log.

## API (`/api/v1/chama/`)

| Path | Use |
| --- | --- |
| `setup/` | GET whether the business can set up a chama; POST to set one up (turns the module on) |
| `` (root) | GET every chama at a glance |
| `<id>/` | GET the full chama (board, members, turns, fines, excuses, money record); PATCH its rules |
| `<id>/members/`, `<id>/members/<m>/`, `.../leave/` | add, change, see a statement, or record a member leaving |
| `<id>/turns/` | POST `{order: [member ids]}` |
| `<id>/next-receiver/` | POST `{member, note}` the member agreed to receive next; `{member: null}` clears it |
| `<id>/payments/`, `payments/<p>/reverse/` | money in, and its correction |
| `<id>/excuses/` | POST `{member, period_date, pay_by, reason}` |
| `dues/<d>/waive-fine/` | waive a fine with a reason |
| `<id>/payouts/`, `payouts/<p>/reverse/` | money given out, and its correction |
