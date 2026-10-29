import { TextBox } from "../../components/forms/TextBox";
// How the owner keeps the money of the parts of the business: one drawer with each part's money labelled, or a cash
// drawer for each part. Chosen when the business is set up and changeable in Settings; the money check, "money you
// should hold" and the dashboard all follow it.
// A hotel's menu runs its shop part (the restaurant and bar), and its rooms its services part.
export const MONEY_PARTS = [
  { key: "SHOP", modules: ["inventory", "menu"], name: "Shop" },
  { key: "CYBER", modules: ["services", "rooms"], name: "Cyber / services" },
  { key: "MPESA", modules: ["mpesa"], name: "M-Pesa agency" },
];

// The parts this business runs, from the tools it chose (the shop when none of them is on), with the owner's own names.
export function businessParts(organization) {
  const enabled = new Set(organization?.enabled_modules || []);
  const named = Object.fromEntries((organization?.parts || []).map((part) => [part.key, part.name]));
  const parts = MONEY_PARTS.filter((part) => part.modules.some((module) => enabled.has(module))).map((part) => ({ ...part, name: named[part.key] || part.name }));
  return parts.length ? parts : MONEY_PARTS.slice(0, 1);
}

// Whether the owner runs this as several businesses under one name, each part's contribution shown.
export function hasParts(organization) {
  return organization?.structure === "PARTS" && businessParts(organization).length > 1;
}

export const STRUCTURES = [
  { id: "PARTS", label: "Several businesses under one name",
    hint: "Like a shop, a cyber and an M-Pesa agency together. See what each part brings in and costs, share costs such as rent between them, and see how each part adds to the whole business's profit." },
  { id: "SINGLE", label: "One business",
    hint: "Like a salon that also sells hair products. Everything is counted together, with no parts." },
];
// A part's usual name, as the server gives it when the owner has not named it.
const HOTEL_SECTORS = ["hotel", "hotel_rooms", "lodging"];
export const defaultPartName = (key, sector = "") => (HOTEL_SECTORS.includes(sector) && key !== "MPESA" ? { SHOP: "Restaurant & bar", CYBER: "Rooms" }[key]
  : key === "CYBER" && sector && !sector.includes("cyber") ? "Services" : { SHOP: "Shop", CYBER: "Cyber", MPESA: "M-Pesa" }[key]);
const ROLES = { SHOP: "Products you sell", CYBER: "Services you offer", MPESA: "M-Pesa agency" };

export const MONEY_MODES = [
  { id: "ONE_DRAWER", label: "One drawer and bank account for everything",
    hint: "All the money sits together. Every shilling is still labelled with the part that brought it in, so you see what each part contributed to the total, and profit is worked out on the whole business." },
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

// Set-up and Settings: is the business one business or several under one name, what is each part called, and how is
// its money kept. Asked only when more than one part of the business takes money.
export function BusinessPartsChoice({ parts, sector, value, onChange, className = "" }) {
  const set = (changes) => onChange({ ...value, ...changes });
  const withParts = value.structure === "PARTS";
  const nameOf = (key) => value.part_names?.[key]?.trim() || defaultPartName(key, sector);
  return <div className={`businessParts ${className}`.trim()}>
    <fieldset className="choiceGroup">
      <legend>Is this one business, or several businesses under one name?</legend>
      <div className="choiceGrid wideChoices">
        {STRUCTURES.map((item) => <button type="button" key={item.id} className={`choiceCard${value.structure === item.id ? " selected" : ""}`}
          aria-pressed={value.structure === item.id} onClick={() => set({ structure: item.id })}>
          <strong>{item.label}</strong><span>{item.hint}</span>
        </button>)}
      </div>
    </fieldset>
    {withParts && <fieldset className="choiceGroup partNames">
      <legend>What do you call each part? <small>These names appear on the dashboard, the money check and expenses.</small></legend>
      {parts.map((part) => <label key={part.key}>{ROLES[part.key]}
        <TextBox value={value.part_names?.[part.key] ?? ""} maxLength={40} placeholder={defaultPartName(part.key, sector)}
          onChange={(event) => set({ part_names: { ...value.part_names, [part.key]: event.target.value } })} />
      </label>)}
    </fieldset>}
    {withParts && <MoneyModeChoice parts={parts.map((part) => ({ ...part, name: nameOf(part.key) }))}
      value={value.money_mode} onChange={(money_mode) => set({ money_mode })} />}
  </div>;
}
