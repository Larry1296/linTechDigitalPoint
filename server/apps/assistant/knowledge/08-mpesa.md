# M-Pesa

## Does {platform} work with M-Pesa?
Yes, in two ways:
1. **Taking M-Pesa for sales**: at the point of sale, M-Pesa is a payment method alongside cash and bank. With your own till or paybill set up (Settings → M-Pesa payments), the till sends the customer a payment prompt on their phone and marks the sale paid by itself; otherwise the cashier records the payment with its M-Pesa code.
2. **M-Pesa agency**: if your business is an M-Pesa agent, the M-Pesa agency module manages your float and customer transactions.

## What does the M-Pesa agency module do?
It is built for M-Pesa agents. You set up your agent outlets, open a shift with the opening cash and opening float, and record customer deposits and withdrawals as they happen. {platform} shows the cash and float effect of each transaction, tracks commission, and helps you reconcile cash and float at the end of the shift. The agency keeps its own separate ledger so it does not mix with your shop's sales.

## How do I reconcile M-Pesa?
In the M-Pesa agency module, use the Reconciliation page to compare the cash and float you actually hold with what the system expects from the recorded transactions, and see any difference.

## How long does a shift run, and what are money checks?
A shift runs the working week: open it on Monday (or the week's first working day) and close it on Saturday with a full count of the cash and float. The agency is closed on Sundays. In between, the money is checked by surprise: when the shift opens, {platform} picks two working days at random, each at a random time in working hours, and nobody is told when they fall. When one comes due, the page asks whoever is on the desk to count the cash and read the float. The total money in operation (cash plus float) is compared with what the records say. An employee counts blind and the owner sees any difference. The owner can also press "Check money now" at any time. If the total agrees but the cash and float split does not, a deposit or withdrawal was probably not recorded or was recorded the wrong way round.

## Why does opening a shift ask why the cash or float differs?
A new shift should open with the cash and float the last shift closed with. When the counts differ, {platform} shows the difference and asks why (for example cash taken to the bank overnight). If the float is higher because Safaricom paid commission into it after the last shift closed, tick that option and enter the month and amount: it is recorded as that month's commission, and the float is not counted twice.

## How do I record Safaricom's commission?
On the Commission page, choose Record commission, the month it was earned, the amount, and where the money went:
- **Kept in the agency float**: recorded in the open shift; the float goes up by the commission.
- **Paid into the float, owner took it from the drawer as cash**: like a withdrawal, the float goes up and the drawer goes down by the same amount; the cash is the business's, kept outside the agency.
- **Put into the agency cash drawer**: the shift's cash goes up.
- **Already in the float when a shift opened**: Safaricom paid it between shifts and the opening float already counted it. Choose that shift; the float does not change, and only as much as that shift opened with above the last close can be commission.
- **Your own M-Pesa, bank, cash kept outside the agency, or other**: enter the date it was paid.
Commission always counts as income in the month it was earned. Undoing a commission takes its income out, so only undo one that was recorded by mistake.
