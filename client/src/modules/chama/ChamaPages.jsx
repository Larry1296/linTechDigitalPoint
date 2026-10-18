import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { ArrowDown, ArrowUp } from "lucide-react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { askForm, confirmAction } from "../../core/ui/alerts";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { FREQUENCIES, ChamaSetupFields, ROLES, emptyChama, chamaPayload, chamaProblem, periodWord, roleLabel } from "./ChamaSetupFields";
import "../platform/platform.css";
import "./chama.css";
import { TextArea, TextBox } from "../../components/forms/TextBox";

const METHODS = [["CASH", "Cash"], ["MPESA", "M-Pesa"], ["BANK", "Bank"], ["OTHER", "Other"]];
const methodName = (value) => Object.fromEntries(METHODS)[value] || value;
export const chamaMoney = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const money = chamaMoney;
export const chamaDate = (value) => (value ? new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }) : "—");
const date = chamaDate;
const todayText = () => new Date().toLocaleDateString("en-CA");
const STATUS = { PAID: "Paid", WAITING: "Not paid yet", LATE: "Late", EXCUSED: "Excused", UPCOMING: "Paid ahead" };
const isoDay = (value) => value.toLocaleDateString("en-CA");

// The contribution dates after `from`, worked out the same way as the server.
function nextDates(chama, count) {
  const start = new Date(`${chama.start_date}T12:00:00`);
  const at = (index) => {
    if (chama.frequency === "DAILY") return new Date(start.getFullYear(), start.getMonth(), start.getDate() + index, 12);
    if (chama.frequency === "WEEKLY") return new Date(start.getFullYear(), start.getMonth(), start.getDate() + index * 7, 12);
    const month = new Date(start.getFullYear(), start.getMonth() + index, 1, 12);
    const last = new Date(month.getFullYear(), month.getMonth() + 1, 0, 12).getDate();
    return new Date(month.getFullYear(), month.getMonth(), Math.min(start.getDate(), last), 12);
  };
  const first = chama.current_period || chama.start_date;
  const result = [];
  for (let index = 0; result.length < count && index < 5000; index += 1) {
    const day = isoDay(at(index));
    if (day >= first) result.push(day);
  }
  return result;
}

function useSetupState() {
  const [state, setState] = useState();
  const [error, setError] = useState("");
  const load = async () => {
    try { setState(await api("/api/v1/chama/setup/")); setError(""); } catch (err) { setError(err.message); }
  };
  useEffect(() => { void load(); }, []);
  return { state, error, load };
}

// Chama: the business's chamas, or the set-up when there are none yet.
export function ChamaHomePage() {
  const { state, error, load } = useSetupState();
  const [list, setList] = useState();
  const [listError, setListError] = useState("");
  const loadList = async () => {
    try { setList(await api("/api/v1/chama/")); setListError(""); } catch (err) { setListError(err.message); }
  };
  useEffect(() => { if (state?.enabled && state.chamas > 0) void loadList(); }, [state]);
  useLiveRefresh(() => { if (state?.enabled && state.chamas > 0) void loadList(); });
  if (error) return <ErrorState message={error} retry={load} />;
  if (!state) return <Loading />;
  if (!state.enabled || state.chamas === 0) return <ChamaSetupPage state={state} />;
  if (listError) return <ErrorState message={listError} retry={loadList} />;
  if (!list) return <Loading />;
  if (list.chamas.length === 1) return <Navigate to={`/admin/chama/${list.chamas[0].id}`} replace />;
  return <>
    <h1>Chama</h1>
    <p className="muted chamaApart">Each chama's money belongs to its members and is kept apart from your shop's money and reports.</p>
    <ul className="chamaCards">{list.chamas.map((chama) => <li key={chama.id}><ChamaSummaryCard chama={chama} /></li>)}</ul>
    {state.can_manage && <Link className="button secondary" to="/admin/chama/setup">Set up another chama</Link>}
  </>;
}

export function ChamaSummaryCard({ chama }) {
  const word = periodWord(chama.frequency);
  return <Link className="chamaCard" to={`/admin/chama/${chama.id}`}>
    <strong>{chama.name}</strong>
    <span className="muted">{money(chama.contribution_amount)} {FREQUENCIES.find(([id]) => id === chama.frequency)?.[1].toLowerCase()} · {chama.members} members</span>
    {chama.current_period
      ? <span>This {word}: <b>{chama.paid_count} of {chama.due_count}</b> paid · {money(chama.collected)} of {money(chama.expected)}{chama.late_count > 0 && <b className="loanLate"> · {chama.late_count} late</b>}</span>
      : <span>First contribution on {date(chama.next_period)}</span>}
    <span>The treasurer holds <b>{money(chama.held)}</b></span>
    {chama.next_turn && <span>Next turn: <b>{chama.next_turn.member || "to be agreed by the members"}</b> on {date(chama.next_turn.date)}</span>}
  </Link>;
}

