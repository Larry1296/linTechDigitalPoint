import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Check, Plus, Sparkles, X } from "lucide-react";
import { api, apiUrl } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { ErrorState, Loading } from "../../components/States";
import { BackLink } from "../../components/navigation/BackLink";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import "./platform.css";
import { ChamaSetupFields, emptyChama, chamaPayload, chamaProblem } from "../chama/ChamaSetupFields";
import { COUNTRIES, CURRENCIES, moduleLabel, planFor, setupProblem, suggestFor, timeZones, toggleModule, useBusinessProfiles } from "./businessSetupData";
import { MpesaPaymentsSetup } from "../settings/MpesaPaymentsSetup";
import { BusinessPartsChoice, MONEY_MODES, MONEY_PARTS, STRUCTURES, defaultPartName } from "../../core/organization/MoneyModeChoice";
import { TextBox } from "../../components/forms/TextBox";

const STEP_LABELS = { business: "Your business", does: "What it does", lists: "Your starter list", plan: "Your plan", chama: "Your chama",
  place: "Location & money", review: "Review" };
// The priced starter lists, by the tool that uses them; a menu item or a kind of room is told apart by its unit.
const PRICE_LISTS = [
  { module: "services", title: "Your services and prices", one: "service", nameLabel: "Service name", add: "Add a service", unit: "FIXED" },
  { module: "menu", title: "Your menu", one: "dish", nameLabel: "Dish or drink", add: "Add to the menu", unit: "MENU" },
  { module: "rooms", title: "Your kinds of room, priced a night", one: "room", nameLabel: "Kind of room", add: "Add a kind of room", unit: "PER_NIGHT" },
];
const kindOf = (service) => (service.billing_unit === "MENU" ? "menu" : service.billing_unit === "PER_NIGHT" ? "rooms" : "services");
const UNIT_LABELS = { FIXED: "each", PER_PAGE: "per page", PER_COPY: "per copy", PER_SHEET: "per sheet", PER_DOCUMENT: "per document", PER_HOUR: "per hour", PER_ITEM: "per item", PER_KG: "per kg", PER_NIGHT: "a night", MENU: "each" };
const LIST_TOOLS = ["inventory", "services", "menu", "rooms"];

