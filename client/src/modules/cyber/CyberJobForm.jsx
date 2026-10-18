import { businessCurrency } from "../../core/organization/presentation";
import { FormField } from "../../components/forms/FormField";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { useState } from "react";
import { TextArea } from "../../components/forms/TextBox";
const emptyLine = () => ({ variant_id: 0, quantity: 1, service_details: {} });
// After a job is created the form clears and shows which job was made, so the same job is not created twice:
// the button stays off until a service is chosen for the next job.
export function CyberJobForm({ services, onSave }) {
  const [lines, setLines] = useState([emptyLine()]);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState("");
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    const element = event.currentTarget;
    const form = new FormData(element);
    setBusy(true);
    setError("");
    setCreated("");
    try {
      const job = await onSave({
        walk_in_customer_name: form.get("customer"),
        phone: form.get("phone"),
        notes: form.get("notes"),
        discount: form.get("discount"),
        lines,
      });
      const who = form.get("customer")?.trim();
      setCreated(`Job ${job.number} created${who ? ` for ${who}` : ""}. It is waiting under Jobs.`);
      element.reset();
      setLines([emptyLine()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="saleCart operatorForm" onSubmit={submit} aria-label="New job" aria-busy={busy}>
      <h2>Take in a job for later</h2>
      <p className="muted">For work you will do after the customer leaves (e.g. typing, design, applications). It waits under
        Jobs; they pay with Pay &amp; complete when it is done. Nothing is paid or counted yet.</p>
      {created && <FormSuccess message={created} />}
      <FormField label="Customer name (optional)" name="customer" />
      <FormField label="Phone (optional)" name="phone" inputMode="tel" />
      {lines.map((line, index) => (
        <div className="jobLine" key={index}>
          <select
            aria-label={`Service ${index + 1}`}
            value={line.variant_id}
            onChange={(event) =>
              setLines((old) =>
                old.map((item, i) =>
                  i === index
                    ? { ...item, variant_id: +event.target.value }
                    : item,
                ),
              )
            }
          >
            <option value={0}>Choose service</option>
            {services
              .filter((service) => service.active)
              .map((service) => (
                <option key={service.id} value={service.variant}>
                  {service.name}{service.variant_name && service.variant_name !== "Standard" ? ` — ${service.variant_name}` : ""} · {businessCurrency()} {service.selling_price}/
                  {service.billing_unit.replace("PER_", "").toLowerCase()}
                </option>
              ))}
          </select>
          <input
            aria-label={`How many ${index + 1}`}
            type="number"
            min="0.001"
            step="0.001"
            value={line.quantity}
            onChange={(event) =>
              setLines((old) =>
                old.map((item, i) =>
                  i === index
                    ? { ...item, quantity: +event.target.value }
                    : item,
                ),
              )
            }
          />
          {lines.length > 1 && (
            <button
              type="button"
              className="danger"
              onClick={() =>
                setLines((old) => old.filter((_, i) => i !== index))
              }
            >
              Remove
            </button>
          )}
        </div>
      ))}
      <button
        type="button"
        className="secondary"
        onClick={() =>
          setLines((old) => [
            ...old,
            emptyLine(),
          ])
        }
      >
        + Another item for this job
      </button>
      <FormField
        label="Discount"
        name="discount"
        type="number"
        min="0"
        defaultValue="0"
      />
      <label>
        Operational notes only
        <TextArea
          name="notes"
          placeholder="Do not record passwords, PINs, OTPs, or document contents."
        />
      </label>
      <button
        disabled={busy || !services.length || lines.some((line) => !line.variant_id)}
      >
        {busy ? "Saving job…" : "Save job for later"}
      </button>
      <FormError title="Could not create the job." message={error} />
    </form>
  );
}