// The same set-up as at registration; saving it also turns chama management on for the business.
export function ChamaSetupPage({ state: given }) {
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const fetched = useSetupState();
  const state = given || fetched.state;
  const [chama, setChama] = useState(() => emptyChama(user));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!given && fetched.error) return <ErrorState message={fetched.error} retry={fetched.load} />;
  if (!state) return <Loading />;
  const intro = <>
    <span className="eyebrow">Chama management · Pro</span>
    <h1>Set up your chama</h1>
    <p className="muted">If you are the treasurer of a chama, LinTech keeps its records for you: every member, who has paid and who has not, fines for paying late, excuses, and whose turn it is to receive the money.</p>
  </>;
  if (!state.plan_allows) return <section className="chamaLocked">{intro}<p>Chama management is part of the Pro plan.</p><Link className="button" to="/admin/subscription">Upgrade to Pro</Link></section>;
  if (!state.enabled && !state.can_turn_on) return <section className="chamaLocked">{intro}<p>Ask the business owner or an administrator to set up the chama.</p></section>;
  if (state.enabled && !state.can_manage) return <section className="chamaLocked">{intro}<p>You don't have permission to set up a chama.</p></section>;
  const save = async (event) => {
    event.preventDefault();
    const problem = chamaProblem(chama);
    if (problem) { setError(problem); return; }
    setBusy(true); setError("");
    try {
      const made = await api("/api/v1/chama/setup/", { method: "POST", body: JSON.stringify(chamaPayload(chama)) });
      await refresh().catch(() => {});  // the menu now shows chama management
      navigate(`/admin/chama/${made.id}`, { replace: true });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return <form className="tenantForm businessSetup chamaSetupPage" onSubmit={(event) => void save(event)}>
    {intro}
    <section className="setupPanel">
      <fieldset disabled={busy} className="chamaPlainFieldset"><ChamaSetupFields value={chama} onChange={setChama} /></fieldset>
    </section>
    <div className="setupActions"><button disabled={busy}>{busy ? "Setting up…" : "Set up the chama"}</button></div>
    <FormError title="Could not set up the chama." message={error} />
  </form>;
}

const TABS = [["board", "This period"], ["members", "Members"], ["turns", "Turns"], ["fines", "Fines & excuses"], ["record", "Money record"], ["rules", "Rules"]];

export function ChamaDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const [chama, setChama] = useState();
  const [error, setError] = useState("");
  const [tab, setTab] = useState("board");
  const load = async () => {
    try { setChama(await api(`/api/v1/chama/${id}/`)); setError(""); } catch (err) { setError(err.message); }
  };
  useEffect(() => { void load(); }, [id]);
  useLiveRefresh(load);
  if (error && !chama) return <ErrorState message={error} retry={load} />;
  if (!chama) return <Loading />;
  const word = periodWord(chama.frequency);
  const tabs = TABS.filter(([key]) => key !== "turns" || chama.payout_mode === "ROTATION")
    .map(([key, label]) => [key, key === "board" ? `This ${word}` : label]);
  const props = { chama, setChama, can, reload: load };
  return <div className="chamaPage">
    <header className="chamaHead">
      <span className="eyebrow">Chama · kept apart from the shop's money</span>
      <h1>{chama.name}</h1>
      <p className="muted">{money(chama.contribution_amount)} {FREQUENCIES.find(([f]) => f === chama.frequency)?.[1].toLowerCase()}
        {Number(chama.fine_amount) > 0 ? ` · fine ${money(chama.fine_amount)} if not paid ${chama.grace_days ? `within ${chama.grace_days} day${chama.grace_days === 1 ? "" : "s"}` : "on the day"}` : " · no fines"}
        {chama.payout_mode === "ROTATION" ? (chama.turn_choice === "AGREED" ? " · members agree who receives next" : " · members take turns") : " · saving together"}
        {" · "}{chama.members.filter((m) => m.active).length} members</p>
    </header>
    <dl className="loanFigures chamaMoney">
      <div><dt>The treasurer holds</dt><dd><strong>{money(chama.money.held)}</strong></dd></div>
      <div><dt>Paid in by members</dt><dd>{money(chama.money.paid_in)}</dd></div>
      <div><dt>Given out</dt><dd>{money(chama.money.given_out)}</dd></div>
      <div><dt>Contributions not paid yet</dt><dd>{money(chama.money.unpaid)}{Number(chama.money.late) > 0 && <small className="loanLate"> · {money(chama.money.late)} late</small>}</dd></div>
      <div><dt>Fines owed</dt><dd>{money(chama.money.fines_owed)}</dd></div>
    </dl>
    <nav className="chamaTabs" aria-label="Chama sections">
      {tabs.map(([key, label]) => <button key={key} type="button" className={tab === key ? "selected" : "secondary"} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}
    </nav>
    {tab === "board" && <Board {...props} />}
    {tab === "members" && <Members {...props} />}
    {tab === "turns" && <Turns {...props} />}
    {tab === "fines" && <Fines {...props} />}
    {tab === "record" && <Record {...props} />}
    {tab === "rules" && <Rules {...props} />}
  </div>;
}

function usePost(setChama) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (path, body, method = "POST") => {
    setBusy(true); setError("");
    try {
      const data = await api(path, { method, body: JSON.stringify(body) });
      setChama(data.chama || data);
      return true;
    } catch (err) {
      setError(err.message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { send, error, busy, setError };
}

function PaymentForm({ chama, member, setChama, onDone }) {
  const owed = Number(member.unpaid) + Number(member.fines_owed);
  const [method, setMethod] = useState("CASH");
  const { send, error, busy } = usePost(setChama);
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!(await confirmAction({ title: `Record ${money(values.amount)} from ${member.full_name}?`,
      text: "It pays their oldest unpaid contributions first, then any fines, then contributions ahead.", confirmButtonText: "Record payment" }))) return;
    if (await send(`/api/v1/chama/${chama.id}/payments/`, { ...values, member: member.id, idempotency_key: crypto.randomUUID() })) onDone();
  };
  return <form className="chamaInlineForm" onSubmit={(event) => void submit(event)} aria-label={`Payment from ${member.full_name}`}>
    <fieldset disabled={busy} className="loanFields">
      <FormField label={`Amount (${businessCurrency()})`} name="amount" type="number" min="0.01" step="0.01" required defaultValue={owed > 0 ? owed : Number(chama.contribution_amount)} />
      <FormField label="Paid on" name="paid_on" type="date" max={todayText()} defaultValue={todayText()} required />
      <FormField label="Paid by"><select name="method" value={method} onChange={(e) => setMethod(e.target.value)}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></FormField>
      <FormField label={method === "MPESA" ? "M-Pesa code" : "Reference (optional)"} name="reference" maxLength={120} required={method === "MPESA"} autoComplete="off" />
    </fieldset>
    <div className="actionRow"><button disabled={busy}>Record payment</button><button type="button" className="secondary" onClick={onDone}>Cancel</button></div>
    <FormError title="Could not record the payment." message={error} />
  </form>;
}

function ExcuseForm({ chama, member, setChama, onDone }) {
  const dates = nextDates(chama, 6);
  const { send, error, busy } = usePost(setChama);
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (await send(`/api/v1/chama/${chama.id}/excuses/`, { ...values, member: member.id })) onDone();
  };
  return <form className="chamaInlineForm" onSubmit={(event) => void submit(event)} aria-label={`Excuse for ${member.full_name}`}>
    <p className="muted">{member.full_name} will pay late. They are not fined if they pay in full by the date they promise.</p>
    <fieldset disabled={busy} className="loanFields">
      <FormField label="Contribution of"><select name="period_date" defaultValue={dates[0]}>{dates.map((d) => <option key={d} value={d}>{date(d)}</option>)}</select></FormField>
      <FormField label="Promises to pay by" name="pay_by" type="date" min={todayText()} required />
      <FormField label="Reason given"><TextBox name="reason" maxLength={500} required placeholder="e.g. waiting for salary on the 10th" /></FormField>
    </fieldset>
    <div className="actionRow"><button disabled={busy}>Accept excuse</button><button type="button" className="secondary" onClick={onDone}>Cancel</button></div>
    <FormError title="Could not record the excuse." message={error} />
  </form>;
}

