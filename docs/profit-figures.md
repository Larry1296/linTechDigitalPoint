# Profit figures: one way, checked, never guessed

Every profit the business sees is worked out from the posted books (PostgreSQL journal lines) by one formula. The
dashboard, the Reports summary, the assistant without an AI and the AI's tool all use it, so the same dates give the
same figures everywhere.

## Where the figures come from

`apps/inventory/dashboard.py`:

- `pnl_rows(start, end)` reads the journal lines for revenue, cost of goods sold and expense accounts, each tagged
  with its part (shop, services, M-Pesa agency, or investments). It also adds the *profit still owed by customers*
  rows from `apps/accounting/credit_profit.py`. Each of those rows names its sale.
- `profit_of(figures)` is the formula. `accrual_totals(rows, units)` adds the rows up and applies it.
- `visible_units_for(user, organization)` decides which parts a person may see. The dashboard and the assistant both
  use it.

`apps/accounting/profit_report.py` builds on these and adds:

- `report(start, end, units)`: every line of the formula, each part, where the interest, running costs and owed profit
  came from (down to each sale number and date), and the checks.
- `reconcile_figures(...)`: checks any breakdown against the formula.
- `find_figure(amount, units)`: finds which profit the business sees that an amount is.

## The accounting basis

The books use accrual accounting. Sales count on the day they are made, after discounts and excluding tax. The cost of
the items sold is each item's buying price from the stock lot it came from, oldest stock first (FIFO), so it is never
today's catalogue cost. Running costs count when they are incurred. One adjustment was chosen by the owner: a sale's
profit counts as its money comes in (the instalment method).

    Gross profit    = sales − cost of the items sold
    Profit received = gross profit − running costs − stock found or missing
                      + interest on investments (after fees) − profit still owed by customers

- **Money received is cash, not revenue.** When a customer pays for an older credit sale, no new sale is counted. Only
  that sale's profit comes in: the *profit still owed* line goes below zero for the dates it was paid in, which adds to
  profit received.
- **Interest on investments** belongs to no part of the business. It is added only to the whole business's profit.
- **Returns, refunds, price corrections and cancelled sales** change what is owed on the day they happen. A sale
  cancelled or refunded in full owes nothing.
- Amounts are `Decimal`, rounded half up to the cent; floats are never used for money.
- The dashboard's **"Profit so far"** counts every record, including records dated ahead (commission is dated on its
  month's last day). Its date section defaults to this month.
- The Reports page also shows **profit earned** (`statements.profit_and_loss`). That figure includes profit customers
  still owe and leaves out investment interest. It is a different figure, and it is labelled as one.

## Checks before anything is shown

`report()` checks three things: the whole business's lines give its profit through the formula, each part's lines give
its profit, and the parts (with interest) add up to the whole for every line. If a check fails, the report is returned
with `reconciled: False` and the failed checks, and the error is logged with the organization id, dates and differences.
Figures are never adjusted to make them agree, and no balancing entry is ever made.

## The assistant

- `explain_profit` (the AI's tool, which the no-AI answers also use) explains a profit from `report()`. Given a figure
  (for example 7,315), it finds which one the business sees: the dashboard headline, each part's figure since the start,
  this month, today or last month. If the figure is none of these, it says so and lists the nearest figures. It never
  explains a different figure in its place.
- **Without an AI** (no key, no credit, an outage), `offline.profit_and_loss` writes every non-zero line of the formula
  to the cent, so the lines add up on paper. It also gives the parts, the credit sales behind any owed profit, and
  whether the checks passed.
- **With an AI**, answers to money questions are held back until every money amount in them is found in what the tools
  returned for that answer (or is the sum or difference of two such figures): see `apps/assistant/grounding.py`. An
  answer quoting an amount the records do not hold is not shown. The business gets the answer from the records
  instead, the mismatch is logged, and only the platform owner is told why.

## Known limits

- The dashboard also shows "profit with unpaid commission" and "profit left in hand after restocking". `explain_profit`
  does not match figures to those two yet; the dashboard explains both next to them.
- The number check reads amounts written with a currency (KES, KSh, Sh). A bare number, or an amount worked out from
  three or more figures, is not checked. The AI's instructions forbid both.