// Set-up for any business, in the owner's own words: they name it, describe what it does, and tick what it does and the
// tools to run it. Nothing is picked from a list of kinds of business; the description only suggests ticks and a
// starter list, which the owner changes freely. Every choice can be changed later in Settings.
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
  const [description, setDescription] = useState(draft.description ?? "");
  const [businessType, setBusinessType] = useState(draft.businessType ?? "");
  const [size, setSize] = useState(draft.size ?? "SMALL");
  const [modules, setModules] = useState(() => new Set(draft.modules ?? []));
  // What the description last suggested: the closest kinds (shown as a hint) and the template the starter list came from.
  const [suggestion, setSuggestion] = useState(draft.suggestion ?? null);
  const [suggestedFor, setSuggestedFor] = useState(draft.suggestedFor ?? "");
  const [modulesEdited, setModulesEdited] = useState(draft.modulesEdited ?? false);
  const [moduleNotes, setModuleNotes] = useState([]);
  const [categories, setCategories] = useState(draft.categories ?? []);
  const [newCategory, setNewCategory] = useState("");
  const [services, setServices] = useState(draft.services ?? []);
  const [details, setDetails] = useState(draft.details ?? { branch_name: "Main branch", phone: user.phone || "", email: user.email || "", address: "", country: "KE", currency: "KES", timezone: "Africa/Nairobi" });
  // structure stays unset until the owner answers whether the business is one business or several under one name.
  const [money, setMoney] = useState({ opening_cash: "", opening_bank: "", money_mode: "ONE_DRAWER", structure: "", part_names: {}, ...draft.money });
  const [plan, setPlan] = useState(draft.plan ?? "");
  const [planChosen, setPlanChosen] = useState(draft.planChosen ?? false);
  const [chama, setChama] = useState(() => draft.chama ?? emptyChama(user));
  const [plans, setPlans] = useState(null);
  useEffect(() => { api("/api/v1/tenancy/plans/").then((data) => setPlans(data.plans)).catch(() => setPlans([])); }, []);
  const template = suggestion?.template || "";
  // What the chosen plan costs a business like this one (a price can differ by kind of business).
  const [kindPrice, setKindPrice] = useState(null);
  useEffect(() => {
    setKindPrice(null);
    if (!template || !plan || user.platform_admin) return;
    api(`/api/v1/tenancy/plans/?sector=${encodeURIComponent(template)}`)
      .then((data) => setKindPrice(data.plans.find((item) => item.code === plan) || null)).catch(() => {});
  }, [template, plan, user.platform_admin]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [created, setCreated] = useState(null);
  const typeEdited = useRef(Boolean(draft.businessType));
  const zones = useMemo(() => timeZones(), []);
  useEffect(() => {
    if (!created) saveDraft(user, { step, name, description, businessType, size, modules: [...modules], suggestion, suggestedFor, modulesEdited,
      categories, services, details, money, plan, planChosen, chama });
  }, [user, created, step, name, description, businessType, size, modules, suggestion, suggestedFor, modulesEdited, categories, services, details, money, plan, planChosen, chama]);
  const toDashboard = () => navigate("/admin/dashboard", { replace: true });
  // After the logo, a business that sells at a counter sets up M-Pesa prompts (or says it takes M-Pesa by hand).
  if (created && created.paymentsStep) return <PaymentsStep business={created} onDone={toDashboard} />;
  if (created) return <LogoStep business={created} onUploaded={refresh}
    onDone={() => (modules.has("pos") ? setCreated({ ...created, paymentsStep: true }) : toDashboard())} />;

  const chosen = modules;
  const recommended = planFor(plans, chosen);
  // Until the owner picks a plan, the first one with every chosen tool is the one shown as chosen.
  const planCode = user.platform_admin ? "" : (planChosen && plans?.some((item) => item.code === plan) ? plan : recommended?.code || plans?.[0]?.code || "");
  const currentPlan = plans?.find((item) => item.code === planCode);
  const hasLists = LIST_TOOLS.some((id) => chosen.has(id));
  const steps = ["business", "does", ...(hasLists ? ["lists"] : []), ...(user.platform_admin ? [] : ["plan"]), ...(chosen.has("chama") ? ["chama"] : []), "place", "review"];
  const current = steps[Math.min(step, steps.length - 1)];
  const goTo = (id) => setStep(steps.indexOf(id));
  const activityIds = catalogue.activities.map((activity) => activity.id);
  const moduleById = Object.fromEntries(catalogue.modules.map((module) => [module.id, module]));
  const chooseModule = (id) => {
    const result = toggleModule(catalogue, "MIXED", modules, id);
    setModules(result.modules);
    setModuleNotes(result.notes);
    setModulesEdited(true);
  };
  // The description suggests ticks and a starter list once, and again when it changes, until the owner ticks themselves.
  const applySuggestion = async () => {
    const text = description.trim();
    if (!text || `${text}|${size}` === suggestedFor) return;
    setThinking(true);
    try {
      const found = await suggestFor(text, size);
      setSuggestion(found);
      setSuggestedFor(`${text}|${size}`);
      if (!modulesEdited) setModules(new Set(found.modules));
      if (!typeEdited.current && found.business_type) setBusinessType(found.business_type);
      setCategories((rows) => [...rows.filter((row) => row.own), ...found.categories.filter((label) => !rows.some((row) => row.own && row.label === label)).map((label) => ({ label, on: true }))]);
      setServices((rows) => [...rows.filter((row) => row.own), ...found.services.map((service) => ({ ...service, selling_price: "" }))]);
    } catch { /* A suggestion is only a help: the owner ticks what the business does themselves. */ }
    finally { setThinking(false); }
  };
  const addCategory = () => {
    const label = newCategory.trim();
    if (label && !categories.some((item) => item.label.toLowerCase() === label.toLowerCase())) setCategories([...categories, { label, on: true, own: true }]);
    setNewCategory("");
  };
  const setService = (index, changes) => setServices((rows) => rows.map((row, i) => (i === index ? { ...row, ...changes, own: true } : row)));
  const pricedServices = services.filter((service) => service.name.trim() && service.selling_price !== "");
  const chosenCategories = categories.filter((item) => item.on).map((item) => item.label);
  const setDetail = (field) => (event) => setDetails((current) => ({ ...current, [field]: event.target.value }));
  const setCountry = (event) => {
    const country = COUNTRIES.find((item) => item.code === event.target.value);
    setDetails((current) => ({ ...current, country: event.target.value, ...(country ? { currency: country.currency, timezone: country.timezone } : {}) }));
  };
  // The parts of the business that take money of their own (shop, services, M-Pesa agency): with more than one, the
  // owner chooses whether it is one business or several under one name, names each part and says how its cash is kept.
  const earningParts = MONEY_PARTS.filter((part) => part.modules.some((module) => chosen.has(module)));
  const withParts = earningParts.length > 1 && money.structure === "PARTS";
  const partName = (key) => money.part_names[key]?.trim() || defaultPartName(key, template);
  const missingFromPlan = currentPlan ? [...chosen].filter((id) => !currentPlan.enabled_modules.includes(id)) : [];
  const problem = {
    business: () => !name.trim() ? "Enter your business name." : "",
    does: () => !businessType.trim() ? "Say what you call your kind of business, in your own words." : setupProblem(catalogue, chosen),
    lists: () => services.some((service) => service.selling_price !== "" && Number(service.selling_price) < 0) ? "Prices cannot be negative." : "",
    plan: () => !plans ? "The plans are still loading." : !currentPlan ? "Choose a plan." : missingFromPlan.length
      ? `${missingFromPlan.map((id) => moduleLabel(catalogue, id)).join(", ")} ${missingFromPlan.length === 1 ? "is" : "are"} not in ${currentPlan.name}. Choose ${recommended?.name || "another plan"}, or go back and leave ${missingFromPlan.length === 1 ? "it" : "them"} off.` : "",
    chama: () => chamaProblem(chama),
    place: () => !details.branch_name.trim() ? "Enter the name of your first branch or shop."
      : [money.opening_cash, money.opening_bank].some((value) => value !== "" && Number(value) < 0) ? "Opening amounts cannot be negative."
      : earningParts.length > 1 && !money.structure ? "Say whether this is one business or several businesses under one name." : "",
    review: () => "",
  }[current]();
  const next = async () => {
    if (problem) { setError({ title: "Before you continue", text: problem }); return; }
    setError(null);
    if (current === "business") await applySuggestion();
    setStep(step + 1);
    window.scrollTo?.({ top: 0 });
  };
  const create = async () => {
    setBusy(true); setError(null);
    try {
      const business = await api("/api/v1/tenancy/create/", { method: "POST", body: JSON.stringify({
        name: name.trim(), description: description.trim(), business_type: businessType.trim().slice(0, 100), sector: template, business_size: size,
        ...(planCode ? { plan: planCode } : {}), enabled_modules: [...chosen],
        starter_categories: chosen.has("inventory") ? chosenCategories : [],
        starter_services: pricedServices.filter((service) => chosen.has(kindOf(service))).map(({ name: serviceName, selling_price, billing_unit, requires_job }) =>
          ({ name: serviceName.trim(), selling_price, billing_unit, requires_job: Boolean(requires_job) })),
        ...details, opening_cash: money.opening_cash || 0, opening_bank: money.opening_bank || 0,
        ...(withParts ? { structure: "PARTS", money_mode: money.money_mode, part_names: Object.fromEntries(earningParts.map((part) => [part.key, money.part_names[part.key]?.trim() || ""])) }
          : { structure: "SINGLE", money_mode: "ONE_DRAWER" }),
        chama: chosen.has("chama") ? chamaPayload(chama) : null,
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
  const priceText = (item) => `${item.prices_vary ? "from " : ""}${item.currency} ${Number(item.prices_vary ? item.price_from : item.price).toLocaleString()} / ${item.period_days === 30 ? "month" : `${item.period_days} days`}`;
  const toolCard = (id, label = moduleById[id]?.label, hint = moduleById[id]?.description) => <button type="button" key={id}
    className={`choiceCard module${chosen.has(id) ? " selected" : ""}`} aria-pressed={chosen.has(id)} onClick={() => chooseModule(id)}>
    <strong>{label}</strong>{hint && <span>{hint}</span>}
  </button>;

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
      <label>Business name<TextBox value={name} onChange={(e) => setName(e.target.value)} maxLength={160} placeholder="e.g. Fresh Cuts Barbershop" autoFocus /></label>
      <label>Describe your business in your own words
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} rows={4}
          placeholder="What you sell or do, for whom, and anything else you run alongside it. e.g. “A cyber with printing and typing, we sell phone accessories and run an M-Pesa agency.”" />
      </label>
      <p className="muted">Any business can be set up here. From your description we tick the usual tools and suggest a starter list; you change anything on the next steps.</p>
      <fieldset className="choiceGroup">
        <legend>How many people work in the business?</legend>
        <div className="choiceGrid">
          {catalogue.sizes.map((item) => <button type="button" key={item.id} className={`choiceCard compact${size === item.id ? " selected" : ""}`}
            aria-pressed={size === item.id} onClick={() => setSize(item.id)}>
            <strong>{item.label}</strong><span>{item.hint}</span>
          </button>)}
        </div>
      </fieldset>
    </section>}

    {current === "does" && <section className="setupPanel">
      {suggestion?.matches?.length > 0 && !modulesEdited && <p className="setupHint" role="status"><Sparkles size={16} aria-hidden="true" /> We ticked what businesses like
        {" "}{suggestion.matches.map((match) => match.label).join(", ").replace(/, ([^,]*)$/, " and $1")} usually use. Change anything that is not how you work.</p>}
      <label>What do you call your kind of business?<TextBox value={businessType} maxLength={100} placeholder="e.g. Car hire, Poultry farm, Cyber & M-Pesa shop"
        onChange={(e) => { typeEdited.current = true; setBusinessType(e.target.value); }} /></label>
      <fieldset className="choiceGroup">
        <legend>What does your business do to earn money? <small>Tick all that apply.</small></legend>
        <div className="choiceGrid">{catalogue.activities.map((activity) => toolCard(activity.id, activity.label, moduleById[activity.id]?.description))}</div>
      </fieldset>
      <fieldset className="choiceGroup">
        <legend>Tools to run it</legend>
        <div className="choiceGrid">{catalogue.running.map((id) => toolCard(id))}</div>
      </fieldset>
      <fieldset className="choiceGroup">
        <legend>Anything else you look after? <small>Kept apart from the business's own money.</small></legend>
        <div className="choiceGrid">{catalogue.also.map((id) => toolCard(id))}</div>
      </fieldset>
      {moduleNotes.length > 0 && <FormSuccess message={moduleNotes.join(" ")} />}
      {thinking && <p className="muted">Reading your description…</p>}
    </section>}

    {current === "lists" && <section className="setupPanel">
      <p className="muted">Start with what you sell so the first sale can happen straight away. Remove what you do not offer and add your own; you can add more later.</p>
      {/* One starter list, shown in up to three parts: services, a menu and kinds of room, each priced. */}
      {PRICE_LISTS.filter((list) => chosen.has(list.module)).map((list) => <fieldset className="choiceGroup starterList" key={list.module}>
        <legend>{list.title} <small>Leave a price blank to skip {list.one === "service" ? "that service" : `that ${list.one}`}.</small></legend>
        {services.map((service, index) => kindOf(service) === list.module && <div className="starterService" key={index}>
          <label><span className="sr">{list.nameLabel}</span><TextBox value={service.name} onChange={(e) => setService(index, { name: e.target.value })} maxLength={180} placeholder={list.nameLabel} /></label>
          <label><span className="sr">Price for {service.name || `this ${list.one}`}</span>
            <input type="number" min="0" step="0.01" inputMode="decimal" value={service.selling_price} onChange={(e) => setService(index, { selling_price: e.target.value })} placeholder={`${details.currency} ${UNIT_LABELS[service.billing_unit] || ""}`} />
          </label>
          <button type="button" className="iconButton" aria-label={`Remove ${service.name || list.one}`} onClick={() => setServices(services.filter((_, i) => i !== index))}><X size={16} aria-hidden="true" /></button>
        </div>)}
        <button type="button" className="secondary addRow" onClick={() => setServices([...services, { name: "", selling_price: "", billing_unit: list.unit, requires_job: false, own: true }])}><Plus size={16} aria-hidden="true" /> {list.add}</button>
      </fieldset>)}

      {chosen.has("inventory") && <fieldset className="choiceGroup starterList">
        <legend>Product categories <small>Groups for the things you sell.</small></legend>
        {categories.length > 0 && <div className="chipList">
          {categories.map((item, index) => <button type="button" key={item.label} className={`chip${item.on ? " selected" : ""}`} aria-pressed={item.on}
            onClick={() => setCategories(categories.map((row, i) => (i === index ? { ...row, on: !row.on } : row)))}>{item.label}</button>)}
        </div>}
        <div className="starterService">
          <label><span className="sr">New category</span><TextBox value={newCategory} onChange={(e) => setNewCategory(e.target.value)} maxLength={120} placeholder="Add a category"
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCategory(); } }} /></label>
          <button type="button" className="secondary" onClick={addCategory}>Add</button>
        </div>
      </fieldset>}
    </section>}

    {current === "plan" && <section className="setupPanel">
      <fieldset className="choiceGroup">
        <legend>Choose your plan <small>The first month is free. You pay only when you continue after it.</small></legend>
        {recommended && <p className="muted"><strong>{recommended.name}</strong> is the first plan with everything you ticked.</p>}
        {!recommended && plans?.length > 0 && <p className="muted">No single plan has every tool you ticked. Choose a plan, then go back and leave off what it does not include.</p>}
        <div className="choiceGrid wideChoices">
          {(plans || []).map((item) => {
            const lacks = [...chosen].filter((id) => !item.enabled_modules.includes(id));
            return <button type="button" key={item.code} className={`choiceCard${planCode === item.code ? " selected" : ""}${item.highlighted ? " recommendedPlan" : ""}`}
              aria-pressed={planCode === item.code} onClick={() => { setPlan(item.code); setPlanChosen(true); }}>
              <strong>{item.name} · {priceText(item)}</strong>
              {item.description && <span>{item.description}</span>}
              <span className="planTools">{lacks.length ? `Does not include: ${lacks.map((id) => moduleLabel(catalogue, id)).join(", ")}` : "Has everything you ticked"}</span>
              {(item.user_limit || item.branch_limit) && <small>{[item.user_limit && `Up to ${item.user_limit} people`, item.branch_limit && `${item.branch_limit} ${item.branch_limit === 1 ? "branch" : "branches"}`].filter(Boolean).join(" · ")}</small>}
            </button>;
          })}
        </div>
        {plans === null && <p className="muted">Loading plans…</p>}
        {plans?.length === 0 && <p className="muted">Plans could not be loaded. Go back and try again in a moment.</p>}
        <p className="muted">You can switch plan when you pay for the next period.</p>
      </fieldset>
    </section>}

    {current === "chama" && <section className="setupPanel">
      <p className="muted">Set up the chama you run. You can add members, change leaders and turns, and set up more chamas later from the dashboard.</p>
      <ChamaSetupFields value={chama} onChange={setChama} />
    </section>}

    {current === "place" && <section className="setupPanel setupGrid">
      <label className="wide">First branch or shop name<TextBox value={details.branch_name} onChange={setDetail("branch_name")} maxLength={160} /></label>
      <label>Phone<input value={details.phone} onChange={setDetail("phone")} type="tel" maxLength={40} placeholder="0712 345 678" /></label>
      <label>Email<input value={details.email} onChange={setDetail("email")} type="email" placeholder="hello@yourbusiness.com" /></label>
      <label className="wide">Address or location<TextBox value={details.address} onChange={setDetail("address")} maxLength={500} placeholder="Street, market or town" /></label>
      <label>Country<select value={country ? details.country : "OTHER"} onChange={setCountry}>
        {COUNTRIES.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
        <option value="OTHER">Another country…</option>
      </select></label>
      {!country && <label>Country code<TextBox value={details.country === "OTHER" ? "" : details.country} onChange={(e) => setDetails((c) => ({ ...c, country: e.target.value.toUpperCase().slice(0, 2) }))} placeholder="Two letters, e.g. FR" /></label>}
      <label>Currency<select value={CURRENCIES.includes(details.currency) ? details.currency : "OTHER"} onChange={(e) => setDetails((c) => ({ ...c, currency: e.target.value === "OTHER" ? "" : e.target.value }))}>
        {CURRENCIES.map((code) => <option key={code} value={code}>{code}</option>)}
        <option value="OTHER">Another currency…</option>
      </select></label>
      {!CURRENCIES.includes(details.currency) && <label>Currency code<TextBox value={details.currency} onChange={(e) => setDetails((c) => ({ ...c, currency: e.target.value.toUpperCase().slice(0, 3) }))} placeholder="Three letters, e.g. EUR" /></label>}
      <label>Time zone<select value={details.timezone} onChange={setDetail("timezone")}>
        {zones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")}</option>)}
      </select></label>
      <p className="muted wide">The currency is fixed once you start recording money, so past records stay correct.</p>
      <h2 className="wide setupSubhead">Money you hold today</h2>
      <p className="muted wide">Enter only money your business already holds today. Leave blank if unsure; you can add it later.</p>
      <label>Cash in the till ({details.currency || "—"})<input type="number" min="0" step="0.01" value={money.opening_cash} onChange={(e) => setMoney((m) => ({ ...m, opening_cash: e.target.value }))} placeholder="0" /></label>
      <label>Bank balance ({details.currency || "—"})<input type="number" min="0" step="0.01" value={money.opening_bank} onChange={(e) => setMoney((m) => ({ ...m, opening_bank: e.target.value }))} placeholder="0" /></label>
      {earningParts.length > 1 && <BusinessPartsChoice className="wide" parts={earningParts} sector={template}
        value={money} onChange={(nextValue) => setMoney((m) => ({ ...m, ...nextValue }))} />}
    </section>}

    {current === "review" && <section className="setupPanel">
      <dl className="setupReview">
        <div><dt>Business</dt><dd>{name} · {businessType} · {catalogue.sizes.find((item) => item.id === size)?.label}</dd><button type="button" className="linkButton" onClick={() => goTo("business")}>Change</button></div>
        {description.trim() && <div><dt>About it</dt><dd>{description.trim()}</dd><button type="button" className="linkButton" onClick={() => goTo("business")}>Change</button></div>}
        <div><dt>What it does</dt><dd>{catalogue.activities.filter((a) => chosen.has(a.id)).map((a) => moduleLabel(catalogue, a.id)).join(", ")}</dd><button type="button" className="linkButton" onClick={() => goTo("does")}>Change</button></div>
        <div><dt>Tools</dt><dd>{catalogue.modules.filter((m) => !activityIds.includes(m.id) && chosen.has(m.id)).map((m) => m.label).join(", ") || "None"}</dd><button type="button" className="linkButton" onClick={() => goTo("does")}>Change</button></div>
        {!user.platform_admin && <div><dt>Plan</dt><dd>{currentPlan?.name || "—"} · first month free{(kindPrice || currentPlan) ? `, then ${(kindPrice || currentPlan).currency} ${Number((kindPrice || currentPlan).price).toLocaleString()} / ${currentPlan?.period_days === 30 ? "month" : `${currentPlan?.period_days} days`}` : ""}</dd><button type="button" className="linkButton" onClick={() => goTo("plan")}>Change</button></div>}
        {PRICE_LISTS.filter((list) => chosen.has(list.module)).map((list) => <div key={list.module}><dt>{{ services: "Services", menu: "Menu", rooms: "Rooms" }[list.module]}</dt>
          <dd>{pricedServices.filter((s) => kindOf(s) === list.module).map((s) => `${s.name.trim()} ${details.currency} ${s.selling_price}${list.module === "rooms" ? " a night" : ""}`).join(", ") || "None yet; add them later"}</dd>
          <button type="button" className="linkButton" onClick={() => goTo("lists")}>Change</button></div>)}
        {chosen.has("inventory") && <div><dt>Categories</dt><dd>{chosenCategories.join(", ") || "None yet; add them later"}</dd><button type="button" className="linkButton" onClick={() => goTo("lists")}>Change</button></div>}
        {chosen.has("chama") && <div><dt>Chama</dt><dd>{chama.name} · {details.currency} {Number(chama.contribution_amount || 0).toLocaleString()} each · {chamaPayload(chama).members.length} members · treasurer {chama.members.find((m) => m.role === "TREASURER")?.full_name || "—"}</dd><button type="button" className="linkButton" onClick={() => goTo("chama")}>Change</button></div>}
        <div><dt>First branch</dt><dd>{details.branch_name}{details.address ? ` · ${details.address}` : ""}</dd><button type="button" className="linkButton" onClick={() => goTo("place")}>Change</button></div>
        <div><dt>Contacts</dt><dd>{[details.phone, details.email].filter(Boolean).join(" · ") || "None yet"}</dd><button type="button" className="linkButton" onClick={() => goTo("place")}>Change</button></div>
        <div><dt>Country & money</dt><dd>{country?.name || details.country} · {details.currency} · {details.timezone.replaceAll("_", " ")}</dd><button type="button" className="linkButton" onClick={() => goTo("place")}>Change</button></div>
        {earningParts.length > 1 && <div><dt>Parts of the business</dt><dd>{withParts
          ? `${earningParts.map((part) => partName(part.key)).join(", ")} · ${MONEY_MODES.find((mode) => mode.id === money.money_mode)?.label}`
          : STRUCTURES.find((item) => item.id === "SINGLE").label}</dd><button type="button" className="linkButton" onClick={() => goTo("place")}>Change</button></div>}
        <div><dt>Opening money</dt><dd>{Number(money.opening_cash || 0) || Number(money.opening_bank || 0) ? `Cash ${money.opening_cash || 0} · Bank ${money.opening_bank || 0}` : "None"}</dd><button type="button" className="linkButton" onClick={() => goTo("place")}>Change</button></div>
      </dl>
      <p className="muted">Only what is listed here is set up. You can change what your business does and its tools later in Settings.</p>
      {user.platform_admin && <p className="muted">As the platform administrator, your business gets every tool for free, with no expiry.</p>}
    </section>}

    <div className="setupActions">
      {step > 0 && <button type="button" className="secondary" onClick={() => { setError(null); setStep(step - 1); }} disabled={busy}>Back</button>}
      {step < steps.length - 1 ? <button type="button" onClick={() => void next()} disabled={thinking}>{thinking ? "Reading your description…" : "Continue"}</button>
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
    <div className="businessLogoPreview setupLogo">{logo ? <img src={apiUrl(logo)} alt={`${business.name} logo`} /> : <span className="muted">No logo yet</span>}</div>
    <div className="setupActions">
      <label className={`button${busy ? " disabled" : ""}`}>{busy ? "Uploading…" : logo ? "Choose a different logo" : "Upload logo"}
        <input type="file" accept="image/png,image/jpeg,image/webp" className="sr" onChange={(e) => void upload(e)} disabled={busy} />
      </label>
      <button type="button" className={logo ? "" : "secondary"} onClick={onDone} disabled={busy}>{logo ? "Continue" : "Skip for now"}</button>
    </div>
    {error && <FormError title="Could not save the logo." message={error} />}
  </main>;
}