function DueBadge({ due }) {
  if (!due) return <span className="loanStatus">Not owed</span>;
  const part = due.status !== "PAID" && Number(due.paid) > 0 ? ` · ${money(due.paid)} of ${money(due.amount)}` : "";
  const until = due.status === "EXCUSED" ? ` until ${date(due.excused_until)}` : due.status === "WAITING" ? ` · by ${date(due.pay_by)}` : "";
  return <span className={`loanStatus chama${due.status}`}>{STATUS[due.status]}{until}{part}</span>;
}

function Board({ chama, setChama, can }) {
  const [open, setOpen] = useState(null);  // [memberId, "pay" | "excuse"]
  const word = periodWord(chama.frequency);
  const active = chama.members.filter((m) => m.active || m.this_period);
  if (!chama.current_period) return <Empty>The first contribution is on {date(chama.next_period)}. Members can pay ahead or be excused before then.</Empty>;
  const due = active.filter((m) => m.this_period);
  const paid = due.filter((m) => m.this_period.status === "PAID").length;
  return <section aria-labelledby="board-heading">
    <h2 id="board-heading">Contribution of {date(chama.current_period)}</h2>
    <p className="muted">{paid} of {due.length} members have paid this {word}. The next contribution is on {date(chama.next_period)}.</p>
    {chama.payout_mode === "ROTATION" && chama.turns.find((t) => t.status !== "GIVEN") && (() => {
      const turn = chama.turns.find((t) => t.status !== "GIVEN");
      return <p className="chamaNext">Next to receive: <b>{turn.member || "not agreed yet"}</b>, turn {turn.round} on {date(turn.date)}</p>;
    })()}
    <ul className="chamaBoard">{active.map((member) => <li key={member.id} className={`chamaBoardRow ${member.this_period?.status?.toLowerCase() || ""}`}>
      <div className="chamaWho">
        <strong>{member.full_name}</strong>
        <span className="muted">{member.role !== "MEMBER" ? `${roleLabel(member.role)} · ` : ""}{member.phone}</span>
      </div>
      <DueBadge due={member.this_period} />
      <div className="chamaOwes">
        {Number(member.unpaid) + Number(member.fines_owed) > 0
          ? <>Owes <b>{money(Number(member.unpaid) + Number(member.fines_owed))}</b>{Number(member.fines_owed) > 0 && <small> incl. fines {money(member.fines_owed)}</small>}</>
          : <span className="muted">Owes nothing</span>}
      </div>
      <div className="actionRow">
        {can("chama.add_chamapayment") && <button type="button" onClick={() => setOpen([member.id, "pay"])}>Record payment</button>}
        {can("chama.change_chama") && member.active && <button type="button" className="secondary" onClick={() => setOpen([member.id, "excuse"])}>Excuse</button>}
      </div>
      {open?.[0] === member.id && open[1] === "pay" && <PaymentForm chama={chama} member={member} setChama={setChama} onDone={() => setOpen(null)} />}
      {open?.[0] === member.id && open[1] === "excuse" && <ExcuseForm chama={chama} member={member} setChama={setChama} onDone={() => setOpen(null)} />}
    </li>)}</ul>
  </section>;
}

