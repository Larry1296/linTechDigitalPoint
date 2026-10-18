import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { TextBox } from "../../components/forms/TextBox";

const NEW = "__new__";

// The supplier of a delivery, chosen from the suppliers already in the system so the same supplier is not written
// three ways. A supplier never used before is typed once under "A new supplier"; the first ever is simply typed.
export function SupplierPicker({ label = "Supplier", value, onChange }) {
  const [suppliers, setSuppliers] = useState(null);
  const [typing, setTyping] = useState(false);
  useEffect(() => {
    let live = true;
    api("/api/v1/inventory/suppliers/").then((rows) => live && setSuppliers(Array.isArray(rows) ? rows : []))
      .catch(() => live && setSuppliers([]));
    return () => { live = false; };
  }, []);
  // A name typed that is already on the list (whatever its capitals) uses the list's spelling.
  const known = (name) => (suppliers || []).find((s) => s.toLowerCase() === name.trim().toLowerCase());
  if (suppliers && (typing || !suppliers.length)) {
    return <>
      <label>{suppliers.length ? "New supplier name" : label}
        <TextBox maxLength="180" required value={value} autoFocus={typing}
          onChange={(e) => onChange(e.target.value)} onBlur={() => { const match = known(value); if (match) onChange(match); }} /></label>
      {suppliers.length > 0 && <button type="button" className="linkButton" onClick={() => { setTyping(false); onChange(known(value) || ""); }}>
        Choose from the list instead</button>}
    </>;
  }
  // A supplier from an earlier delivery or a saved draft stays shown even before the list arrives.
  const options = value && !known(value) ? [value, ...(suppliers || [])] : suppliers || [];
  return <label>{label}
    <select required value={value} onChange={(e) => {
      if (e.target.value === NEW) { setTyping(true); onChange(""); } else onChange(e.target.value);
    }}>
      <option value="">{suppliers ? "Choose a supplier" : "Loading suppliers…"}</option>
      {options.map((name) => <option key={name} value={name}>{name}</option>)}
      <option value={NEW}>+ A new supplier</option>
    </select>
  </label>;
}
