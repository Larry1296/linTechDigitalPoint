import { useState } from "react";
import type { CyberService } from "./types";

export function CyberJobForm({ services, onSave }: { services: CyberService[]; onSave: (data: unknown) => Promise<void> }) {
  const [lines, setLines] = useState([{ variant_id: services[0]?.variant || 0, quantity: 1, service_details: {} }]);
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await onSave({ walk_in_customer_name: form.get("customer"), phone: form.get("phone"), notes: form.get("notes"), discount: form.get("discount"), lines });
  };
  return <form className="saleCart operatorForm" onSubmit={submit}>
    <h2>New job / Quick service</h2>
    <label>Customer name (optional)<input name="customer" /></label>
    <label>Phone (optional)<input name="phone" inputMode="tel" /></label>
    {lines.map((line, index) => <div className="jobLine" key={index}>
      <select aria-label={`Service ${index + 1}`} value={line.variant_id} onChange={(event) => setLines((old) => old.map((item, i) => i === index ? { ...item, variant_id: +event.target.value } : item))}>
        <option value={0}>Choose service</option>{services.filter((service) => service.active).map((service) => <option key={service.id} value={service.variant}>{service.name} · KSh {service.selling_price}/{service.billing_unit.replace("PER_", "").toLowerCase()}</option>)}
      </select>
      <input aria-label={`Billable units ${index + 1}`} type="number" min="0.001" step="0.001" value={line.quantity} onChange={(event) => setLines((old) => old.map((item, i) => i === index ? { ...item, quantity: +event.target.value } : item))} />
      {lines.length > 1 && <button type="button" className="danger" onClick={() => setLines((old) => old.filter((_, i) => i !== index))}>Remove</button>}
    </div>)}
    <button type="button" className="secondary" onClick={() => setLines((old) => [...old, { variant_id: services[0]?.variant || 0, quantity: 1, service_details: {} }])}>Add another service</button>
    <label>Discount<input name="discount" type="number" min="0" defaultValue="0" /></label>
    <label>Operational notes only<textarea name="notes" placeholder="Do not record passwords, PINs, OTPs, or document contents." /></label>
    <button disabled={!services.length || lines.some((line) => !line.variant_id)}>Create job</button>
  </form>;
}