function MemberForm({ chama, member, setChama, onDone }) {
  const { send, error, busy } = usePost(setChama);
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const ok = member
      ? await send(`/api/v1/chama/${chama.id}/members/${member.id}/`, values, "PATCH")
      : await send(`/api/v1/chama/${chama.id}/members/`, values);
    if (ok) onDone();
  };
  return <form className="formCard chamaInlineForm" onSubmit={(event) => void submit(event)}>
    <h3>{member ? `Change ${member.full_name}'s details` : "Add a member"}</h3>
    <fieldset disabled={busy} className="loanFields">
      <FormField label="Full name" name="full_name" required maxLength={120} defaultValue={member?.full_name} autoComplete="off" />
      <FormField label="ID number" name="id_number" required maxLength={20} defaultValue={member?.id_number} autoComplete="off" />
      <FormField label="Phone" name="phone" type="tel" required maxLength={20} defaultValue={member?.phone} autoComplete="off" />
      <FormField label="Role"><select name="role" defaultValue={member?.role || "MEMBER"}>{ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></FormField>
      {!member && <FormField label="Joined on" name="joined_on" type="date" max={todayText()} min={chama.start_date} defaultValue={todayText()} />}
    </fieldset>
    {!member && <p className="muted">They owe contributions from the day they joined, without fines for days before today. They take the last turn; change the order under Turns.</p>}
    <div className="actionRow"><button disabled={busy}>{member ? "Save changes" : "Add member"}</button><button type="button" className="secondary" onClick={onDone}>Cancel</button></div>
    <FormError title="Could not save the member." message={error} />
  </form>;
}

function Statement({ chama, member }) {
  const [data, setData] = useState();
  const [error, setError] = useState("");
  useEffect(() => { api(`/api/v1/chama/${chama.id}/members/${member.id}/`).then(setData).catch((err) => setError(err.message)); }, [chama, member.id]);
  if (error) return <FormError title="Could not load the statement." message={error} />;
  if (!data) return <Loading />;
  return <div className="chamaStatement">
    <table>
      <caption>{member.full_name}'s contributions</caption>
      <thead><tr><th>Date</th><th>Contribution</th><th>Paid</th><th>Status</th><th>Fine</th></tr></thead>
      <tbody>{data.dues.map((d) => <tr key={d.id}>
        <td>{date(d.period_date)}</td><td>{money(d.amount)}</td><td>{money(d.paid)}</td><td><DueBadge due={d} />{d.excuse_reason && <small> · {d.excuse_reason}</small>}</td>
        <td>{Number(d.fine_amount) > 0 ? (d.fine_waived ? `Waived (${d.fine_waive_reason})` : `${money(d.fine_amount)}${Number(d.fine_owed) > 0 ? ` · owes ${money(d.fine_owed)}` : " · paid"}`) : "—"}</td>
      </tr>)}</tbody>
    </table>
    {data.payouts.length > 0 && <p>Received: {data.payouts.filter((p) => !p.reversed_at).map((p) => `${money(p.amount)} on ${date(p.paid_on)}${p.round ? ` (turn ${p.round})` : ""}`).join(", ") || "nothing"}</p>}
  </div>;
}

