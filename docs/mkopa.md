# M-KOPA phones

A business that sells phones for M-KOPA as a dealer turns on **M-KOPA phones** (Settings, or the setup question
"Do you sell M-KOPA phones?"). It is its own part of the business (unit `MKOPA`), beside the shop, services and the
M-Pesa agency. Its page is `/admin/mkopa`.

## What is the business's

- The phones belong to M-KOPA until customers pay them off. They are counted on the M-KOPA page (received from
  M-KOPA, given back, sold, in hand), never as shop stock, and they never change the business's money.
- Customers pay the deposit and the daily payments to M-KOPA, not to the dealer, so none of it is in the books.
- The dealer's money is the **commission** M-KOPA pays for each phone sold. It counts as profit on the day M-KOPA pays
  it, into the place it was paid to (cash, M-Pesa, bank, other): a cash-book entry of the `MKOPA` part and a journal
  crediting **4050 M-KOPA phone commission**. Undoing a payment reverses both.

## Phones and plans

Each phone (X30, X4e, X4…) has one or two plans: a deposit, then so much a day for so many days. The customer pays
M-KOPA deposit + daily × days in all (X30: 3,899 + 93 × 365 = 37,844, or 5,999 + 130 × 180 = 29,399). Each plan has
the commission M-KOPA pays per phone sold on it, typed or learned (below). A sale keeps the plan's terms as they were
on the day; until M-KOPA pays for it, it is expected to earn its plan's commission as now known, and once paid, what
M-KOPA paid for it. A plan left out when a phone is changed stops being sold
and stays on record for its sales.

## Learning the commission from M-KOPA's payments

The owner may type a plan's commission, or leave it blank. When M-KOPA pays, the owner records the payment and ticks the
phones sold it covers (every unpaid phone sold by that day is ticked to start with). Each payment is one equation, e.g.
4 × (X30 plan 1) + 2 × (X30 plan 2) = 7,800. `apps/mkopa/learning.py` solves all the payments together by least squares
in exact fractions, so a bonus or deduction in one payment is evened out by the rest. A plan's commission is learned
only once the payments pin it down on its own (a plan always paid together with another in the same mix cannot be told
apart yet). Everything is worked out again after each payment is recorded or undone.

- The learned commission replaces the typed one wherever the app needs a plan's commission: the next sales, what
  M-KOPA still owes, the calculator. The page says which it is ("learned from N payments" or "typed by you").
- Each payment is split between the phones it paid for in proportion to their plans' commission, adding up to exactly
  what M-KOPA paid, so each plan shows how much M-KOPA has paid for its phones.
- A phone already paid for cannot be undone until its payment is undone.

## Commission figures

- **M-KOPA has paid you**: commission payments not undone. This is what the dashboard counts as the part's profit.
- **M-KOPA still owes you**: for every phone not paid for yet, its plan's commission as now known. Phones on plans whose
  commission is not known yet are counted apart and not included.
- **Commission earned**: the two together.
- **What would I earn?**: type how many phones on each plan; the commission is added up.

## Who sees what

An employee given the M-KOPA page records phones received and sells phones. The plans' commission, M-KOPA's payments,
setting up phones and plans, and undoing sales or stock entries are the owner's.
