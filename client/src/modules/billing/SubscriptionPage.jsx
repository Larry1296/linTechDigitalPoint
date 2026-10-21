import { useCallback, useEffect, useState } from "react";
import Swal from "sweetalert2";
import { Check, Crown, Smartphone } from "lucide-react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { confirmAction, showError, showSuccess } from "../../core/ui/alerts";
import { ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { SubscriptionStatus } from "./SubscriptionBanner";
import "./billing.css";

const money = (currency, amount) => `${currency} ${Number(amount).toLocaleString()}`;
const dateText = (value) => (value ? new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
export const POLL_INTERVAL = { ms: 3000, attempts: 40 };

// Waits for the owner to answer the M-Pesa prompt on their phone.
async function waitForPayment(id) {
  for (let attempt = 0; attempt < POLL_INTERVAL.attempts; attempt += 1) {
    await sleep(POLL_INTERVAL.ms);
    const payment = await api(`/api/v1/tenancy/billing/payments/${id}/`);
    if (payment.status !== "PENDING") return payment;
  }
  return null;
}

export function SubscriptionPage() {
  const { user, refresh } = useAuth();
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const role = user?.roles?.[0];
  const canManage = role === "OWNER" || role === "ADMIN";
  const load = useCallback(() => {
    setError("");
    return api("/api/v1/tenancy/billing/").then((result) => {
      setData(result);
      setPhone((current) => current || result.phone || "");
    }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { if (canManage) void load(); }, [canManage, load]);

  if (!canManage) return <section className="billingPage"><h1>Subscription</h1>
    <SubscriptionStatus subscription={user.organization.subscription} />
    <p className="muted">Only the business owner or an administrator can change the subscription.</p></section>;
  if (error && !data) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const { subscription } = data;
  const current = data.plans.find((plan) => plan.code === subscription.plan);
  const mpesa = data.payment_methods.includes("MPESA");

  const choose = async (plan) => {
    if (!mpesa) { await showError("Payments are not available yet", "M-Pesa payments are not set up on this platform yet. Contact the platform team to activate your subscription."); return; }
    if (!phone.trim()) { await showError("Enter your M-Pesa number", "Type the Safaricom number that will receive the payment prompt."); return; }
    const renewing = plan.code === subscription.plan;
    // Switching plan says which tools go off (kept, back on with Pro) or come back, so nothing changes unexpectedly.
    const names = { ...current?.feature_names, ...plan.feature_names };
    const label = (codes) => codes.map((code) => names[code] || code).join(", ");
    const goingOff = !renewing && current ? label(current.enabled_modules.filter((code) => !plan.enabled_modules.includes(code))) : "";
    const comingBack = !renewing && current ? label(plan.enabled_modules.filter((code) => !current.enabled_modules.includes(code))) : "";
    const change = goingOff ? ` On ${plan.name}, these switch off until you are back on ${current.name}; nothing recorded in them is deleted: ${goingOff}.`
      : comingBack ? ` ${plan.name} adds: ${comingBack}. Turn on the ones you want in Settings.` : "";
    const confirmed = await confirmAction({
      title: `${renewing ? "Renew" : "Switch to"} ${plan.name} for ${money(plan.currency, plan.price)}?`,
      text: `An M-Pesa prompt will be sent to ${phone}. Enter your M-Pesa PIN on the phone to pay for ${plan.period_days} days.${change}`,
      confirmButtonText: `Send M-Pesa prompt`, icon: "question",
    });
    if (!confirmed) return;
    setBusy(true);
    try {
      const payment = await api("/api/v1/tenancy/billing/pay/", { method: "POST", body: JSON.stringify({ plan: plan.code, phone, method: "MPESA" }) });
      void Swal.fire({ title: "Check your phone", html: `Enter your M-Pesa PIN to pay <strong>${money(plan.currency, plan.price)}</strong>.<br/>This window updates by itself once the payment is received.`,
        icon: "info", allowOutsideClick: false, showConfirmButton: false, didOpen: () => Swal.showLoading() });
      const result = await waitForPayment(payment.id);
      Swal.close();
      if (result?.status === "PAID") {
        await refresh();
        await showSuccess(`${plan.name} is active`, `Thank you. Paid ${money(result.currency, result.amount)} (M-Pesa ${result.receipt_number}). Your subscription now runs until ${dateText(result.period_ends_at)}.`);
      } else if (result) {
        await showError("Payment not completed", result.status_detail || "The payment did not go through. You can try again.");
      } else {
        await showError("Still waiting for M-Pesa", "We have not received the payment yet. If money was deducted, it will activate automatically once M-Pesa confirms it.");
      }
    } catch (e) {
      Swal.close();
      await showError("Could not send the M-Pesa prompt", e.message);
    } finally {
      setBusy(false);
      await load();
    }
  };

  return <section className="billingPage">
    <h1>Subscription</h1>
    <SubscriptionStatus subscription={subscription} />
    {subscription.complimentary ? <p className="muted">This business is on a free platform plan with every feature. No payment is ever needed.</p> : <>
      <div className="billingPhone">
        <label>M-Pesa number for the payment prompt
          <span className="billingPhoneInput"><Smartphone size={18} aria-hidden="true" />
            <input type="tel" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="0712 345 678" maxLength={20} />
          </span>
        </label>
        {data.simulated_payments && <p className="billingNote">Development mode: payments are simulated and complete by themselves after a few seconds.</p>}
        {!mpesa && <p className="billingNote">M-Pesa payments are not set up on this platform yet. Contact the platform team to activate your subscription.</p>}
      </div>
      <div className="planGrid">
        {data.plans.map((plan) => {
          const isCurrent = plan.code === subscription.plan;
          return <article key={plan.code} className={`planCard${isCurrent ? " current" : ""}${plan.code === "PRO" ? " pro" : ""}`}>
            <header>
              <h2>{plan.code === "PRO" && <Crown size={18} aria-hidden="true" />} {plan.name}</h2>
              {isCurrent && <span className="planBadge">Your plan</span>}
            </header>
            <p className="planPrice"><strong>{money(plan.currency, plan.price)}</strong> / {plan.period_days} days</p>
            <p className="muted">{plan.description}</p>
            <ul>{plan.features.map((feature) => <li key={feature}><Check size={16} aria-hidden="true" /> {feature}</li>)}</ul>
            <button type="button" disabled={busy} className={isCurrent ? "secondary" : ""} onClick={() => void choose(plan)}>
              {isCurrent ? (subscription.ended ? "Renew" : "Pay for next period") : current && Number(plan.price) > Number(current.price) ? "Upgrade" : "Switch"} · {money(plan.currency, plan.price)}
            </button>
          </article>;
        })}
      </div>
      {subscription.status === "TRIAL" && <p className="muted">Paying during your free month keeps the free days: the paid period starts when the free month ends. Upgrading applies straight away.</p>}
    </>}
    <h2>Payment history</h2>
    {data.payments.length ? <table className="billingPayments">
      <thead><tr><th>Date</th><th>Plan</th><th>Amount</th><th>Status</th><th>M-Pesa receipt</th><th>Paid until</th></tr></thead>
      <tbody>{data.payments.map((payment) => <tr key={payment.id}>
        <td>{dateText(payment.created_at)}</td><td>{payment.plan}</td><td>{money(payment.currency, payment.amount)}</td>
        <td><span className={`paymentStatus ${payment.status.toLowerCase()}`}>{payment.status.toLowerCase()}</span>{payment.status !== "PAID" && payment.status_detail ? <small> {payment.status_detail}</small> : null}</td>
        <td>{payment.receipt_number || "—"}</td><td>{dateText(payment.period_ends_at)}</td>
      </tr>)}</tbody>
    </table> : <p className="muted">No payments yet.</p>}
    <FormError title="Could not refresh the subscription." message={error} />
  </section>;
}