function Members({ chama, setChama, can, reload }) {
  const [editing, setEditing] = useState(null);  // member id, "new" or null
  const [statement, setStatement] = useState(null);
  const [error, setError] = useState("");
  const change = async (path, body) => {
    try { setChama(await api(`/api/v1/chama/${chama.id}/members/${path}`, { method: "POST", body: JSON.stringify(body || {}) })); setError(""); }
    catch (err) { setError(err.message); await reload(); }
  };
  // Removing a member: either they left (their record and anything they owe stay), or they were added by mistake and,
  // with no money paid in or out, are deleted completely.
  const remove = async (member) => {
    const mistake = !member.has_money_history;
    const values = await askForm({ title: `Remove ${member.full_name}?`,
      text: mistake ? "If they left, they owe nothing from tomorrow and their record stays. If they were added by mistake, they are deleted completely."
        : "They owe nothing from tomorrow. What they owe already stays owed, their payments stay on record, and their turn is removed.",
      confirmButtonText: "Remove", fields: [
        ...(mistake ? [{ name: "how", label: "Why are they going?", type: "select", value: "LEFT",
          options: [["LEFT", "They left the chama (keep their record)"], ["MISTAKE", "Added by mistake (delete completely)"]] }] : []),
        { name: "reason", label: "Reason", required: true, placeholder: "e.g. moved away" }] });
    if (!values) return;
    if (values.how === "MISTAKE") await change(`${member.id}/remove/`, { reason: values.reason });
    else await change(`${member.id}/leave/`, { reason: values.reason });
  };
  const rejoin = async (member) => {
    if (!(await confirmAction({ title: `${member.full_name} rejoins the chama?`, text: "They owe contributions again from today (nothing for the time they were away) and take the last turn.",
      confirmButtonText: "Rejoin" }))) return;
    await change(`${member.id}/rejoin/`);
  };
  const leaders = chama.members.filter((m) => m.active && m.role !== "MEMBER");
  return <section aria-labelledby="members-heading">
    <h2 id="members-heading">Leaders</h2>
    <ul className="chamaLeaders">{leaders.map((m) => <li key={m.id}><span>{m.role_label}</span><strong>{m.full_name}</strong><small>{m.phone}</small></li>)}</ul>
    <h2>Members ({chama.members.filter((m) => m.active).length})</h2>
    {can("chama.change_chama") && editing !== "new" && <button type="button" onClick={() => setEditing("new")}>Add a member</button>}
    {editing === "new" && <MemberForm chama={chama} setChama={setChama} onDone={() => setEditing(null)} />}
    <FormError title="Could not change the member." message={error} />
    <div className="trendTable"><table className="chamaMembersTable">
      <thead><tr><th className="chamaMemberCell">Member</th><th>ID number</th><th>Phone</th><th>Role</th><th>Paid in</th><th>Owes</th><th>Received</th><th>Next turn</th></tr></thead>
      <tbody>{chama.members.map((m) => <tr key={m.id} className={m.active ? undefined : "muted"}>
        <th scope="row" className="chamaMemberCell">
          <span>{m.full_name}{!m.active && <small> · left {date(m.left_on)}</small>}</span>
          {/* The actions sit under the name, so a wide table never pushes them out of sight. */}
          <div className="actionRow chamaMemberActions">
            <button type="button" className="secondary" onClick={() => setStatement(statement === m.id ? null : m.id)}>{statement === m.id ? "Hide statement" : "Statement"}</button>
            {can("chama.change_chama") && m.active && <button type="button" className="secondary" onClick={() => setEditing(m.id)}>Change</button>}
            {can("chama.change_chama") && m.active && (m.role === "TREASURER"
              ? <button type="button" className="secondary" disabled title="Make another member treasurer first">Remove</button>
              : <button type="button" className="danger" onClick={() => void remove(m)} aria-label={`Remove ${m.full_name}`}>Remove</button>)}
            {can("chama.change_chama") && !m.active && <button type="button" className="secondary" onClick={() => void rejoin(m)}>Rejoins</button>}
          </div>
          {can("chama.change_chama") && m.active && m.role === "TREASURER" && <small className="muted">To remove the treasurer, make another member treasurer first (Change).</small>}
        </th>
        <td>{m.id_number}</td><td>{m.phone}</td><td>{m.role_label}</td><td>{money(m.paid_in)}</td>
        <td className={Number(m.late) > 0 || Number(m.fines_owed) > 0 ? "loanLate" : undefined}>{money(Number(m.unpaid) + Number(m.fines_owed))}</td>
        <td>{money(m.received)}</td><td>{m.next_turn ? date(m.next_turn.date) : "—"}</td>
      </tr>)}</tbody>
    </table></div>
    {typeof editing === "number" && <MemberForm chama={chama} member={chama.members.find((m) => m.id === editing)} setChama={setChama} onDone={() => setEditing(null)} />}
    {statement && <Statement chama={chama} member={chama.members.find((m) => m.id === statement)} />}
  </section>;
}

function PayoutForm({ chama, setChama, next, onDone }) {
  const [method, setMethod] = useState("CASH");
  const { send, error, busy } = usePost(setChama);
  const active = next ? chama.still_to_receive : chama.members.filter((m) => m.active);
  const suggested = next ? Math.min(Number(next.collected ?? chama.money.held), Number(chama.money.held)) : Number(chama.money.held);
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const who = active.find((m) => String(m.id) === values.member)?.full_name;
    const swap = next?.member_id && String(next.member_id) !== values.member;
    if (!(await confirmAction({ title: `Give ${money(values.amount)} to ${who}?`,
      text: next ? `This is turn ${next.round}${swap ? `, which was ${next.member}'s turn` : ""}.` : "It comes out of the money the treasurer holds.",
      confirmButtonText: "Record payout" }))) return;
    if (await send(`/api/v1/chama/${chama.id}/payouts/`, { ...values, idempotency_key: crypto.randomUUID() })) onDone();
  };
  return <form className="formCard chamaInlineForm" onSubmit={(event) => void submit(event)}>
    <h3>{next ? `Give out turn ${next.round}` : "Give out money"}</h3>
    <fieldset disabled={busy} className="loanFields">
      <FormField label="Given to"><select name="member" defaultValue={next?.member_id || active[0]?.id}>{active.map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}</select></FormField>
      <FormField label={`Amount (${businessCurrency()})`} name="amount" type="number" min="0.01" max={Number(chama.money.held)} step="0.01" required defaultValue={suggested > 0 ? suggested : ""} />
      <FormField label="Given on" name="paid_on" type="date" max={todayText()} defaultValue={todayText()} required />
      <FormField label="Given by"><select name="method" value={method} onChange={(e) => setMethod(e.target.value)}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></FormField>
      <FormField label={method === "MPESA" ? "M-Pesa code" : "Reference (optional)"} name="reference" maxLength={120} required={method === "MPESA"} autoComplete="off" />
      <FormField label="Note (optional)"><TextBox name="notes" maxLength={500} /></FormField>
    </fieldset>
    <p className="muted">The treasurer holds {money(chama.money.held)}.</p>
    <div className="actionRow"><button disabled={busy}>Record payout</button><button type="button" className="secondary" onClick={onDone}>Cancel</button></div>
    <FormError title="Could not record the payout." message={error} />
  </form>;
}

