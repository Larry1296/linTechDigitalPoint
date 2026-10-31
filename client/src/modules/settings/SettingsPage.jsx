import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { FormField } from "../../components/forms/FormField";
import { ErrorState, Loading } from "../../components/States";
import { confirmAction } from "../../core/ui/alerts";
import { LogoImage } from "../../components/LogoImage";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { MpesaPaymentsSetup } from "./MpesaPaymentsSetup";
import { allowedModules, findSector, fitModules, moduleProblem, toggleModule, useBusinessProfiles } from "../platform/businessSetupData";
import { BusinessPartsChoice, MONEY_PARTS } from "../../core/organization/MoneyModeChoice";
import { TextBox } from "../../components/forms/TextBox";

const roleLabels = {
  OWNER: "Owner",
  ADMIN: "Administrator — full access",
  MANAGER: "Manager — all daily operations",
  CASHIER: "Cashier — counter sales and payments",
  INVENTORY: "Inventory — products and stock",
  ACCOUNTANT: "Accountant — expenses and reports",
  SERVICE_ATTENDANT: "Service attendant — service jobs",
  READ_ONLY: "Read only — view records",
  CUSTOM: "Custom",
};
const shortRole = (role) => roleLabels[role]?.split(" — ")[0] || role;

export function SettingsPage() {
  const { user } = useAuth();
  const role = user?.roles?.[0];
  const isAdmin = role === "OWNER" || role === "ADMIN";
  return <>
    <h1>Settings</h1>
    {isAdmin && <BusinessLogo />}
    {isAdmin && <BusinessSettings />}
    {isAdmin && user.organization?.enabled_modules?.includes("pos") && <section className="formCard" aria-labelledby="mpesa-payments-heading">
      <h2 id="mpesa-payments-heading">M-Pesa payments</h2>
      <MpesaPaymentsSetup />
    </section>}
    {isAdmin && <BranchSettings />}
    {isAdmin && <StaffSettings isOwner={role === "OWNER"} />}
    <PinSettings />
    <PasswordSettings />
  </>;
}

function BusinessLogo() {
  const { user, refresh } = useAuth();
  const [logo, setLogo] = useState(user?.organization?.logo_url || "");
  const [logoDark, setLogoDark] = useState(user?.organization?.logo_dark_url || "");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const change = async (request, done, failure) => {
    setBusy(true); setNotice(null);
    try {
      const organization = await request();
      setLogo(organization.logo_url);
      setLogoDark(organization.logo_dark_url || "");
      setNotice({ kind: "success", text: done });
      await refresh();
    } catch (e) {
      setNotice({ kind: "error", title: failure, text: e.message });
    } finally {
      setBusy(false);
    }
  };
  const upload = (event) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    const body = new FormData();
    body.append("logo", file);
    void change(() => api("/api/v1/tenancy/settings/logo/", { method: "POST", body }),
      "Logo saved. It now shows in your dashboard and on every customer receipt.", "Could not save the logo.");
  };
  const remove = () => change(() => api("/api/v1/tenancy/settings/logo/", { method: "DELETE" }),
    "Logo removed. Your business name is used instead.", "Could not remove the logo.");
  return <section className="formCard businessLogoCard" aria-labelledby="business-logo-heading">
    <h2 id="business-logo-heading">Business logo</h2>
    <p className="muted">Your logo appears in your dashboard and on receipts your customers receive by WhatsApp, email or print. A plain white, grey or black background is removed automatically, and the logo is resized to fit every screen.</p>
    {logo ? <div className="businessLogoPreviews">
      <figure className="businessLogoPreview onLight">
        <LogoImage key={logo} slot="preview" src={logo} alt={`${user.organization.name} logo on receipts`} />
        <figcaption>On receipts and email</figcaption>
      </figure>
      <figure className="businessLogoPreview onDark">
        <LogoImage key={logoDark || logo} slot="preview" src={logoDark || logo} alt={`${user.organization.name} logo on the navigation bar`} />
        <figcaption>On the navigation bar</figcaption>
      </figure>
    </div> : <div className="businessLogoPreview"><span className="muted">No logo yet. Receipts show your business name.</span></div>}
    <div className="businessLogoActions">
      <label className={`button${busy ? " disabled" : ""}`}>
        {busy ? "Saving…" : logo ? "Replace logo" : "Upload logo"}
        <input type="file" accept="image/png,image/jpeg,image/webp" onChange={upload} disabled={busy} className="sr" />
      </label>
      {logo && <button type="button" className="secondary" onClick={() => void remove()} disabled={busy}>Remove logo</button>}
    </div>
    {notice?.kind === "error" && <FormError title={notice.title} message={notice.text} />}
    {notice?.kind === "success" && <FormSuccess message={notice.text} />}
  </section>;
}

