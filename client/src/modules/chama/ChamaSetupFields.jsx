import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { businessCurrency } from "../../core/organization/presentation";
import "./chama.css";

// The chama set-up, shared by business registration and the dashboard so both look and work the same.
export const FREQUENCIES = [["DAILY", "Every day", "day"], ["WEEKLY", "Every week", "week"], ["MONTHLY", "Every month", "month"]];
export const ROLES = [["CHAIRPERSON", "Chairperson"], ["VICE_CHAIRPERSON", "Vice-chairperson"], ["SECRETARY", "Secretary"],
  ["TREASURER", "Treasurer"], ["ORGANISER", "Organising secretary"], ["MEMBER", "Member"]];
export const roleLabel = (role) => Object.fromEntries(ROLES)[role] || role;
export const periodWord = (frequency) => FREQUENCIES.find(([id]) => id === frequency)?.[2] || "period";
const today = () => new Date().toLocaleDateString("en-CA");
const blankMember = (role = "MEMBER") => ({ full_name: "", id_number: "", phone: "", role });

export function emptyChama(user) {
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.name || "";
  return { name: "", contribution_amount: "", frequency: "WEEKLY", start_date: today(), grace_days: "1", fine_amount: "",
    payout_mode: "ROTATION", periods_per_round: "1", turn_choice: "ORDER", first_receiver: "", notes: "",
    // The person setting it up is usually the treasurer; they can change that.
    members: [{ full_name: name, id_number: "", phone: user?.phone || "", role: "TREASURER" }, blankMember()] };
}

// The same checks the server makes, so a mistake is shown before continuing.
export function chamaProblem(chama) {
  if (!chama.name.trim()) return "Enter the chama's name.";
  if (!(Number(chama.contribution_amount) > 0)) return "Enter how much each member contributes.";
  if (!chama.start_date) return "Choose the date of the first contribution to record.";
  if (chama.frequency === "DAILY" && new Date(`${chama.start_date}T12:00:00`).getDay() === 0)
    return "Sunday is the chama's rest day: a daily chama contributes Monday to Saturday. Start on Monday instead.";
  if (chama.fine_amount !== "" && Number(chama.fine_amount) < 0) return "The fine cannot be below zero. Enter 0 for no fine.";
  if (Number(chama.grace_days) < 0 || Number(chama.grace_days) > 60) return "Allow between 0 and 60 days to pay after the contribution date.";
  const people = chama.members.filter((m) => m.full_name.trim() || m.id_number.trim() || m.phone.trim());
  if (people.length < 2) return "A chama needs at least two members. Add every member, including yourself if you contribute.";
  for (const [index, m] of people.entries()) {
    const who = m.full_name.trim() || `Member ${index + 1}`;
    if (m.full_name.trim().split(/\s+/).length < 2) return `Enter ${who}'s full name, at least two names.`;
    if (!/^[A-Za-z0-9]{4,20}$/.test(m.id_number.replace(/[\s-]/g, ""))) return `Enter ${who}'s ID number.`;
    if (!/^\+?\d{9,15}$/.test(m.phone.replace(/[\s()-]/g, ""))) return `Enter ${who}'s phone number, such as 0712 345 678.`;
  }
  const ids = people.map((m) => m.id_number.replace(/[\s-]/g, "").toUpperCase());
  if (new Set(ids).size !== ids.length) return "Two members have the same ID number.";
  const treasurers = people.filter((m) => m.role === "TREASURER").length;
  if (treasurers !== 1) return treasurers ? "Only one member can be the treasurer." : "Choose the chama's treasurer.";
  for (const [role, label] of ROLES.filter(([role]) => !["MEMBER", "TREASURER"].includes(role))) {
    if (people.filter((m) => m.role === role).length > 1) return `Only one member can be ${label.toLowerCase()}.`;
  }
  return "";
}

const filled = (m) => Boolean(m.full_name.trim() || m.id_number.trim() || m.phone.trim());

// What the server receives: blank member rows are left out, and the first receiver is counted among the rest.
export function chamaPayload(chama) {
  const chosen = chama.first_receiver === "" || chama.first_receiver == null ? null : Number(chama.first_receiver);
  const agreed = chama.payout_mode === "ROTATION" && chama.turn_choice === "AGREED" && chosen != null && filled(chama.members[chosen] || { full_name: "", id_number: "", phone: "" });
  return { ...chama, grace_days: Number(chama.grace_days || 0), fine_amount: chama.fine_amount || 0, periods_per_round: Number(chama.periods_per_round || 1),
    turn_choice: chama.turn_choice || "ORDER", members: chama.members.filter(filled),
    first_receiver: agreed ? chama.members.slice(0, chosen).filter(filled).length : null };
}