// The members agree who receives next; the treasurer records it here.
function NextReceiver({ chama, setChama, can, next }) {
  const [editing, setEditing] = useState(false);
  const { send, error, busy } = usePost(setChama);
  const agreed = chama.next_receiver;
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (await send(`/api/v1/chama/${chama.id}/next-receiver/`, values)) setEditing(false);
  };
  return <div className="chamaNextReceiver">
    <h3>Who receives turn {next.round} ({date(next.date)})</h3>
    {agreed ? <p>The members agreed: <b>{agreed.full_name}</b>{agreed.note && <span className="muted"> · {agreed.note}</span>}</p>
      : chama.turn_choice === "AGREED" ? <p className="loanLate">Not agreed yet. Record the member the members agree on before giving out the money.</p>
        : <p className="muted">Next in the list: <b>{next.member}</b>. If the members agree someone else goes next, record it here.</p>}
    <p className="muted">Still to receive in this round of turns: {chama.still_to_receive.map((m) => m.full_name).join(", ")}</p>
    {can("chama.change_chama") && (editing
      ? <form className="chamaInlineForm" onSubmit={(event) => void submit(event)} aria-label="Agreed next receiver">
        <fieldset disabled={busy} className="loanFields">
          <FormField label="The members agreed"><select name="member" defaultValue={agreed?.id || ""} required>
            <option value="" disabled>Choose the member</option>
            {chama.still_to_receive.map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}
          </select></FormField>
          <FormField label="Note (optional)"><TextBox name="note" maxLength={500} placeholder="e.g. agreed at Sunday's meeting" /></FormField>
        </fieldset>
        <div className="actionRow"><button disabled={busy}>Save who receives next</button><button type="button" className="secondary" onClick={() => setEditing(false)}>Cancel</button></div>
        <FormError title="Could not save who receives next." message={error} />
      </form>
      : <div className="actionRow">
        <button type="button" className={agreed ? "secondary" : undefined} onClick={() => setEditing(true)}>{agreed ? "Change who receives next" : "Record who the members agreed"}</button>
        {agreed && <button type="button" className="secondary" disabled={busy} onClick={() => void send(`/api/v1/chama/${chama.id}/next-receiver/`, { member: null })}>Clear</button>}
      </div>)}
    {!editing && error && <FormError title="Could not change who receives next." message={error} />}
  </div>;
}

