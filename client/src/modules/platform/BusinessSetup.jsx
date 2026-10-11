import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Check, Plus, Search, X } from "lucide-react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { ErrorState, Loading } from "../../components/States";
import { BackLink } from "../../components/navigation/BackLink";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import "./platform.css";
import { ChamaSetupFields, emptyChama, chamaPayload, chamaProblem } from "../chama/ChamaSetupFields";
import { COUNTRIES, CURRENCIES, allowedModules, findSector, moduleLabel, moduleProblem, searchSectors, timeZones, toggleModule, useBusinessProfiles } from "./businessSetupData";
import { MpesaPaymentsSetup } from "../settings/MpesaPaymentsSetup";

const STEP_LABELS = { business: "Your business", kind: "Kind of business", tools: "Tools & starter list", chama: "Your chama",
  place: "Location & contacts", money: "Opening money", review: "Review" };
const UNIT_LABELS = { FIXED: "each", PER_PAGE: "per page", PER_COPY: "per copy", PER_SHEET: "per sheet", PER_DOCUMENT: "per document", PER_HOUR: "per hour", PER_ITEM: "per item" };

// A guided set-up that adapts to how the business makes money and what kind it is. Every choice can be changed later in Settings.
export function BusinessSetupPage() {
  const { user, loading, refresh } = useAuth();
  const { catalogue, error: catalogueError } = useBusinessProfiles();
  if (loading || (!catalogue && !catalogueError)) return <Loading />;
  if (!user) return <Navigate to="/login?next=/onboarding" replace />;
  if (!catalogue) return <ErrorState message={catalogueError} retry={() => window.location.reload()} />;
  return <SetupWizard catalogue={catalogue} user={user} refresh={refresh} />;
}

// Progress is kept for this browser tab, so a reload or signing in again resumes where the owner stopped.
const draftKey = (user) => `business-setup-draft:${user.id}`;
function loadDraft(user) {
  try { return JSON.parse(window.sessionStorage.getItem(draftKey(user))) || {}; } catch { return {}; }
}
function saveDraft(user, draft) {
  try { window.sessionStorage.setItem(draftKey(user), JSON.stringify(draft)); } catch { /* Storage unavailable: the set-up still works, only without resuming. */ }
}
function clearDraft(user) {
  try { window.sessionStorage.removeItem(draftKey(user)); } catch { /* Nothing stored. */ }
}

