// How the owner keeps the money of the parts of the business: one drawer with each part's money labelled, or a cash
// drawer for each part. Chosen when the business is set up and changeable in Settings; the money check, "money you
// should hold" and the dashboard all follow it.
export const MONEY_PARTS = [
  { key: "SHOP", module: "pos", name: "Shop" },
  { key: "CYBER", module: "services", name: "Cyber / services" },
  { key: "MPESA", module: "mpesa", name: "M-Pesa agency" },
];

// The parts this business runs, from the tools it chose (the shop when none of them is on).
export function businessParts(organization) {
  const enabled = new Set(organization?.enabled_modules || []);
  const parts = MONEY_PARTS.filter((part) => enabled.has(part.module));
  return parts.length ? parts : MONEY_PARTS.slice(0, 1);
}

export const MONEY_MODES = [
  { id: "ONE_DRAWER", label: "One drawer for everything",
    hint: "All the cash sits together. Every shilling is still labelled with the part that brought it in, and the dashboard shows how each part is doing." },
  { id: "SEPARATE_CASH", label: "A separate cash drawer for each part",
    hint: "Each part keeps and counts its own cash. The Lipa na M-Pesa till and the bank stay shared, with each part's share shown. The dashboard adds them all up." },
];

export function MoneyModeChoice({ parts, value, onChange, className = "" }) {
  return <fieldset className={`choiceGroup ${className}`.trim()}>
    <legend>How do you keep the money of {parts.map((part) => part.name).join(", ").replace(/, ([^,]*)$/, " and $1")}?</legend>
    <div className="choiceGrid wideChoices">
      {MONEY_MODES.map((mode) => <button type="button" key={mode.id} className={`choiceCard${value === mode.id ? " selected" : ""}`}
        aria-pressed={value === mode.id} onClick={() => onChange(mode.id)}>
        <strong>{mode.label}</strong><span>{mode.hint}</span>
      </button>)}
    </div>
    {parts.some((part) => part.key === "MPESA") && <p className="muted">Either way, the M-Pesa agency's cash and float are the agency's money in
      operation and are never counted as yours. Only the commission it earns is yours, and it counts as the agency's contribution.</p>}
  </fieldset>;
}
