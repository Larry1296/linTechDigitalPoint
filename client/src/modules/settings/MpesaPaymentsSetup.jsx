import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, Smartphone } from "lucide-react";
import { api } from "../../core/api/client";
import { FormError } from "../../components/forms/FormNotice";
import { PromptStatus, usePrompt } from "../pos/MpesaPrompt";
import "./mpesaSetup.css";

const KINDS = [
  { id: "TILL", name: "Till number", text: "Buy Goods: customers pay to a till number." },
  { id: "PAYBILL", name: "Paybill", text: "Customers pay to a paybill and account." },
  { id: "NONE", name: "Neither", text: "No Safaricom till or paybill: record M-Pesa by hand with the code." },
];
const blank = { kind: "NONE", shortcode: "", till_number: "", account_reference: "", environment: "PRODUCTION", consumer_key: "", consumer_secret: "", passkey: "" };

/**
 * A business's own M-Pesa till or paybill, so the point of sale can send customers a payment prompt. The owner lists
 * what Safaricom gave them; the platform does the rest (the callback address, checking the keys, the test prompt).
 * Without a till or paybill, M-Pesa is recorded by hand.
 */
export function MpesaPaymentsSetup({ intro = true }) {
  const [setup, setSetup] = useState(null);
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [testPhone, setTestPhone] = useState("");
  const [testing, setTesting] = useState(null);
  const [testError, setTestError] = useState("");
  const load = (data) => {
    setSetup(data);
    setForm({ ...blank, kind: data.kind, shortcode: data.shortcode || "", till_number: data.till_number || "",
      account_reference: data.account_reference || "", environment: data.environment || "PRODUCTION" });
  };
  useEffect(() => { api("/api/v1/commerce/mpesa-express/").then(load).catch((e) => setError(e.message)); }, []);
  const test = usePrompt(testing, () => api("/api/v1/commerce/mpesa-express/").then(load).catch(() => {}));
  if (!setup) return error ? <FormError title="Could not load the M-Pesa payment settings." message={error} /> : <p className="muted">Loading…</p>;
  const set = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));
  const till = form.kind === "TILL";
  const save = async (event) => {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      load(await api("/api/v1/commerce/mpesa-express/", { method: "PUT", body: JSON.stringify(form) }));
    } catch (e) {
      setError(e.message);
    } finally { setBusy(false); }
  };
  const sendTest = async (event) => {
    event.preventDefault();
    setTestError("");
    try {
      setTesting(await api("/api/v1/commerce/mpesa-express/test/", { method: "POST", body: JSON.stringify({ phone: testPhone }) }));
    } catch (e) { setTestError(e.message); }
  };
  const saved = setup.kind !== "NONE";
  const savedNumber = setup.kind === "TILL" ? `Till ${setup.till_number}` : `Paybill ${setup.shortcode}`;

  return <div className="mpesaSetup">
    {intro && <p className="muted">Send customers an M-Pesa prompt from the point of sale: they enter their PIN on their own phone, the
      money goes straight to your till or paybill, and the sale is marked paid by itself.</p>}
    {setup.ready ? <p className="mpesaSetupState on" role="status"><CheckCircle2 size={18} aria-hidden="true" />
      <span><b>Prompts are on</b> · {savedNumber}{setup.environment === "SANDBOX" ? " (testing)" : ""}{setup.tested_at ? " · test prompt paid" : ""}</span></p>
      : saved ? <p className="mpesaSetupState" role="status"><CircleAlert size={18} aria-hidden="true" />
        <span><b>Not working yet.</b> {setup.status_detail || "Check the details below and save again."}</span></p>
      : <p className="mpesaSetupState none" role="status"><Smartphone size={18} aria-hidden="true" /><span><b>Manual M-Pesa only.</b> Payments are confirmed with the code from the customer's message.</span></p>}
    {setup.ready && setup.status_detail && <p className="muted">{setup.status_detail}</p>}
    {saved && !setup.callback_ready && <p className="formNotice" role="status">The platform's public web address is not set yet, so Safaricom
      cannot report payments back. Ask the platform team to set it (MPESA_CALLBACK_BASE_URL).</p>}

    {!setup.can_change ? <p className="muted">Only the business owner can change where M-Pesa payments go.</p> : <form onSubmit={save} className="mpesaSetupForm">
      <fieldset className="mpesaKinds">
        <legend>Does the business have a Safaricom till or paybill?</legend>
        {KINDS.map((kind) => <label key={kind.id} className={form.kind === kind.id ? "on" : ""}>
          <input type="radio" name="kind" value={kind.id} checked={form.kind === kind.id} onChange={set("kind")} />
          <b>{kind.name}</b><small>{kind.text}</small>
        </label>)}
      </fieldset>

      {form.kind !== "NONE" && <>
        <section className="mpesaNeeds" aria-labelledby="mpesa-needs">
          <h3 id="mpesa-needs">What you need from Safaricom</h3>
          <ol>{setup.requirements.map((item) => <li key={item.id}><b>{item.label}</b><span>{item.help}</span></li>)}</ol>
          <p className="muted">The rest is done for you: the address Safaricom reports payments to, checking your keys, and matching each payment to its sale.</p>
        </section>
        <div className="mpesaFields">
          {till ? <>
            <label>Till number<input value={form.till_number} onChange={set("till_number")} inputMode="numeric" required maxLength={10} placeholder="e.g. 9876543" /></label>
            <label>Store number (head office number)<input value={form.shortcode} onChange={set("shortcode")} inputMode="numeric" required maxLength={10} placeholder="On your till registration letter" /></label>
          </> : <>
            <label>Paybill number<input value={form.shortcode} onChange={set("shortcode")} inputMode="numeric" required maxLength={10} placeholder="e.g. 522522" /></label>
            <label>Account number customers pay to (optional)<input value={form.account_reference} onChange={set("account_reference")} maxLength={12} placeholder="Blank: the sale number" /></label>
          </>}
          <label>Consumer Key<input value={form.consumer_key} onChange={set("consumer_key")} autoComplete="off" spellCheck={false}
            required={!setup.consumer_key_hint} placeholder={setup.consumer_key_hint ? `Saved (${setup.consumer_key_hint}). Leave blank to keep` : "From your Daraja app"} /></label>
          <label>Consumer Secret<input type="password" value={form.consumer_secret} onChange={set("consumer_secret")} autoComplete="new-password"
            required={!setup.has_consumer_secret} placeholder={setup.has_consumer_secret ? "Saved. Leave blank to keep" : "From your Daraja app"} /></label>
          <label>Lipa na M-Pesa Online passkey<input type="password" value={form.passkey} onChange={set("passkey")} autoComplete="new-password"
            required={!setup.has_passkey} placeholder={setup.has_passkey ? "Saved. Leave blank to keep" : "Emailed by Safaricom after Go Live"} /></label>
          <label>Mode<select value={form.environment} onChange={set("environment")}>
            <option value="PRODUCTION">Live (real money)</option>
            <option value="SANDBOX">Testing (Safaricom sandbox)</option>
          </select></label>
        </div>
      </>}
      <button disabled={busy}>{busy ? "Checking with Safaricom…" : form.kind === "NONE" ? "Save: manual payments only" : "Save and check with Safaricom"}</button>
      <FormError title="Could not save the M-Pesa settings." message={error} />
    </form>}

    {setup.can_change && setup.ready && <form className="sendPrompt" onSubmit={sendTest}>
      <label>Send a KES 1 test prompt to your phone<input value={testPhone} onChange={(e) => setTestPhone(e.target.value)} inputMode="tel" required placeholder="0712 345 678" /></label>
      <button className="secondary" disabled={test?.status === "PENDING"}>Send test prompt</button>
      {testError && <p className="formNotice error" role="alert">{testError}</p>}
    </form>}
    <PromptStatus prompt={test} />
  </div>;
}