function SetupWizard({ catalogue, user, refresh }) {
  const navigate = useNavigate();
  const [draft] = useState(() => loadDraft(user));
  const [step, setStep] = useState(draft.step ?? 0);
  const [name, setName] = useState(draft.name ?? "");
  const [model, setModel] = useState(draft.model ?? "");
  const [size, setSize] = useState(draft.size ?? "SMALL");
  const [sectorId, setSectorId] = useState(draft.sectorId ?? "");
  const [sectorQuery, setSectorQuery] = useState(draft.sectorQuery ?? "");
  const [otherText, setOtherText] = useState(draft.otherText ?? "");
  const [modules, setModules] = useState(() => new Set(draft.modules ?? []));
  const [modulesEdited, setModulesEdited] = useState(draft.modulesEdited ?? false);
  const [moduleNotes, setModuleNotes] = useState([]);
  const [categories, setCategories] = useState(draft.categories ?? []);
  const [newCategory, setNewCategory] = useState("");
  const [services, setServices] = useState(draft.services ?? []);
  const [details, setDetails] = useState(draft.details ?? { branch_name: "Main branch", phone: user.phone || "", email: user.email || "", address: "", country: "KE", currency: "KES", timezone: "Africa/Nairobi" });
  const [money, setMoney] = useState(draft.money ?? { opening_cash: "", opening_bank: "" });
  const [plan, setPlan] = useState(draft.plan ?? "BASIC");
  const [chama, setChama] = useState(() => draft.chama ?? emptyChama(user));
  const [plans, setPlans] = useState(null);
  useEffect(() => { api("/api/v1/tenancy/plans/").then((data) => setPlans(data.plans)).catch(() => setPlans([])); }, []);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState(null);
  const zones = useMemo(() => timeZones(), []);
  useEffect(() => {
    if (!created) saveDraft(user, { step, name, model, size, sectorId, sectorQuery, otherText, modules: [...modules], modulesEdited, categories, services, details, money, plan, chama });
  }, [user, created, step, name, model, size, sectorId, sectorQuery, otherText, modules, modulesEdited, categories, services, details, money, plan, chama]);
  const toDashboard = () => navigate("/admin/dashboard", { replace: true });
  // After the logo, a business that sells at a counter sets up M-Pesa prompts (or says it takes M-Pesa by hand).
  if (created && created.paymentsStep) return <PaymentsStep business={created} onDone={toDashboard} />;
  if (created) return <LogoStep business={created} onUploaded={refresh}
    onDone={() => (modules.has("pos") ? setCreated({ ...created, paymentsStep: true }) : toDashboard())} />;

  // The chama step appears only when chama management is one of the chosen tools.
  const steps = ["business", "kind", "tools", ...(modules.has("chama") ? ["chama"] : []), "place", "money", "review"];
  const current = steps[Math.min(step, steps.length - 1)];
  const goTo = (id) => setStep(steps.indexOf(id));
  const sector = sectorId ? findSector(catalogue, sectorId) : null;
  const isOther = catalogue.other_sectors.includes(sectorId);
  const allowed = model ? allowedModules(catalogue, model) : [];
  const typeLabel = isOther ? otherText.trim() : sector?.label || "";
  // Until the owner edits the tools themselves, they follow the kind of business and its size.
  const suggest = (nextSector, nextSize) => { if (!modulesEdited && nextSector) setModules(new Set(nextSector.modules[nextSize])); };
  const chooseModel = (id) => {
    if (id === model) return;
    setModel(id); setSectorId(""); setSectorQuery(""); setModules(new Set()); setModulesEdited(false); setModuleNotes([]);
  };
  const chooseSize = (id) => { setSize(id); suggest(sector, id); };
  const chooseSector = (item) => {
    setSectorId(item.id);
    suggest(item, size);
    setCategories(item.categories.map((label) => ({ label, on: true })));
    setServices(item.services.map((service) => ({ ...service, selling_price: "" })));
  };
  const chooseModule = (id) => {
    const result = toggleModule(catalogue, model, modules, id);
    setModules(result.modules);
    setModuleNotes(result.notes);
    setModulesEdited(true);
  };
  const addCategory = () => {
    const label = newCategory.trim();
    if (label && !categories.some((item) => item.label.toLowerCase() === label.toLowerCase())) setCategories([...categories, { label, on: true }]);
    setNewCategory("");
  };
  const setService = (index, changes) => setServices((rows) => rows.map((row, i) => (i === index ? { ...row, ...changes } : row)));
  const pricedServices = services.filter((service) => service.name.trim() && service.selling_price !== "");
  const chosenCategories = categories.filter((item) => item.on).map((item) => item.label);
  const setDetail = (field) => (event) => setDetails((current) => ({ ...current, [field]: event.target.value }));
  const setCountry = (event) => {
    const country = COUNTRIES.find((item) => item.code === event.target.value);
    setDetails((current) => ({ ...current, country: event.target.value, ...(country ? { currency: country.currency, timezone: country.timezone } : {}) }));
  };
  const problem = {
    business: () => !name.trim() ? "Enter your business name." : !model ? "Choose how your business makes money." : "",
    kind: () => !sectorId ? "Choose the kind of business you run." : isOther && !otherText.trim() ? "Name your kind of business." : "",
    tools: () => moduleProblem(catalogue, model, modules)
      || (services.some((service) => service.selling_price !== "" && Number(service.selling_price) < 0) ? "Service prices cannot be negative." : ""),
    chama: () => chamaProblem(chama),
    place: () => !details.branch_name.trim() ? "Enter the name of your first branch or shop." : "",
    money: () => [money.opening_cash, money.opening_bank].some((value) => value !== "" && Number(value) < 0) ? "Opening amounts cannot be negative." : "",
    review: () => "",
  }[current]();
  const next = () => {
    if (problem) { setError({ title: "Before you continue", text: problem }); return; }
    setError(null);
    setStep(step + 1);
    window.scrollTo?.({ top: 0 });
  };
  const create = async () => {
    setBusy(true); setError(null);
    try {
      const business = await api("/api/v1/tenancy/create/", { method: "POST", body: JSON.stringify({
        name: name.trim(), business_model: model, sector: sectorId, business_size: size, business_type: typeLabel.slice(0, 100), plan,
        enabled_modules: [...modules],
        starter_categories: modules.has("inventory") ? chosenCategories : [],
        starter_services: modules.has("services") ? pricedServices.map(({ name: serviceName, selling_price, billing_unit, requires_job }) =>
          ({ name: serviceName.trim(), selling_price, billing_unit, requires_job })) : [],
        ...details, opening_cash: money.opening_cash || 0, opening_bank: money.opening_bank || 0,
        chama: modules.has("chama") ? chamaPayload(chama) : null,
      }) });
      clearDraft(user);
      // Load the new business into the session before the logo step, so leaving it opens that business's dashboard.
      await refresh().catch(() => {});  // the business exists either way; the dashboard loads it again
      setCreated(business);
    } catch (e) {
      setError({ title: "Could not create the business.", text: e.message });
    } finally {
      setBusy(false);
    }
  };
  const country = COUNTRIES.find((item) => item.code === details.country);
  const basicModules = plans?.find((item) => item.code === "BASIC")?.enabled_modules;
  const proOnly = (id) => Boolean(basicModules && !basicModules.includes(id));
  const lockedOnBasic = !user.platform_admin && plan === "BASIC" ? [...modules].filter(proOnly) : [];
  const modelLabel = catalogue.models.find((item) => item.id === model)?.label;
  // "Other" stays in view whatever the search, so a business that is not listed can always create its own kind.
  const otherSector = model ? catalogue.sectors[model].find((item) => catalogue.other_sectors.includes(item.id)) : null;
  const matches = model ? searchSectors(catalogue.sectors[model], sectorQuery) : [];
  const sectors = otherSector && !matches.includes(otherSector) ? [...matches, otherSector] : matches;
  const createOwnKind = () => { chooseSector(otherSector); setOtherText(sectorQuery.trim().slice(0, 100)); };

  return <main className="tenantForm businessSetup">
    <BackLink className="authBackButton" />
    <span className="eyebrow">Set up your business</span>
    <h1>{STEP_LABELS[current]}</h1>
    <ol className="setupSteps" aria-label="Set-up progress">
      {steps.map((id) => STEP_LABELS[id]).map((label, index) => <li key={label} className={index === step ? "current" : index < step ? "done" : ""} aria-current={index === step ? "step" : undefined}>
        <span>{index < step ? <Check size={14} aria-hidden="true" /> : index + 1}</span>{label}
      </li>)}
    </ol>

    {current === "business" && <section className="setupPanel">
      <label>Business name<input value={name} onChange={(e) => setName(e.target.value)} maxLength={160} placeholder="e.g. Fresh Cuts Barbershop" autoFocus /></label>
      <fieldset className="choiceGroup">
        <legend>How does your business make money?</legend>
        <div className="choiceGrid wideChoices">
          {catalogue.models.map((item) => <button type="button" key={item.id} className={`choiceCard${model === item.id ? " selected" : ""}`}
            aria-pressed={model === item.id} onClick={() => chooseModel(item.id)}>
            <strong>{item.label}</strong><span>{item.hint}</span>
          </button>)}
        </div>
      </fieldset>
      <fieldset className="choiceGroup">
        <legend>How many people work in the business?</legend>
        <div className="choiceGrid">
          {catalogue.sizes.map((item) => <button type="button" key={item.id} className={`choiceCard compact${size === item.id ? " selected" : ""}`}
            aria-pressed={size === item.id} onClick={() => chooseSize(item.id)}>
            <strong>{item.label}</strong><span>{item.hint}</span>
          </button>)}
        </div>
      </fieldset>
      <p className="muted">Built for small and medium businesses. Support for large companies and supermarkets is coming later.</p>
    </section>}

    {current === "kind" && <section className="setupPanel">
      <p className="muted">You chose <strong>{modelLabel}</strong>. Which of these is closest to your business?</p>
      <label className="sectorSearch"><Search size={16} aria-hidden="true" /><span className="sr">Search kinds of business</span>
        <input type="search" value={sectorQuery} onChange={(e) => setSectorQuery(e.target.value)} placeholder="Search, e.g. kinyozi, fundi simu, mitumba" />
      </label>
      <fieldset className="choiceGroup">
        <legend className="sr">Kind of business</legend>
        <div className="choiceGrid">
          {sectors.map((item) => <button type="button" key={item.id} className={`choiceCard${sectorId === item.id ? " selected" : ""}`}
            aria-pressed={sectorId === item.id} onClick={() => chooseSector(item)}>
            <strong>{item.label}</strong><span>{item.hint}</span>
          </button>)}
        </div>
        {sectorQuery.trim() && !matches.length && <p className="muted">“{sectorQuery.trim()}” is not listed yet.{" "}
          <button type="button" className="linkButton" onClick={createOwnKind}>Create “{sectorQuery.trim()}” as my kind of business</button></p>}
      </fieldset>
      {isOther && <>
        <label>Name your kind of business<input value={otherText} onChange={(e) => setOtherText(e.target.value)} maxLength={100} placeholder="e.g. Poultry farm, Car hire, Music studio" /></label>
        <p className="muted">You start with the usual tools for a business that {catalogue.models.find((item) => item.id === model)?.phrase}, and choose your own on the next step.
          Once reviewed, your kind of business is added to this list so others like you find it.</p>
      </>}
      {model !== "MIXED" && <p className="muted">Doing more than this? Go back and choose <strong>Both goods and services</strong>.</p>}
    </section>}

    {current === "tools" && <section className="setupPanel">
      <p className="muted">We picked the usual tools for a <strong>{typeLabel || "business like yours"}</strong>. Turn any on or off; you can change them later in Settings.</p>
      <fieldset className="choiceGroup">
        <legend>Tools</legend>
        <div className="choiceGrid">
          {catalogue.modules.filter((module) => allowed.includes(module.id)).map((module) => <button type="button" key={module.id}
            className={`choiceCard module${modules.has(module.id) ? " selected" : ""}`} aria-pressed={modules.has(module.id)} onClick={() => chooseModule(module.id)}>
            <strong>{module.label}</strong><span>{module.description}</span>
            {proOnly(module.id) && <small className="proTag">Pro plan</small>}
            {module.needs.length > 0 && <small>Works with {module.needs.filter((need) => allowed.includes(need)).map((need) => moduleLabel(catalogue, need)).join(" or ")}</small>}
          </button>)}
        </div>
      </fieldset>
      {moduleNotes.length > 0 && <FormSuccess message={moduleNotes.join(" ")} />}

      {modules.has("services") && <fieldset className="choiceGroup starterList">
        <legend>Your service price list <small>Leave a price blank to skip that service.</small></legend>
        {services.map((service, index) => <div className="starterService" key={index}>
          <label><span className="sr">Service name</span><input value={service.name} onChange={(e) => setService(index, { name: e.target.value })} maxLength={180} placeholder="Service name" /></label>
          <label><span className="sr">Price for {service.name || "this service"}</span>
            <input type="number" min="0" step="0.01" inputMode="decimal" value={service.selling_price} onChange={(e) => setService(index, { selling_price: e.target.value })} placeholder={`${details.currency} ${UNIT_LABELS[service.billing_unit] || ""}`} />
          </label>
          <button type="button" className="iconButton" aria-label={`Remove ${service.name || "service"}`} onClick={() => setServices(services.filter((_, i) => i !== index))}><X size={16} aria-hidden="true" /></button>
        </div>)}
        <button type="button" className="secondary addRow" onClick={() => setServices([...services, { name: "", selling_price: "", billing_unit: "FIXED", requires_job: false }])}><Plus size={16} aria-hidden="true" /> Add a service</button>
      </fieldset>}

      {modules.has("inventory") && <fieldset className="choiceGroup starterList">
        <legend>Product categories <small>Groups for the things you sell.</small></legend>
        <div className="chipList">
          {categories.map((item, index) => <button type="button" key={item.label} className={`chip${item.on ? " selected" : ""}`} aria-pressed={item.on}
            onClick={() => setCategories(categories.map((row, i) => (i === index ? { ...row, on: !row.on } : row)))}>{item.label}</button>)}
        </div>
        <div className="starterService">
          <label><span className="sr">New category</span><input value={newCategory} onChange={(e) => setNewCategory(e.target.value)} maxLength={120} placeholder="Add a category"
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCategory(); } }} /></label>
          <button type="button" className="secondary" onClick={addCategory}>Add</button>
        </div>
      </fieldset>}
    </section>}

    {current === "chama" && <section className="setupPanel">
      <p className="muted">Set up the chama you run. You can add members, change leaders and turns, and set up more chamas later from the dashboard.</p>
      <ChamaSetupFields value={chama} onChange={setChama} />
    </section>}

    {current === "place" && <section className="setupPanel setupGrid">
      <label className="wide">First branch or shop name<input value={details.branch_name} onChange={setDetail("branch_name")} maxLength={160} /></label>
      <label>Phone<input value={details.phone} onChange={setDetail("phone")} type="tel" maxLength={40} placeholder="0712 345 678" /></label>
      <label>Email<input value={details.email} onChange={setDetail("email")} type="email" placeholder="hello@yourbusiness.com" /></label>
      <label className="wide">Address or location<input value={details.address} onChange={setDetail("address")} maxLength={500} placeholder="Street, market or town" /></label>
      <label>Country<select value={country ? details.country : "OTHER"} onChange={setCountry}>
        {COUNTRIES.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
        <option value="OTHER">Another country…</option>
      </select></label>
      {!country && <label>Country code<input value={details.country === "OTHER" ? "" : details.country} onChange={(e) => setDetails((c) => ({ ...c, country: e.target.value.toUpperCase().slice(0, 2) }))} placeholder="Two letters, e.g. FR" /></label>}
      <label>Currency<select value={CURRENCIES.includes(details.currency) ? details.currency : "OTHER"} onChange={(e) => setDetails((c) => ({ ...c, currency: e.target.value === "OTHER" ? "" : e.target.value }))}>
        {CURRENCIES.map((code) => <option key={code} value={code}>{code}</option>)}
        <option value="OTHER">Another currency…</option>
      </select></label>
      {!CURRENCIES.includes(details.currency) && <label>Currency code<input value={details.currency} onChange={(e) => setDetails((c) => ({ ...c, currency: e.target.value.toUpperCase().slice(0, 3) }))} placeholder="Three letters, e.g. EUR" /></label>}
      <label>Time zone<select value={details.timezone} onChange={setDetail("timezone")}>
        {zones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")}</option>)}
      </select></label>
      <p className="muted wide">The currency is fixed once you start recording money, so past records stay correct.</p>
    </section>}

    {current === "money" && <section className="setupPanel setupGrid">
      <p className="muted wide">Enter only money your business already holds today. Leave blank if unsure; an accountant can add verified opening balances later.</p>
      <label>Cash in the till ({details.currency || "—"})<input type="number" min="0" step="0.01" value={money.opening_cash} onChange={(e) => setMoney((m) => ({ ...m, opening_cash: e.target.value }))} placeholder="0" /></label>
      <label>Bank balance ({details.currency || "—"})<input type="number" min="0" step="0.01" value={money.opening_bank} onChange={(e) => setMoney((m) => ({ ...m, opening_bank: e.target.value }))} placeholder="0" /></label>
    </section>}

    {current === "review" && <section className="setupPanel">
      <dl className="setupReview">
        <div><dt>Business</dt><dd>{name} · {catalogue.sizes.find((item) => item.id === size)?.label}</dd><button type="button" className="linkButton" onClick={() => goTo("business")}>Change</button></div>
        <div><dt>What it does</dt><dd>{typeLabel} · {modelLabel}</dd><button type="button" className="linkButton" onClick={() => goTo("kind")}>Change</button></div>
        <div><dt>Tools</dt><dd>{catalogue.modules.filter((m) => modules.has(m.id)).map((m) => m.label).join(", ")}</dd><button type="button" className="linkButton" onClick={() => goTo("tools")}>Change</button></div>
        {modules.has("services") && <div><dt>Services</dt><dd>{pricedServices.map((s) => `${s.name.trim()} ${details.currency} ${s.selling_price}`).join(", ") || "None yet; add them later"}</dd><button type="button" className="linkButton" onClick={() => goTo("tools")}>Change</button></div>}
        {modules.has("inventory") && <div><dt>Categories</dt><dd>{chosenCategories.join(", ") || "None yet; add them later"}</dd><button type="button" className="linkButton" onClick={() => goTo("tools")}>Change</button></div>}
        {modules.has("chama") && <div><dt>Chama</dt><dd>{chama.name} · {details.currency} {Number(chama.contribution_amount || 0).toLocaleString()} each · {chamaPayload(chama).members.length} members · treasurer {chama.members.find((m) => m.role === "TREASURER")?.full_name || "—"}</dd><button type="button" className="linkButton" onClick={() => goTo("chama")}>Change</button></div>}
        <div><dt>First branch</dt><dd>{details.branch_name}{details.address ? ` · ${details.address}` : ""}</dd><button type="button" className="linkButton" onClick={() => goTo("place")}>Change</button></div>
        <div><dt>Contacts</dt><dd>{[details.phone, details.email].filter(Boolean).join(" · ") || "None yet"}</dd><button type="button" className="linkButton" onClick={() => goTo("place")}>Change</button></div>
        <div><dt>Country & money</dt><dd>{country?.name || details.country} · {details.currency} · {details.timezone.replaceAll("_", " ")}</dd><button type="button" className="linkButton" onClick={() => goTo("place")}>Change</button></div>
        <div><dt>Opening money</dt><dd>{Number(money.opening_cash || 0) || Number(money.opening_bank || 0) ? `Cash ${money.opening_cash || 0} · Bank ${money.opening_bank || 0}` : "None"}</dd><button type="button" className="linkButton" onClick={() => goTo("money")}>Change</button></div>
      </dl>
      {user.platform_admin && <p className="muted">As the platform administrator, your business gets every Pro feature for free, with no expiry.</p>}
      {!user.platform_admin && <fieldset className="choiceGroup">
        <legend>Choose your plan <small>The first month is free. You pay only when you continue after it.</small></legend>
        <div className="choiceGrid wideChoices">
          {(plans || []).map((item) => <button type="button" key={item.code} className={`choiceCard${plan === item.code ? " selected" : ""}`}
            aria-pressed={plan === item.code} onClick={() => setPlan(item.code)}>
            <strong>{item.name} · {item.currency} {Number(item.price).toLocaleString()} / month</strong><span>{item.description}</span>
          </button>)}
        </div>
        {lockedOnBasic.length > 0 && <p className="muted">On Basic, {lockedOnBasic.map((id) => moduleLabel(catalogue, id)).join(", ")} stay locked until you upgrade to Pro.</p>}
        {plans?.length === 0 && <p className="muted">Plans could not be loaded. You start on Basic and can change it on the Subscription page.</p>}
      </fieldset>}
    </section>}

    <div className="setupActions">
      {step > 0 && <button type="button" className="secondary" onClick={() => { setError(null); setStep(step - 1); }} disabled={busy}>Back</button>}
      {step < steps.length - 1 ? <button type="button" onClick={next}>Continue</button>
        : <button type="button" onClick={() => void create()} disabled={busy}>{busy ? "Creating business…" : "Create business workspace"}</button>}
    </div>
    {error && <FormError title={error.title} message={error.text} />}
    {!!user.memberships?.length && <Link to="/select-business">Use an existing business instead</Link>}
  </main>;
}

function PaymentsStep({ business, onDone }) {
  return <main className="tenantForm businessSetup">
    <span className="eyebrow">{business.name} is ready</span>
    <h1>M-Pesa payments</h1>
    <MpesaPaymentsSetup />
    <div className="setupActions">
      <button type="button" onClick={onDone}>Go to my dashboard</button>
    </div>
    <p className="muted">You can set this up or change it later in Settings → M-Pesa payments.</p>
  </main>;
}

function LogoStep({ business, onUploaded, onDone }) {
  const [busy, setBusy] = useState(false);
  const [logo, setLogo] = useState("");
  const [error, setError] = useState("");
  const upload = async (event) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    const body = new FormData();
    body.append("logo", file);
    setBusy(true); setError("");
    try {
      const organization = await api("/api/v1/tenancy/settings/logo/", { method: "POST", body });
      setLogo(organization.logo_url);
      await onUploaded();  // The header shows the new logo as soon as the dashboard opens.
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return <main className="tenantForm businessSetup">
    <span className="eyebrow">{business.name} is ready</span>
    <h1>Add your logo</h1>
    <p className="muted">Your logo appears in your dashboard and on the receipts your customers receive. A plain background is removed automatically. You can also do this later in Settings.</p>
    <div className="businessLogoPreview setupLogo">{logo ? <img src={logo} alt={`${business.name} logo`} /> : <span className="muted">No logo yet</span>}</div>
    <div className="setupActions">
      <label className={`button${busy ? " disabled" : ""}`}>{busy ? "Uploading…" : logo ? "Choose a different logo" : "Upload logo"}
        <input type="file" accept="image/png,image/jpeg,image/webp" className="sr" onChange={(e) => void upload(e)} disabled={busy} />
      </label>
      <button type="button" className={logo ? "" : "secondary"} onClick={onDone} disabled={busy}>{logo ? "Continue" : "Skip for now"}</button>
    </div>
    {error && <FormError title="Could not save the logo." message={error} />}
  </main>;
}
