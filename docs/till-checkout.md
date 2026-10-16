# Till checkout and M-Pesa payments

How the point of sale takes payment, and what Safaricom must provide for till payments to be confirmed automatically.
Code: `server/apps/commerce/checkout.py`, `checkout_api.py`, `mpesa_express.py`; screen: `client/src/modules/pos/CheckoutPanel.jsx`.

## The flow

1. **Charge.** The cashier presses *Charge*. The basket, its agreed prices and the exact amount are frozen in a
   `Checkout` after a rehearsal of the real sale (run and rolled back), so stock, prices and the below-cost rule are
   checked now. Nothing is sold yet: no stock leaves and nothing reaches the books.
2. **Pay.** One way or several (`CheckoutPayment`):
   - **Cash**: the cashier enters the cash given; the change is shown.
   - **Till / paybill**: a payment Safaricom reported (see below) is attached to the checkout.
   - **Prompt (STK push)**: confirmed by Safaricom's answer to that very prompt (its `CheckoutRequestID`).
   - **Bank**: the cashier records the transfer reference after checking the account.
   - **Owed**: the rest, by a named customer, with an optional due date.
3. **Sale.** When the payments cover the amount, the sale is made exactly once from the frozen basket by the same
   `complete_sale` as every sale, and each payment becomes a `Payment` on it; the books follow as for any sale.
   If stock sold out meanwhile, the checkout stays **Paid, sale not made yet** with its money; *Try again* after
   receiving stock, or a manager cancels and refunds.

A reloaded till returns to the cashier's open checkout. Unpaid checkouts with no money on them expire after 30 minutes.
Each cashier sees only their own checkouts; the owner and managers see the branch's.

## How till payments are matched

Safaricom's notice of a Buy Goods payment (C2B confirmation) carries the M-Pesa code, amount, time, the customer's
masked number and first name, and **nothing that names the basket**. Two customers paying KSh 850 at the same second
look alike. So:

- Every payment Safaricom reports is kept once in `IncomingMpesaPayment` (unique M-Pesa code per business), whether it
  came as a till notice or a prompt's answer. Repeated notices change nothing.
- A till payment is **never** applied because its amount matches. The checkout lists the payments that just arrived
  (exact amount first, with code, time, name and masked number); the cashier taps the customer's own, or enters the
  code from the customer's SMS, which must be one Safaricom reported.
- A payment can pay one sale only (`CheckoutPayment.incoming` is one to one, taken under a row lock). A second
  cashier trying the same payment is refused.
- Paid more than the sale: the sale takes what it needs; the extra stays traceable as "paid more, give it back".
  Paid less: the checkout is partly paid and the rest is taken another way.
- A payment no sale claims (or one freed by a cancelled checkout, or a prompt answered after the customer left) stays
  in the ledger. The owner and managers see it at `GET /api/v1/commerce/till-payments/` and record what became of it
  (`.../settle/`, e.g. "refunded").
- **Paybill**: a payment whose account number is the checkout's number (e.g. `POS-AB12CD34EF`) names the checkout and is
  attached by itself.
- A business **not** connected to Safaricom can still enter the code from the SMS; it is recorded as typed and marked
  *not checked with Safaricom*.

## What each business needs from Safaricom

In **Settings → M-Pesa payments** the owner enters the till (store number and till number) or paybill and the keys of
their own Daraja app. The platform then:

1. checks the Consumer Key and Secret with Safaricom;
2. registers the till's payment-notice address (C2B Register URL, `/mpesa/c2b/v2/registerurl`) with the store number
   (or paybill number). The address is `https://<platform>/api/v1/tenancy/payments/till/<hex secret>/confirm/`: it
   never contains words Safaricom refuses (M-Pesa, Safaricom, exe, sql, query…) and never changes, because live
   registration is once per short code;
3. the owner sends a KSh 1 test prompt to their own phone.

The Daraja app must be taken **live** with:
- **M-Pesa Express (Lipa na M-Pesa Online)** for prompts, with its passkey;
- **Customer To Business (C2B)** for till/paybill payment notices.

Settings shows whether till payments are reported, Safaricom's reason if not, and *Try again*.

## Platform settings

| Setting | Purpose |
|---|---|
| `MPESA_CALLBACK_BASE_URL` | The platform's public **HTTPS** address Safaricom posts to. Without it, nothing can be reported. |
| `MPESA_CALLBACK_IPS` | Optional, comma separated: Safaricom's callback IP addresses. When set, notices from any other address are refused. Behind the proxy (`BEHIND_HTTPS_PROXY`), the address the proxy added is used. |
| `MPESA_MODE=simulate` with `DEBUG=True` | Development only: prompts answer themselves and the checkout offers *Simulate a till payment*. Never active in production. |

## Security notes

- Safaricom does not sign C2B notices. They are accepted only at the business's secret address (and, when configured,
  only from Safaricom's addresses), stored once per code, and they pay for nothing until attached to a sale as above.
  Set `MPESA_CALLBACK_IPS` in production.
- Stronger proof per payment (Safaricom's Transaction Status API, or the Pull Transactions API for reconciliation)
  needs extra Daraja products and an initiator credential; it is not used yet.
- M-Pesa agency float and deposits never enter this ledger: they belong to the agency desk.

## Not done yet

Cashier registers and shifts (opening float, drawer count at close, shift reports), held carts, a reconciliation
screen for unmatched payments (the API exists), thermal-receipt layouts, and dynamic QR.