function Turns({ chama, setChama, can }) {
  const [giving, setGiving] = useState(false);
  const [order, setOrder] = useState(null);
  const { send, error, busy } = usePost(setChama);
  const next = chama.turns.find((t) => t.status !== "GIVEN");
  const active = chama.members.filter((m) => m.active);
  const list = order || active.map((m) => m.id);
  const move = (index, step) => { const ids = [...list]; [ids[index], ids[index + step]] = [ids[index + step], ids[index]]; setOrder(ids); };
  const nameOf = (id) => active.find((m) => m.id === id)?.full_name;
  return <section aria-labelledby="turns-heading">
    <h2 id="turns-heading">Whose turn</h2>
    <p className="muted">Each turn is {chama.periods_per_round} contribution{chama.periods_per_round === 1 ? "" : "s"}. A member receives the money on the last contribution date of their turn.</p>
    {next && <NextReceiver chama={chama} setChama={setChama} can={can} next={next} />}
    {next && can("chama.add_chamapayout") && (giving
      ? <PayoutForm chama={chama} setChama={setChama} next={next} onDone={() => setGiving(false)} />
      : next.member_id ? <button type="button" onClick={() => setGiving(true)}>Give {next.member} their money</button> : null)}
    <ol className="chamaTurns">{chama.turns.map((turn) => <li key={turn.round} className={`chamaTurnRow ${turn.status.toLowerCase()}`}>
      <span className="chamaTurn">{turn.round}</span>
      <div><strong>{turn.member || "To be agreed"}</strong>{turn.agreed && <small className="muted"> · agreed by the members</small>}<span className="muted"> · {date(turn.status === "GIVEN" ? turn.paid_on : turn.date)}</span></div>
      <span className={`loanStatus ${turn.status === "GIVEN" ? "repaid" : turn.status === "DUE" ? "overdue" : ""}`}>
        {turn.status === "GIVEN" ? `Received ${money(turn.amount)}` : turn.status === "DUE" ? "Due now" : "Coming"}
        {turn.collected != null && turn.status !== "GIVEN" ? ` · collected ${money(turn.collected)} of ${money(turn.expected)}` : ""}
      </span>
      {turn.status === "GIVEN" && can("chama.change_chama") && turn.round === Math.max(...chama.turns.filter((t) => t.status === "GIVEN").map((t) => t.round)) &&
        <ReverseButton path={`/api/v1/chama/payouts/${turn.payout_id}/reverse/`} title={`Reverse ${turn.member}'s payout of ${money(turn.amount)}?`}
          text="Use this only if it was recorded by mistake. The money goes back to the treasurer and it becomes their turn again." setChama={setChama} />}
    </li>)}</ol>
    {can("chama.change_chama") && chama.turn_choice !== "AGREED" && <details className="chamaOrder">
      <summary>Change the turn order</summary>
      <p className="muted">Members who have already received this cycle keep their place; the order decides who is next among the rest.</p>
      <ol>{list.map((id, index) => <li key={id}><span>{nameOf(id)}</span>
        <button type="button" className="iconButton" aria-label={`Move ${nameOf(id)} up`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={16} aria-hidden="true" /></button>
        <button type="button" className="iconButton" aria-label={`Move ${nameOf(id)} down`} disabled={index === list.length - 1} onClick={() => move(index, 1)}><ArrowDown size={16} aria-hidden="true" /></button>
      </li>)}</ol>
      <button type="button" disabled={busy || !order} onClick={() => void send(`/api/v1/chama/${chama.id}/turns/`, { order: list }).then((ok) => ok && setOrder(null))}>Save turn order</button>
      <FormError title="Could not change the order." message={error} />
    </details>}
  </section>;
}

function ReverseButton({ path, title, text, setChama, label = "Reverse" }) {
  const [error, setError] = useState("");
  const go = async () => {
    const values = await askForm({ title, text, confirmButtonText: "Confirm", fields: [{ name: "reason", label: "Reason", required: true, placeholder: "e.g. entered twice" }] });
    if (!values) return;
    try { setChama(await api(path, { method: "POST", body: JSON.stringify(values) })); setError(""); } catch (err) { setError(err.message); }
  };
  return <>
    <button type="button" className="secondary" onClick={() => void go()}>{label}</button>
    {error && <FormError title="Could not make the correction." message={error} />}
  </>;
}

function Fines({ chama, setChama, can }) {
  return <section aria-labelledby="fines-heading">
    <h2 id="fines-heading">Fines</h2>
    <p className="muted">{Number(chama.fine_amount) > 0 ? `A member who has not paid in full by the deadline is fined ${money(chama.fine_amount)} once for that contribution. Excused members are fined only if they miss the date they promised.` : "This chama does not fine late payments. Set a fine under Rules."}</p>
    {chama.fines.length ? <div className="trendTable"><table>
      <thead><tr><th>Member</th><th>Contribution of</th><th>Fine</th><th>Status</th><th><span className="visuallyHidden">Action</span></th></tr></thead>
      <tbody>{chama.fines.map((f) => <tr key={f.id} className={f.fine_waived ? "muted" : undefined}>
        <th scope="row">{f.member}</th><td>{date(f.period_date)}</td><td>{money(f.fine_amount)}</td>
        <td>{f.fine_waived ? `Waived: ${f.fine_waive_reason}` : Number(f.fine_owed) > 0 ? `Owes ${money(f.fine_owed)}` : "Paid"}</td>
        <td>{!f.fine_waived && Number(f.fine_paid) === 0 && can("chama.change_chama") &&
          <ReverseButton label="Waive" path={`/api/v1/chama/dues/${f.id}/waive-fine/`} title={`Waive ${f.member}'s fine of ${money(f.fine_amount)}?`}
            text="Only when the members agree, for example the member was sick." setChama={setChama} />}</td>
      </tr>)}</tbody>
    </table></div> : <Empty>No fines so far.</Empty>}
    <h2>Excuses</h2>
    {chama.excuses.length ? <div className="trendTable"><table>
      <thead><tr><th>Member</th><th>Contribution of</th><th>Promised to pay by</th><th>Reason</th><th>Status</th></tr></thead>
      <tbody>{chama.excuses.map((e) => <tr key={e.id}>
        <th scope="row">{e.member}</th><td>{date(e.period_date)}</td><td>{date(e.excused_until)}</td><td>{e.excuse_reason}</td>
        <td>{e.status === "PAID" ? "Paid" : Number(e.fine_amount) > 0 ? "Missed the promise: fined" : e.status === "LATE" ? "Missed the promise" : "Waiting"}</td>
      </tr>)}</tbody>
    </table></div> : <Empty>No member has asked to pay late. Use Excuse on the board when one does.</Empty>}
  </section>;
}

function Record({ chama, setChama, can }) {
  const [giving, setGiving] = useState(false);
  const part = (a) => `${a.part === "FINE" ? "fine of" : ""} ${date(a.period_date)} ${money(a.amount)}`.trim();
  return <section aria-labelledby="record-heading">
    <h2 id="record-heading">Money paid in</h2>
    {chama.payments.length ? <div className="trendTable"><table>
      <thead><tr><th>Date</th><th>Member</th><th>Amount</th><th>By</th><th>What it paid</th><th>Recorded by</th><th><span className="visuallyHidden">Action</span></th></tr></thead>
      <tbody>{chama.payments.map((p) => <tr key={p.id} className={p.reversed_at ? "muted" : undefined}>
        <td>{date(p.paid_on)}</td><th scope="row">{p.member}</th>
        <td>{money(p.amount)}{p.reversed_at && <small> · reversed ({p.reverse_reason})</small>}</td>
        <td>{methodName(p.method)}{p.reference && ` · ${p.reference}`}</td>
        <td>{p.allocations.map(part).join("; ")}</td><td>{p.recorded_by}</td>
        <td>{!p.reversed_at && can("chama.change_chama") && <ReverseButton path={`/api/v1/chama/payments/${p.id}/reverse/`}
          title={`Reverse ${p.member}'s payment of ${money(p.amount)}?`} text="Use this only if the money never came in or was entered twice. They will owe it again." setChama={setChama} />}</td>
      </tr>)}</tbody>
    </table></div> : <Empty>No payments recorded yet.</Empty>}
    <h2>Money given out</h2>
    {chama.payout_mode === "SAVINGS" && can("chama.add_chamapayout") && (giving
      ? <PayoutForm chama={chama} setChama={setChama} onDone={() => setGiving(false)} />
      : <button type="button" onClick={() => setGiving(true)}>Give out money</button>)}
    {chama.payouts.length ? <div className="trendTable"><table>
      <thead><tr><th>Date</th><th>Given to</th><th>Amount</th><th>By</th><th>Turn</th><th>Recorded by</th></tr></thead>
      <tbody>{chama.payouts.map((p) => <tr key={p.id} className={p.reversed_at ? "muted" : undefined}>
        <td>{date(p.paid_on)}</td><th scope="row">{p.member}</th>
        <td>{money(p.amount)}{p.reversed_at && <small> · reversed ({p.reverse_reason})</small>}</td>
        <td>{methodName(p.method)}{p.reference && ` · ${p.reference}`}</td><td>{p.round || "—"}</td><td>{p.recorded_by}</td>
      </tr>)}</tbody>
    </table></div> : <Empty>Nothing given out yet.</Empty>}
  </section>;
}

function Rules({ chama, setChama, can }) {
  const { send, error, busy } = usePost(setChama);
  const editable = can("chama.change_chama");
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!(await confirmAction({ title: "Save the chama's rules?", text: "New amounts and fines apply from the next contribution. Past contributions and fines stay as they were.", confirmButtonText: "Save rules" }))) return;
    await send(`/api/v1/chama/${chama.id}/`, values, "PATCH");
  };
  return <form className="formCard wide" onSubmit={(event) => void submit(event)}>
    <h2>Rules</h2>
    <fieldset disabled={busy || !editable} className="loanFields">
      <FormField label="Chama name" name="name" required maxLength={120} defaultValue={chama.name} />
      <FormField label={`${{ DAILY: "Daily", WEEKLY: "Weekly", MONTHLY: "Monthly" }[chama.frequency] || "Each"} contribution per member (${businessCurrency()})`}
        name="contribution_amount" type="number" min="0.01" step="0.01" required defaultValue={Number(chama.contribution_amount)} />
      <p className="muted">A new amount applies from the next contribution; contributions already due keep their amount.</p>
      <FormField label="Days allowed to pay after it" name="grace_days" type="number" min="0" max="60" step="1" defaultValue={chama.grace_days} />
      <FormField label={`Fine for paying late (${businessCurrency()})`} name="fine_amount" type="number" min="0" step="0.01" defaultValue={Number(chama.fine_amount)} />
      <FormField label="How often"><select name="frequency" defaultValue={chama.frequency} disabled={chama.schedule_locked}>{FREQUENCIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></FormField>
      {chama.payout_mode === "ROTATION" && <FormField label="Who receives next"><select name="turn_choice" defaultValue={chama.turn_choice}>
        <option value="ORDER">In the order the members are listed</option>
        <option value="AGREED">The members agree who receives next, each turn</option>
      </select></FormField>}
      <FormField label="Contributions in each turn" name="periods_per_round" type="number" min="1" max="60" step="1" defaultValue={chama.periods_per_round} disabled={chama.turns_locked || chama.payout_mode !== "ROTATION"} />
      <FormField label="Notes (optional)"><TextArea name="notes" maxLength={2000} defaultValue={chama.notes} placeholder="e.g. agreed rules, meeting day, bank account" /></FormField>
    </fieldset>
    {chama.schedule_locked && <p className="muted">How often members contribute cannot change once contributions have started, because past records depend on it.</p>}
    {editable && <button disabled={busy}>Save rules</button>}
    <FormError title="Could not save the rules." message={error} />
  </form>;
}
