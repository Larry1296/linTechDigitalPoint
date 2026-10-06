import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { businessCurrency } from "../../core/organization/presentation";
import "./kyama.css";

// The kyama set-up, shared by business registration and the dashboard so both look and work the same.
export const FREQUENCIES = [["DAILY", "Every day", "day"], ["WEEKLY", "Every week", "week"], ["MONTHLY", "Every month", "month"]];
export const ROLES = [["CHAIRPERSON", "Chairperson"], ["VICE_CHAIRPERSON", "Vice-chairperson"], ["SECRETARY", "Secretary"],
  ["TREASURER", "Treasurer"], ["ORGANISER", "Organising secretary"], ["MEMBER", "Member"]];
export const roleLabel = (role) => Object.fromEntries(ROLES)[role] || role;
export const periodWord = (frequency) => FREQUENCIES.find(([id]) => id === frequency)?.[2] || "period";
const today = () => new Date().toLocaleDateString("en-CA");
const blankMember = (role = "MEMBER") => ({ full_name: "", id_number: "", phone: "", role });

export function emptyKyama(user) {
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.name || "";
  return { name: "", contribution_amount: "", frequency: "WEEKLY", start_date: today(), grace_days: "1", fine_amount: "",
    payout_mode: "ROTATION", periods_per_round: "1", notes: "",
    // The person setting it up is usually the treasurer; they can change that.
    members: [{ full_name: name, id_number: "", phone: user?.phone || "", role: "TREASURER" }, blankMember()] };
}

// The same checks the server makes, so a mistake is shown before continuing.
export function kyamaProblem(kyama) {
  if (!kyama.name.trim()) return "Enter the kyama's name.";
  if (!(Number(kyama.contribution_amount) > 0)) return "Enter how much each member contributes.";
  if (!kyama.start_date) return "Choose the date of the first contribution to record.";
  if (kyama.fine_amount !== "" && Number(kyama.fine_amount) < 0) return "The fine cannot be below zero. Enter 0 for no fine.";
  if (Number(kyama.grace_days) < 0 || Number(kyama.grace_days) > 60) return "Allow between 0 and 60 days to pay after the contribution date.";
  const people = kyama.members.filter((m) => m.full_name.trim() || m.id_number.trim() || m.phone.trim());
  if (people.length < 2) return "A kyama needs at least two members. Add every member, including yourself if you contribute.";
  for (const [index, m] of people.entries()) {
    const who = m.full_name.trim() || `Member ${index + 1}`;
    if (m.full_name.trim().split(/\s+/).length < 2) return `Enter ${who}'s full name, at least two names.`;
    if (!/^[A-Za-z0-9]{4,20}$/.test(m.id_number.replace(/[\s-]/g, ""))) return `Enter ${who}'s ID number.`;
    if (!/^\+?\d{9,15}$/.test(m.phone.replace(/[\s()-]/g, ""))) return `Enter ${who}'s phone number, such as 0712 345 678.`;
  }
  const ids = people.map((m) => m.id_number.replace(/[\s-]/g, "").toUpperCase());
  if (new Set(ids).size !== ids.length) return "Two members have the same ID number.";
  const treasurers = people.filter((m) => m.role === "TREASURER").length;
  if (treasurers !== 1) return treasurers ? "Only one member can be the treasurer." : "Choose the kyama's treasurer.";
  for (const [role, label] of ROLES.filter(([role]) => !["MEMBER", "TREASURER"].includes(role))) {
    if (people.filter((m) => m.role === role).length > 1) return `Only one member can be ${label.toLowerCase()}.`;
  }
  return "";
}

// What the server receives: blank member rows are left out.
export const kyamaPayload = (kyama) => ({
  ...kyama, grace_days: Number(kyama.grace_days || 0), fine_amount: kyama.fine_amount || 0, periods_per_round: Number(kyama.periods_per_round || 1),
  members: kyama.members.filter((m) => m.full_name.trim() || m.id_number.trim() || m.phone.trim()),
});