export function ChamaSetupFields({ value, onChange }) {
  const set = (field) => (event) => {
    const next = { ...value, [field]: event.target.value };
    // A daily chama rests on Sunday: a Sunday start moves to the Monday after.
    const start = next.start_date && new Date(`${next.start_date}T12:00:00`);
    if (next.frequency === "DAILY" && start?.getDay() === 0) next.start_date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1, 12).toLocaleDateString("en-CA");
    onChange(next);
  };
  const setMember = (index, changes) => {
    // Giving someone an office takes it from whoever had it, as in the chama itself.
    const members = value.members.map((member, i) => {
      if (i === index) return { ...member, ...changes };
      if (changes.role && changes.role !== "MEMBER" && member.role === changes.role) return { ...member, role: "MEMBER" };
      return member;
    });
    onChange({ ...value, members });
  };
  // The chosen first receiver follows their row when rows move or are removed.
  const chosen = value.first_receiver === "" || value.first_receiver == null ? null : Number(value.first_receiver);
  const move = (index, step) => {
    const members = [...value.members];
    [members[index], members[index + step]] = [members[index + step], members[index]];
    const first = chosen === index ? index + step : chosen === index + step ? index : chosen;
    onChange({ ...value, members, first_receiver: first ?? "" });
  };
  const remove = (index) => onChange({ ...value, members: value.members.filter((_, i) => i !== index),
    first_receiver: chosen == null || chosen === index ? "" : chosen > index ? chosen - 1 : chosen });
  const word = periodWord(value.frequency);
  const currency = businessCurrency();
  const rotation = value.payout_mode === "ROTATION";
  const agreed = rotation && value.turn_choice === "AGREED";
  const count = value.members.filter((m) => m.full_name.trim()).length;
  const pot = Number(value.contribution_amount || 0) * count * Number(value.periods_per_round || 1);
  return <div className="chamaSetup">
    <p className="chamaApart">The chama's money belongs to its members. It is kept completely apart from your shop: it never appears in your sales, profit, cash or reports.</p>
    <fieldset className="choiceGroup">
      <legend>The chama</legend>
      <div className="setupGrid">
        <label className="wide">Chama name<input value={value.name} onChange={set("name")} maxLength={120} placeholder="e.g. Umoja Women Group" /></label>
        <label>Each member contributes ({currency})<input type="number" min="1" step="0.01" inputMode="decimal" value={value.contribution_amount} onChange={set("contribution_amount")} placeholder="e.g. 500" /></label>
        <label>How often<select value={value.frequency} onChange={set("frequency")}>
          {FREQUENCIES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select></label>
        <label>First contribution to record<input type="date" value={value.start_date} onChange={set("start_date")} /></label>
        <label>Days allowed to pay after it<input type="number" min="0" max="60" step="1" value={value.grace_days} onChange={set("grace_days")} /></label>
        <label>Fine for paying late ({currency})<input type="number" min="0" step="0.01" inputMode="decimal" value={value.fine_amount} onChange={set("fine_amount")} placeholder="0 for no fine" /></label>
      </div>
      <p className="muted">Members contribute {value.frequency === "DAILY" ? "every day from Monday to Saturday (Sunday is a rest day)" : `every ${word}`} from {value.start_date || "the first date"}
        {value.frequency === "MONTHLY" && value.start_date ? `, on day ${Number(value.start_date.slice(8, 10))} of each month` : ""}.
        {Number(value.fine_amount) > 0 ? ` Anyone who has not paid in full ${Number(value.grace_days) ? `${value.grace_days} day${Number(value.grace_days) === 1 ? "" : "s"} after` : "by the end of"} the contribution day is fined ${currency} ${Number(value.fine_amount).toLocaleString()}, unless they gave an excuse and pay by the date they promised.` : " Nobody is fined for paying late."}
        {" "}If your chama has been running for a while, start from the current or next contribution.</p>
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
      {rotation && <label className="chamaRound">Contributions in each turn<input type="number" min="1" max="60" step="1" value={value.periods_per_round} onChange={set("periods_per_round")} />
        <small className="muted">1 means a member receives every {word}.{value.frequency === "DAILY" ? " 6 means everyone gives Monday to Saturday, one member receives, and the next member's turn starts on Monday." : ""}{pot > 0 ? ` Each turn's money: about ${currency} ${pot.toLocaleString()}.` : ""}</small></label>}
      {rotation && <div className="choiceGrid wideChoices chamaTurnChoice" role="group" aria-label="Who receives next">
        <button type="button" className={`choiceCard${!agreed ? " selected" : ""}`} aria-pressed={!agreed} onClick={() => onChange({ ...value, turn_choice: "ORDER" })}>
          <strong>In the order listed</strong><span>Turns follow the member list below. The members can still agree to let someone go next.</span>
        </button>
        <button type="button" className={`choiceCard${agreed ? " selected" : ""}`} aria-pressed={agreed} onClick={() => onChange({ ...value, turn_choice: "AGREED" })}>
          <strong>Members agree who receives next</strong><span>After each turn, the members agree the next member to receive, and the treasurer records it.</span>
        </button>
      </div>}
      {agreed && <label className="chamaRound">Who receives the first turn<select value={chosen ?? ""} onChange={set("first_receiver")}>
        <option value="">Not agreed yet</option>
        {value.members.map((member, index) => filled(member) && <option key={index} value={index}>{member.full_name || `Member ${index + 1}`}</option>)}
      </select><small className="muted">Each member receives once before anyone receives again.</small></label>}
    </fieldset>
    <fieldset className="choiceGroup">
      <legend>Leaders and members <small>{rotation && !agreed ? "List them in the order they receive the money, starting with whoever receives next." : "Every member, including the leaders."}</small></legend>
      <ol className="chamaMemberRows">
        {value.members.map((member, index) => <li key={index} className="chamaMemberRow">
          <span className="chamaTurn" aria-hidden="true">{index + 1}</span>
          <label><span>Full name</span><input value={member.full_name} onChange={(e) => setMember(index, { full_name: e.target.value })} maxLength={120} placeholder="e.g. Mary Wanjiku Achieng" autoComplete="off" /></label>
          <label><span>ID number</span><input value={member.id_number} onChange={(e) => setMember(index, { id_number: e.target.value })} maxLength={20} placeholder="e.g. 12345678" autoComplete="off" /></label>
          <label><span>Phone</span><input type="tel" value={member.phone} onChange={(e) => setMember(index, { phone: e.target.value })} maxLength={20} placeholder="0712 345 678" autoComplete="off" /></label>
          <label><span>Role</span><select value={member.role} onChange={(e) => setMember(index, { role: e.target.value })}>
            {ROLES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select></label>
          <div className="chamaRowTools">
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
