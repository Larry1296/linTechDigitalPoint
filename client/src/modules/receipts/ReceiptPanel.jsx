import { useCallback, useEffect, useState } from "react";
import { MessageCircle, Mail, Link2, Printer } from "lucide-react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { ErrorState, Loading } from "../../components/States";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { ReceiptDocument } from "./ReceiptDocument";
import { whatsappLink, whatsappNumber } from "./whatsapp";

// Staff view of one sale's receipt, with every way of getting it to the customer.
export function ReceiptPanel({ saleId, onClose }) {
  const { user } = useAuth();
  const [data, setData] = useState();
  const [loadError, setLoadError] = useState("");
  const [mode, setMode] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const load = useCallback(() => {
    setLoadError("");
    return api(`/api/v1/commerce/sales/${saleId}/receipt/`).then(setData).catch((e) => setLoadError(e.message));
  }, [saleId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const close = (event) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);
  const shareLink = async () => {
    if (data.link) return data.link;
    const { link } = await api(`/api/v1/commerce/sales/${saleId}/receipt/link/`, { method: "POST" });
    setData((current) => ({ ...current, link }));
    return link;
  };
  const act = async (work, failure) => {
    setBusy(true); setNotice(null);
    try {
      setNotice({ kind: "success", text: await work() });
      setMode(null);
    } catch (e) {
      setNotice({ kind: "error", title: failure, text: e.message });
    } finally {
      setBusy(false);
    }
  };
  const sendWhatsapp = (event) => {
    event.preventDefault();
    const number = whatsappNumber(new FormData(event.currentTarget).get("phone"), user.organization?.country);
    if (number.length < 10) {
      setNotice({ kind: "error", title: "Check the phone number.", text: "Enter the customer's WhatsApp number, e.g. 0712 345 678 or +254 712 345 678." });
      return;
    }
    // Open the window before awaiting so browsers do not block it as a pop-up.
    const whatsapp = window.open("", "_blank");
    void act(async () => {
      const link = await shareLink();
      const url = whatsappLink(number, data.receipt, link);
      if (whatsapp) whatsapp.location.href = url; else window.location.href = url;
      return "WhatsApp opened with the receipt message ready. Press send in WhatsApp.";
    }, "Could not prepare the WhatsApp message.");
  };
  const sendEmail = (event) => {
    event.preventDefault();
    const email = new FormData(event.currentTarget).get("email");
    void act(async () => {
      const result = await api(`/api/v1/commerce/sales/${saleId}/receipt/email/`, { method: "POST", body: JSON.stringify({ email }) });
      setData((current) => ({ ...current, link: result.link }));
      return `Receipt emailed to ${result.sent_to}.`;
    }, "Could not email the receipt.");
  };
  const copyLink = () => act(async () => {
    const link = await shareLink();
    await navigator.clipboard.writeText(link);
    return "Receipt link copied. Paste it into any message.";
  }, "Could not copy the link.");
  const turnOff = () => act(async () => {
    await api(`/api/v1/commerce/sales/${saleId}/receipt/link/`, { method: "DELETE" });
    setData((current) => ({ ...current, link: null }));
    return "Receipt link turned off. Anyone who opens it now sees that it is no longer available.";
  }, "Could not turn off the link.");

  return <div className="shelfOverlay receiptOverlay" role="presentation" onMouseDown={onClose}>
    <div className="shelfPanel receiptPanel" role="dialog" aria-modal="true" aria-label="Customer receipt" onMouseDown={(event) => event.stopPropagation()}>
      <header className="shelfPanelHeader">
        <div>
          <span className="eyebrow">Customer receipt</span>
          <h2>{data ? data.receipt.number : "Loading…"}</h2>
        </div>
        <button type="button" className="shelfClose" onClick={onClose} aria-label="Close receipt">×</button>
      </header>
      {loadError && !data ? <ErrorState message={loadError} retry={load} /> : !data ? <Loading /> : <>
        <div className="receiptActions" role="group" aria-label="Send or print this receipt">
          <button type="button" onClick={() => { setMode("whatsapp"); setNotice(null); }} disabled={busy}><MessageCircle size={18} aria-hidden="true" /> Send on WhatsApp</button>
          <button type="button" className="secondary" onClick={() => { setMode("email"); setNotice(null); }} disabled={busy}><Mail size={18} aria-hidden="true" /> Send by email</button>
          <button type="button" className="secondary" onClick={() => void copyLink()} disabled={busy}><Link2 size={18} aria-hidden="true" /> Copy link</button>
          <button type="button" className="secondary" onClick={() => window.print()} disabled={busy}><Printer size={18} aria-hidden="true" /> Print</button>
        </div>
        {mode === "whatsapp" && <form className="receiptSendForm" onSubmit={sendWhatsapp}>
          <label>Customer's WhatsApp number<input name="phone" type="tel" inputMode="tel" autoComplete="off" required placeholder="0712 345 678" autoFocus /></label>
          <button disabled={busy}>{busy ? "Preparing…" : "Open WhatsApp"}</button>
          <button type="button" className="secondary" onClick={() => setMode(null)}>Cancel</button>
        </form>}
        {mode === "email" && <form className="receiptSendForm" onSubmit={sendEmail}>
          <label>Customer's email<input name="email" type="email" autoComplete="off" required placeholder="customer@example.com" autoFocus /></label>
          <button disabled={busy}>{busy ? "Sending…" : "Send receipt"}</button>
          <button type="button" className="secondary" onClick={() => setMode(null)}>Cancel</button>
        </form>}
        {notice?.kind === "error" && <FormError title={notice.title} message={notice.text} />}
        {notice?.kind === "success" && <FormSuccess message={notice.text} />}
        <ReceiptDocument receipt={data.receipt} />
        {data.link && <p className="receiptLinkNote">
          This receipt has a private link that the customer can open. <button type="button" className="linkButton" onClick={() => void turnOff()} disabled={busy}>Turn off link</button>
        </p>}
      </>}
    </div>
  </div>;
}