export function KyamaSetupFields({ value, onChange }) {
  const set = (field) => (event) => onChange({ ...value, [field]: event.target.value });
  const setMember = (index, changes) => {
    // Giving someone an office takes it from whoever had it, as in the kyama itself.
    const members = value.members.map((member, i) => {
      if (i === index) return { ...member, ...changes };
      if (changes.role && changes.role !== "MEMBER" && member.role === changes.role) return { ...member, role: "MEMBER" };
      return member;
    });
    onChange({ ...value, members });
  };
  const move = (index, step) => {
    const members = [...value.members];
    [members[index], members[index + step]] = [members[index + step], members[index]];
    onChange({ ...value, members });
  };
  const remove = (index) => onChange({ ...value, members: value.members.filter((_, i) => i !== index) });
  const word = periodWord(value.frequency);
  const currency = businessCurrency();
  const rotation = value.payout_mode === "ROTATION";
  const count = value.members.filter((m) => m.full_name.trim()).length;
  const pot = Number(value.contribution_amount || 0) * count * Number(value.periods_per_round || 1);
  return <div className="kyamaSetup">
    <p className="kyamaApart">The kyama's money belongs to its members. It is kept completely apart from your shop: it never appears in your sales, profit, cash or reports.</p>
    <fieldset className="choiceGroup">
      <legend>The kyama</legend>
      <div className="setupGrid">
        <label className="wide">Kyama name<input value={value.name} onChange={set("name")} maxLength={120} placeholder="e.g. Umoja Women Group" /></label>
        <label>Each member contributes ({currency})<input type="number" min="1" step="0.01" inputMode="decimal" value={value.contribution_amount} onChange={set("contribution_amount")} placeholder="e.g. 500" /></label>
        <label>How often<select value={value.frequency} onChange={set("frequency")}>
          {FREQUENCIES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select></label>
        <label>First contribution to record<input type="date" value={value.start_date} onChange={set("start_date")} /></label>
        <label>Days allowed to pay after it<input type="number" min="0" max="60" step="1" value={value.grace_days} onChange={set("grace_days")} /></label>
        <label>Fine for paying late ({currency})<input type="number" min="0" step="0.01" inputMode="decimal" value={value.fine_amount} onChange={set("fine_amount")} placeholder="0 for no fine" /></label>
      </div>
      <p className="muted">Members contribute {value.frequency === "DAILY" ? "every day" : `every ${word}`} from {value.start_date || "the first date"}
        {value.frequency === "MONTHLY" && value.start_date ? `, on day ${Number(value.start_date.slice(8, 10))} of each month` : ""}.
        {Number(value.fine_amount) > 0 ? ` Anyone who has not paid in full ${Number(value.grace_days) ? `${value.grace_days} day${Number(value.grace_days) === 1 ? "" : "s"} after` : "by the end of"} the contribution day is fined ${currency} ${Number(value.fine_amount).toLocaleString()}, unless they gave an excuse and pay by the date they promised.` : " Nobody is fined for paying late."}
        {" "}If your kyama has been running for a while, start from the current or next contribution.</p>
    </fieldset>
    <fieldset className="choiceGroup">
      <legend>What happens to the money</legend>
      <div className="choiceGrid wideChoices">
        <button type="button" className={`choiceCard${rotation ? " selected" : ""}`} aria-pressed={rotation} onClick={() => onChange({ ...value, payout_mode: "ROTATION" })}>
          <strong>Members take turns</strong><span>Merry-go-round: each turn, one member receives the money collected, in the order listed below.</span>
        </button>
        <button type="button" className={`choiceCard${!rotation ? " selected" : ""}`} aria-pressed={!rotation} onClick={() => onChange({ ...value, payout_mode: "SAVINGS" })}>
          <strong>Save it together</strong><span>The money is kept and shared out or used when the members agree.</span>
        </button>
      </div>
      {rotation && <label className="kyamaRound">Contributions in each turn<input type="number" min="1" max="60" step="1" value={value.periods_per_round} onChange={set("periods_per_round")} />
        <small className="muted">1 means a member receives every {word}.{pot > 0 ? ` Each turn's money: about ${currency} ${pot.toLocaleString()}.` : ""}</small></label>}
    </fieldset>
    <fieldset className="choiceGroup">
      <legend>Leaders and members <small>{rotation ? "List them in the order they receive the money, starting with whoever receives next." : "Every member, including the leaders."}</small></legend>
      <ol className="kyamaMemberRows">
        {value.members.map((member, index) => <li key={index} className="kyamaMemberRow">
          <span className="kyamaTurn" aria-hidden="true">{index + 1}</span>
          <label><span>Full name</span><input value={member.full_name} onChange={(e) => setMember(index, { full_name: e.target.value })} maxLength={120} placeholder="e.g. Mary Wanjiku Achieng" autoComplete="off" /></label>
          <label><span>ID number</span><input value={member.id_number} onChange={(e) => setMember(index, { id_number: e.target.value })} maxLength={20} placeholder="e.g. 12345678" autoComplete="off" /></label>
          <label><span>Phone</span><input type="tel" value={member.phone} onChange={(e) => setMember(index, { phone: e.target.value })} maxLength={20} placeholder="0712 345 678" autoComplete="off" /></label>
          <label><span>Role</span><select value={member.role} onChange={(e) => setMember(index, { role: e.target.value })}>
            {ROLES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select></label>
          <div className="kyamaRowTools">
            <button type="button" className="iconButton" aria-label={`Move ${member.full_name || `member ${index + 1}`} up`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={16} aria-hidden="true" /></button>
            <button type="button" className="iconButton" aria-label={`Move ${member.full_name || `member ${index + 1}`} down`} disabled={index === value.members.length - 1} onClick={() => move(index, 1)}><ArrowDown size={16} aria-hidden="true" /></button>
            <button type="button" className="iconButton" aria-label={`Remove ${member.full_name || `member ${index + 1}`}`} disabled={value.members.length <= 1} onClick={() => remove(index)}><X size={16} aria-hidden="true" /></button>
          </div>
        </li>)}
      </ol>
      <button type="button" className="secondary addRow" onClick={() => onChange({ ...value, members: [...value.members, blankMember()] })}><Plus size={16} aria-hidden="true" /> Add a member</button>
    </fieldset>
  </div>;
}
