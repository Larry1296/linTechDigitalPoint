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
the commission M-KOPA pays per phone sold on it. A sale keeps the plan's terms and commission as they were on the day,
so changing a plan never changes what earlier sales earned. A plan left out when a phone is changed stops being sold
and stays on record for its sales.

## Commission figures

- **Commission from those sales**: the commission of every sale not undone (what the sales earn).
- **M-KOPA has paid you**: commission payments not undone. This is what the dashboard counts as the part's profit.
- **M-KOPA still owes you**: the first less the second (never below zero; paying more shows as a bonus line).
- **What would I earn?**: type how many phones on each plan; the commission is added up.

## Who sees what

An employee given the M-KOPA page records phones received and sells phones. The plans' commission, M-KOPA's payments,
setting up phones and plans, and undoing sales or stock entries are the owner's.