function BusinessSettings() {
  const { refresh } = useAuth();
  const { catalogue, error: catalogueError } = useBusinessProfiles();
  const [data, setData] = useState();
  const [profile, setProfile] = useState(null);
  const [notes, setNotes] = useState([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const show = (settings) => {
    setData(settings);
    setProfile({ business_model: settings.business_model, sector: settings.sector, business_size: settings.business_size,
      business_type: settings.business_type, modules: new Set(settings.enabled_modules), money_mode: settings.money_mode || "ONE_DRAWER",
      structure: settings.structure || "SINGLE", part_names: settings.own_part_names || {}, sale_mpesa_to: settings.sale_mpesa_to || "AGENT_LINE" });
  };
  const load = useCallback(() => {
    setError("");
    api("/api/v1/tenancy/settings/").then(show).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  if ((error || catalogueError) && !(data && catalogue)) return <ErrorState message={error || catalogueError} retry={load} />;
  if (!data || !catalogue) return <Loading />;
  const allowed = allowedModules(catalogue, profile.business_model);
  const isOther = catalogue.other_sectors.includes(profile.sector);
  // A different way of making money keeps only the tools that still fit; the owner reviews them before saving.
  const chooseModel = (model) => {
    const { modules, removed } = fitModules(catalogue, model, profile.modules);
    setNotes(removed.length ? [`${removed.join(", ")} turned off: not used when you ${catalogue.models.find((m) => m.id === model).phrase}. Your past records are kept.`] : []);
    setProfile({ ...profile, business_model: model, sector: "", business_type: "", modules });
  };
  const chooseSector = (id) => {
    const sector = findSector(catalogue, id);
    setProfile({ ...profile, sector: id, business_type: sector && !catalogue.other_sectors.includes(id) ? sector.label : "" });
  };
  const chooseModule = (id) => {
    const result = toggleModule(catalogue, profile.business_model, profile.modules, id);
    setProfile({ ...profile, modules: result.modules });
    setNotes(result.notes);
  };
  const save = async (event) => {
    event.preventDefault();
    const problem = moduleProblem(catalogue, profile.business_model, profile.modules);
    if (problem) { setError(problem); return; }
    const form = new FormData(event.currentTarget);
    const body = Object.fromEntries(["name", "phone", "email", "address", "timezone", "receipt_footer"].map((key) => [key, form.get(key) || ""]));
    Object.assign(body, { business_model: profile.business_model, sector: profile.sector, business_size: profile.business_size,
      business_type: profile.business_type, enabled_modules: [...profile.modules], money_mode: profile.money_mode,
      structure: profile.structure, sale_mpesa_to: profile.sale_mpesa_to, part_names: Object.fromEntries(MONEY_PARTS.map((part) => [part.key, profile.part_names[part.key]?.trim() || ""])) });
    setBusy(true); setError(""); setMessage("");
    try {
      show(await api("/api/v1/tenancy/settings/", { method: "PATCH", body: JSON.stringify(body) }));
      setNotes([]);
      setMessage("Business settings saved.");
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return <form className="formCard" onSubmit={(event) => void save(event)}>
    <h2>Business details</h2>
    <FormField label="Business name" name="name" defaultValue={data.name} required maxLength={160} />
    <label>How the business makes money<select value={profile.business_model} onChange={(e) => chooseModel(e.target.value)}>
      {catalogue.models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}
    </select></label>
    <label>Kind of business<select value={profile.sector} onChange={(e) => chooseSector(e.target.value)}>
      <option value="">Choose…</option>
      {catalogue.sectors[profile.business_model].map((sector) => <option key={sector.id} value={sector.id}>{sector.label}</option>)}
    </select></label>
    {(isOther || !profile.sector) && <label>Name your kind of business<TextBox value={profile.business_type} onChange={(e) => setProfile({ ...profile, business_type: e.target.value })} maxLength={100} /></label>}
    <label>People working in the business<select value={profile.business_size} onChange={(e) => setProfile({ ...profile, business_size: e.target.value })}>
      {catalogue.sizes.map((size) => <option key={size.id} value={size.id}>{size.label}</option>)}
    </select></label>
    <FormField label="Phone" name="phone" defaultValue={data.phone} maxLength={40} />
    <FormField label="Email" name="email" type="email" defaultValue={data.email} />
    <FormField label="Address" name="address" defaultValue={data.address} />
    <FormField label="Time zone" name="timezone" defaultValue={data.timezone} required />
    <FormField label="Receipt footer" name="receipt_footer" defaultValue={data.receipt_footer} maxLength={255} />
    <p>Currency: <strong>{data.currency}</strong> (fixed after setup so past records stay correct).</p>
    {data.plan && <section className="planSummary" aria-label="Your plan">
      <h3>Plan: {data.plan.name || "None"}{data.plan.complimentary ? " · free, every tool" : ""}{data.plan.ended ? " · ended" : ""}</h3>
      <p>Includes: {catalogue.modules.filter((m) => data.plan.includes.includes(m.id)).map((m) => m.label).join(", ")}.</p>
      {data.plan.waiting.length > 0 && <p className="muted">Chosen but not in {data.plan.name}, so switched off until you are on Pro: {catalogue.modules.filter((m) => data.plan.waiting.includes(m.id)).map((m) => m.label).join(", ")}.</p>}
      {!data.plan.complimentary && <p className="muted"><Link to="/admin/subscription">Change plan</Link>: switch between Basic and Pro when you pay for the next month.</p>}
    </section>}
    <fieldset className="checkList">
      <legend>Tools</legend>
      {catalogue.modules.filter((module) => allowed.includes(module.id)).map((module) => {
        // Tools outside the plan cannot be switched on here; they unlock with an upgrade.
        const locked = Boolean(data.plan_modules && !data.plan_modules.includes(module.id));
        return <label key={module.id} className={locked ? "lockedTool" : undefined}>
          <input type="checkbox" checked={!locked && profile.modules.has(module.id)} disabled={locked} onChange={() => chooseModule(module.id)} /> {module.label}
          {locked && <small> · Pro plan</small>}
        </label>;
      })}
    </fieldset>
    {data.plan_modules && allowed.some((id) => !data.plan_modules.includes(id)) && <p className="muted">Tools marked Pro plan are not in your current plan. <Link to="/admin/subscription">Upgrade to Pro</Link> to use them.</p>}
    {notes.length > 0 && <p className="muted" role="status">{notes.join(" ")}</p>}
    {MONEY_PARTS.filter((part) => part.modules.some((module) => profile.modules.has(module))).length > 1 && <BusinessPartsChoice parts={MONEY_PARTS.filter((part) => part.modules.some((module) => profile.modules.has(module)))}
      sector={profile.sector} value={profile} onChange={(next) => setProfile({ ...profile, ...next })} />}
    {profile.modules.has("mpesa") && MONEY_PARTS.filter((part) => part.modules.some((module) => profile.modules.has(module))).length > 1 && profile.money_mode === "ONE_DRAWER" &&
      <fieldset className="checkList">
        <legend>When customers pay for sales by M-Pesa, where does the money go?</legend>
        <label><input type="radio" name="sale_mpesa_to" checked={profile.sale_mpesa_to === "AGENT_LINE"} onChange={() => setProfile({ ...profile, sale_mpesa_to: "AGENT_LINE" })} /> To the agent line</label>
        <label><input type="radio" name="sale_mpesa_to" checked={profile.sale_mpesa_to === "TILL"} onChange={() => setProfile({ ...profile, sale_mpesa_to: "TILL" })} /> To a till of the business's own</label>
        <small className="muted">With one drawer, the M-Pesa shift counts all the money: the cash in the drawer{profile.sale_mpesa_to === "AGENT_LINE" ? " and everything on the agent line" : ""}, and expects the sales with the agency's money.</small>
      </fieldset>}
    {(data.money_mode || "ONE_DRAWER") !== profile.money_mode && <p className="muted">Past records are kept as they are. From now on the money check
      {profile.money_mode === "SEPARATE_CASH" ? " counts each part's cash drawer on its own: count each drawer once to start." : " counts all the cash as one drawer."}</p>}
    <button disabled={busy}>{busy ? "Saving…" : "Save business details"}</button>
    <FormSuccess message={message} />
    <FormError title="Could not save business details." message={error} />
  </form>;
}

function Notice({ notice, place }) {
  if (notice?.place !== place) return null;
  return notice.kind === "error" ? <FormError title={notice.title} message={notice.text} /> : <FormSuccess message={notice.text} />;
}

function BranchSettings() {
  const { refresh } = useAuth();
  const [branches, setBranches] = useState();
  const [editing, setEditing] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    api("/api/v1/tenancy/branches/").then(setBranches).catch((e) => setLoadError(e.message));
  }, []);
  useEffect(load, [load]);
  if (loadError && !branches) return <ErrorState message={loadError} retry={load} />;
  if (!branches) return <Loading />;
  // Each message appears directly below the form or list the action came from.
  const run = async (place, failure, work, done) => {
    setBusy(true); setNotice(null);
    try {
      await work();
      setNotice({ place, kind: "success", text: done });
      load();
      await refresh();
      return true;
    } catch (e) {
      setNotice({ place, kind: "error", title: failure, text: e.message || "Please try again." });
      return false;
    } finally {
      setBusy(false);
    }
  };
  const add = (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    return run("add", "Could not add the branch.", async () => {
      await api("/api/v1/tenancy/branches/", { method: "POST", body: JSON.stringify(data) });
      form.reset();
    }, `Added ${data.name}. Switch to it from the Branch menu at the top of the page.`);
  };
  const save = async (event) => {
    event.preventDefault();
    const body = JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)));
    if (await run("edit", `Could not save ${editing.name}.`,
      () => api(`/api/v1/tenancy/branches/${editing.id}/`, { method: "PATCH", body }), "Branch details saved.")) {
      setEditing(null);
      setNotice({ place: "list", kind: "success", text: "Branch details saved." });
    }
  };
  const remove = async (branch) => {
    if (!(await confirmAction({
      title: `Delete ${branch.name}?`,
      text: "Only a branch with no sales, stock or money records can be deleted. This cannot be undone.",
      confirmButtonText: "Delete branch",
    }))) return;
    if (await run("list", `Could not delete ${branch.name}.`,
      () => api(`/api/v1/tenancy/branches/${branch.id}/`, { method: "DELETE" }), `Deleted ${branch.name}.`)
      && editing?.id === branch.id) setEditing(null);
  };
  return <section className="formCard">
    <h2>Branches</h2>
    <p>Each branch keeps its own stock, sales and cash. Reports can be viewed per branch. The main branch can be edited but not deleted.</p>
    <div className="tableWrap"><table>
      <thead><tr><th>Branch</th><th>Address</th><th /></tr></thead>
      <tbody>{branches.map((branch) => <tr key={branch.id}>
        <td>{branch.name}{(branch.is_main || branch.is_active) && <><br /><small>{[branch.is_main && "Main branch", branch.is_active && "Current"].filter(Boolean).join(" · ")}</small></>}</td>
        <td>{branch.address}</td>
        <td>
          <button type="button" className="secondary" disabled={busy} onClick={() => { setEditing(branch); setNotice(null); }} aria-label={`Edit ${branch.name}`}>Edit</button>
          {!branch.is_main && <> <button type="button" className="secondary" disabled={busy} onClick={() => void remove(branch)} aria-label={`Delete ${branch.name}`}>Delete</button></>}
        </td>
      </tr>)}</tbody>
    </table></div>
    <Notice notice={notice} place="list" />
    {editing && <form key={editing.id} onSubmit={(event) => void save(event)}>
      <h3>Edit {editing.name}</h3>
      <FormField label="Branch name" name="name" defaultValue={editing.name} required maxLength={160} />
      <FormField label="Address" name="address" defaultValue={editing.address} />
      <FormField label="Phone" name="phone" defaultValue={editing.phone} maxLength={30} />
      <FormField label="Email" name="email" type="email" defaultValue={editing.email} />
      <button disabled={busy}>{busy ? "Saving…" : "Save branch"}</button>{" "}
      <button type="button" className="secondary" onClick={() => { setEditing(null); setNotice(null); }}>Cancel</button>
      <Notice notice={notice} place="edit" />
    </form>}
    <form onSubmit={(event) => void add(event)}>
      <h3>Add a branch</h3>
      <FormField label="Branch name" name="name" required maxLength={160} />
      <FormField label="Address" name="address" />
      <button disabled={busy}>{busy ? "Adding…" : "Add branch"}</button>
      <Notice notice={notice} place="add" />
    </form>
  </section>;
}

function StaffSettings({ isOwner }) {
  const [data, setData] = useState();
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    api("/api/v1/tenancy/staff/").then(setData).catch((e) => setLoadError(e.message));
  }, []);
  useEffect(load, [load]);
  if (loadError && !data) return <ErrorState message={loadError} retry={load} />;
  if (!data) return <Loading />;
  const assignable = data.roles.filter((role) => isOwner || role !== "ADMIN");
  const add = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(true); setNotice(null);
    try {
      const member = await api("/api/v1/tenancy/staff/", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
      form.reset();
      setNotice({ place: "add", kind: "success", text: `Added ${member.username}. Share their username and password with them; they can change the password in Settings.` });
      load();
    } catch (e) {
      setNotice({ place: "add", kind: "error", title: "Could not add the staff member.", text: e.message });
    } finally {
      setBusy(false);
    }
  };
  const change = async (member, body) => {
    setNotice(null);
    try {
      await api(`/api/v1/tenancy/staff/${member.id}/`, { method: "PATCH", body: JSON.stringify(body) });
      load();
    } catch (e) {
      setNotice({ place: "list", kind: "error", title: `Could not update ${member.username}.`, text: e.message });
    }
  };
  return <section className="formCard">
    <h2>Staff</h2>
    <p>Give each person their own sign-in. Their role decides what they can see and do.
      {isOwner && " You can also keep anyone out of the pages you choose: they leave that person's menu and stay closed to them. You always see every page, and Investments is yours alone."}</p>
    <div className="tableWrap"><table>
      <thead><tr><th>Name</th><th>Role</th><th>Status</th>{isOwner && <th>Pages they cannot open</th>}<th /></tr></thead>
      <tbody>{data.staff.map((member) => {
        const locked = member.role === "OWNER" || (member.role === "ADMIN" && !isOwner);
        return <tr key={member.id}>
          <td>{member.name || member.username}<br /><small>{member.username}{member.email ? ` · ${member.email}` : ""}</small></td>
          <td>{locked ? shortRole(member.role) : <select aria-label={`Role for ${member.username}`} value={member.role} onChange={(event) => void change(member, { role: event.target.value })}>
            {[...new Set([member.role, ...assignable])].map((role) => <option key={role} value={role}>{shortRole(role)}</option>)}
          </select>}</td>
          <td>{member.status === "ACTIVE" ? "Active" : "Suspended"}</td>
          {isOwner && <td>{member.role === "OWNER" ? "None: the owner sees every page" : <details className="staffPages">
            <summary>{member.hidden_pages?.length ? member.hidden_pages.map((key) => data.pages.find((page) => page.key === key)?.label || key).join(", ") : "None"}</summary>
            {data.pages.map((page) => <label key={page.key}><input type="checkbox" checked={(member.hidden_pages || []).includes(page.key)}
              aria-label={`${member.username} cannot open ${page.label}`}
              onChange={(event) => void change(member, { hidden_pages: event.target.checked ? [...(member.hidden_pages || []), page.key] : (member.hidden_pages || []).filter((key) => key !== page.key) })} /> {page.label}</label>)}
          </details>}</td>}
          <td>{!locked && <button type="button" className="secondary" onClick={() => void change(member, { status: member.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE" })}>
            {member.status === "ACTIVE" ? "Suspend" : "Reactivate"}
          </button>}</td>
        </tr>;
      })}</tbody>
    </table></div>
    <Notice notice={notice} place="list" />
    <form onSubmit={(event) => void add(event)}>
      <h3>Add a staff member</h3>
      <FormField label="First name" name="first_name" maxLength={150} />
      <FormField label="Last name" name="last_name" maxLength={150} />
      <FormField label="Username" name="username" required maxLength={150} autoComplete="off" />
      <FormField label="Email" name="email" type="email" required />
      <FormField label="Temporary password" name="password" type="password" required minLength={8} autoComplete="new-password" />
      <label>Role<select name="role" defaultValue="CASHIER" required>
        {assignable.map((role) => <option key={role} value={role}>{roleLabels[role] || role}</option>)}
      </select></label>
      <button disabled={busy}>{busy ? "Adding…" : "Add staff member"}</button>
      <Notice notice={notice} place="add" />
    </form>
  </section>;
}

// Each person's lock PIN opens the workspace after they lock it. The private pages (M-Pesa, investments) each open only
// with their own PIN, the business's: the owner sets and resets those, each different. Every change needs the sign-in password.
function PinSettings() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [which, setWhich] = useState("");
  const load = useCallback(() => api("/api/v1/auth/lock-pin/").then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);
  if (!data) return error ? <ErrorState message={error} retry={load} /> : <Loading />;
  const name = (page) => (page ? `the ${data.pages[page].label} PIN` : "your lock PIN");
  const save = async (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    if (!/^\d{4,6}$/.test(form.get("pin"))) { setError("A PIN is 4 to 6 digits."); return; }
    if (form.get("pin") !== form.get("again")) { setError("The two PINs are not the same."); return; }
    setBusy(true); setError(""); setSaved("");
    try {
      setData(await api("/api/v1/auth/lock-pin/", { method: "POST", body: JSON.stringify({ page: which, pin: form.get("pin"), password: form.get("password") }) }));
      setSaved(`Saved ${name(which)}.`);
      formElement.reset();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <section className="formCard pinSettings" aria-labelledby="pin-heading">
    <h2 id="pin-heading">Lock PIN and private pages</h2>
    <p>The workspace locks only when you press Lock, and opens with your own lock PIN. M-Pesa and investments are private pages: each
      opens only with its own PIN, never with a sign-in password, and locks after 5 minutes untouched.
      {data.is_owner ? " You set and reset their PINs, each different. Give the M-Pesa PIN to the people who run the agency; Investments is yours alone."
        : " The business owner sets their PINs; ask them if you forget one."}</p>
    <div className="pinRow"><strong>Your lock PIN</strong><span>{data.pin.set ? `Set · ${data.pin.length} digits` : "Not set yet"}</span></div>
    {Object.entries(data.pages).map(([page, info]) => <div className="pinRow" key={page}>
      <strong>{info.label} PIN</strong>
      <span>{!info.set ? "Not set yet" : data.is_owner ? `Set · ${info.length} digits` : "Set by the business owner"}</span>
    </div>)}
    <form onSubmit={(event) => void save(event)}>
      <label>PIN to set
        <select value={which} onChange={(event) => setWhich(event.target.value)}>
          <option value="">{data.pin.set ? "Change my lock PIN" : "My lock PIN"}</option>
          {data.is_owner && Object.entries(data.pages).map(([page, info]) => <option key={page} value={page}>{info.set ? `Change or reset the ${info.label} PIN` : `Set the ${info.label} PIN`}</option>)}
        </select>
      </label>
      <FormField label="New PIN (4 to 6 digits)" name="pin" type="password" inputMode="numeric" maxLength={6} required autoComplete="off" />
      <FormField label="New PIN again" name="again" type="password" inputMode="numeric" maxLength={6} required autoComplete="off" />
      <FormField label="Your sign-in password" name="password" type="password" required autoComplete="current-password" />
      <button disabled={busy}>{busy ? "Saving…" : "Save PIN"}</button>
    </form>
    <FormError title="Could not save the PIN." message={error} />
    <FormSuccess message={saved} />
  </section>;
}

function PasswordSettings() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (form.get("new_password") !== form.get("confirm_password")) { setError("The new passwords do not match."); return; }
    setBusy(true); setError("");
    try {
      await api("/api/v1/auth/password/change/", { method: "POST", body: JSON.stringify({ current_password: form.get("current_password"), new_password: form.get("new_password") }) });
      // Changing the password signs out every device, including this one.
      navigate("/login", { replace: true, state: { message: "Password changed. Sign in with your new password." } });
      window.location.reload();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };
  return <form className="formCard" onSubmit={(event) => void save(event)}>
    <h2>Change your password</h2>
    <p>You will be signed out on all devices and asked to sign in again.</p>
    <FormField label="Current password" name="current_password" type="password" required autoComplete="current-password" />
    <FormField label="New password" name="new_password" type="password" required minLength={8} autoComplete="new-password" />
    <FormField label="Confirm new password" name="confirm_password" type="password" required minLength={8} autoComplete="new-password" />
    <button disabled={busy}>{busy ? "Changing…" : "Change password"}</button>
    <FormError title="Could not change your password." message={error} />
  </form>;
}
