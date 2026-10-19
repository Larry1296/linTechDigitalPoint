import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Printer } from "lucide-react";
import { Loading } from "../../components/States";
import { ReceiptDocument } from "./ReceiptDocument";
import { apiUrl } from "../../core/api/client";

// What the customer sees when they open the link from WhatsApp or email. No account needed.
export function PublicReceiptPage() {
  const { token } = useParams();
  const [receipt, setReceipt] = useState();
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(apiUrl(`/api/v1/tenancy/public/receipts/${encodeURIComponent(token)}/`), { credentials: "omit" })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "This receipt could not be loaded.");
        setReceipt(data);
        document.title = `Receipt ${data.number} · ${data.business.name}`;
      })
      .catch((e) => setError(e.message));
  }, [token]);
  return <main className="publicReceipt">
    {error ? <section className="publicReceiptMessage" role="alert">
      <h1>Receipt unavailable</h1>
      <p>{error}</p>
      <p className="muted">Please contact the business that served you for a new link.</p>
    </section> : !receipt ? <Loading /> : <>
      <ReceiptDocument receipt={receipt} />
      <div className="publicReceiptActions">
        <button type="button" onClick={() => window.print()}><Printer size={18} aria-hidden="true" /> Print or save as PDF</button>
      </div>
    </>}
  </main>;
}
