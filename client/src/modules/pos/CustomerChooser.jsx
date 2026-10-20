import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { FormError } from "../../components/forms/FormNotice";
import { TextBox } from "../../components/forms/TextBox";

// The business's customers, for those allowed to see them.
export function useCustomers(user) {
  const [customers, setCustomers] = useState([]);
  useEffect(() => {
    if (user?.permissions?.includes("accounts.view_customerprofile")) api("/api/v1/commerce/customers/").then(setCustomers).catch(() => {});
  }, []);
  return [customers, setCustomers];
}

// Who is paying: a walk-in customer, or a named one who can then owe part of it. Shared by the till and the Cyber desk.
export function CustomerChooser({ user, customers, setCustomers, value, onChange, open }) {
  const canAddCustomer = user?.permissions?.includes("accounts.add_customerprofile");
  const [newCustomer, setNewCustomer] = useState(null);
  const [customerError, setCustomerError] = useState("");
  // Someone who pays later must be named, so the balance is owed by a real customer.
  const addCustomer = async () => {
    setCustomerError("");
    try {
      const created = await api("/api/v1/commerce/customers/", { method: "POST", body: JSON.stringify({ name: newCustomer.name.trim(), phone: newCustomer.phone.trim() }) });
      setCustomers((list) => [created, ...list]);
      onChange(String(created.id));
      setNewCustomer(null);
    } catch (e) {
      setCustomerError(e.message);
    }
  };
  return <details className="posCustomer" open={open || Boolean(value) || undefined}>
    <summary>Customer{value ? `: ${customers.find((c) => String(c.id) === value)?.name || ""}` : " (optional)"}</summary>
    <p className="muted">Walk-in customers need nothing. Choose a customer to put the sale on their record, or to let them owe part of it.</p>
    <label>Customer<select name="customer_id" value={value} onChange={(e) => onChange(e.target.value)}><option value="">Walk-in customer</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name} {c.phone}</option>)}</select></label>
    {canAddCustomer && (newCustomer ? <div className="inlineCreate" role="group" aria-label="New customer">
      <label>Customer name<TextBox value={newCustomer.name} maxLength={150} onChange={(e) => setNewCustomer({ ...newCustomer, name: e.target.value })} /></label>
      <label>Phone<TextBox value={newCustomer.phone} maxLength={30} inputMode="tel" onChange={(e) => setNewCustomer({ ...newCustomer, phone: e.target.value })} /></label>
      <button type="button" disabled={!newCustomer.name.trim()} onClick={() => void addCustomer()}>Save customer</button>
      <button type="button" className="secondary" onClick={() => { setNewCustomer(null); setCustomerError(""); }}>Cancel</button>
      <FormError title="Could not add the customer." message={customerError} />
    </div> : <button type="button" className="secondary" onClick={() => setNewCustomer({ name: "", phone: "" })}>+ New customer</button>)}
  </details>;
}
