import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { CheckoutPanel } from "../pos/CheckoutPanel";
import { useMpesaExpress } from "../pos/MpesaPrompt";
import "../admin/pos.css";
import "../pos/posPage.css";

// The desk's own checkout still waiting for payment (``which`` picks visits or a job's), so a reloaded page picks it up.
export function useOpenCyberCheckout(user, which) {
  const [checkout, setCheckout] = useState(null);
  useEffect(() => {
    api("/api/v1/commerce/pos/checkouts/?kind=cyber").then((data) => {
      const mine = (data?.checkouts || []).find((row) => row.cashier_id === user?.id && which(row));
      if (mine) setCheckout(mine);
    }).catch(() => {});
  }, []);
  return [checkout, setCheckout];
}

// Cyber services paid exactly as at the till: cash, the till, a prompt, bank, or owed by a named customer, or a mix.
export function CyberPay({ checkout, customers, onChange, onDone, onBack }) {
  const express = useMpesaExpress();
  const customerPhone = customers.find((c) => String(c.id) === String(checkout.customer_id))?.phone;
  return <CheckoutPanel checkout={checkout} express={express} customerPhone={customerPhone} onChange={onChange} onDone={onDone} onBack={onBack} />;
}
