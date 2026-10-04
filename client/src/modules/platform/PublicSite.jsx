import { ThemePicker } from "../../components/ThemePicker";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDownRight, ArrowUpRight, Boxes, MessageCircle, Building2, ChartNoAxesCombined, CircleCheck, LogIn, Menu, ReceiptText, ShieldCheck, Store, UserPlus, Users, Wrench, X } from "lucide-react";
import { usePlatform } from "./PlatformContext";
import { PlatformLogo } from "../../components/Brand";
import { PhotoCarousel, usePrefersReducedMotion } from "../../components/PhotoCarousel";
import { HERO_SLIDES, PEOPLE_SLIDES, WORK_TILES } from "./showcase";
import { HelpChat, openHelpChat } from "./HelpChat";
import { LiveDashboard, between, clamp, useLiveTick } from "./LiveCharts";
import { api } from "../../core/api/client";
import "./platform.css";
import "./home.css";
const features = [
  ["inventory", Boxes, "Inventory, with a place for everything", "Organize products and categories, receive stock, and track quantities across shelves and locations. Keep receipts and a history of stock movements.", ["Group products into categories your staff recognise", "Record stock received, with its receipt kept alongside", "See where stock sits across shelves and locations"]],
  ["pos", ReceiptText, "A connected point of sale", "Find products, complete counter sales and keep payment records alongside your inventory. Record cash and manual M-Pesa payments.", ["Search and add products quickly at the counter", "Stock quantities update as sales are completed", "Cash and M-Pesa payments recorded with each sale"]],
  ["services", Wrench, "Services alongside your products", "Configure service fees, manage jobs and retain the charged price on completed transactions. Record physical materials separately when a service uses stock.", ["Set fees for the services you offer", "Keep the price actually charged on each completed job", "Track materials a service consumes from stock"]],
  ["analytics", ChartNoAxesCombined, "Understand your business records", "Review sales, expenses, purchases and inventory with reports built from your business records. Restrict access to cost and profit information.", ["Sales, expenses and purchases in one place", "Inventory reports built from recorded activity", "Cost and profit visible only to the right people"]],
  ["business", Users, "Your business, your workspace", "Set your business name, currency and time zone. Choose the modules you need and give each member of staff their own sign-in and role.", ["Business details and modules managed in Settings", "Turn on only the modules you use", "Add staff with roles like cashier or accountant"]],
  ["privacy", ShieldCheck, "Separate businesses. Private workspaces.", "Your organization provides the boundary for products, locations, transactions and reports. Switch between businesses you are authorized to access.", ["Each business keeps its own products and records", "Transactions and reports stay inside the organization", "Move between businesses you are authorized to access"]],
];
const steps = [
  [UserPlus, "Create your account", "Register with your details and sign in to start setting up."],
  [Building2, "Set up your business", "Enter your business name, currency and time zone, then choose your modules."],
  [Store, "Add what you sell", "Add products, categories, locations and the services you offer."],
  [ChartNoAxesCombined, "Run and review", "Record sales and services each day, then review reports built from your records."],
];
const audiences = [
  ["Retail shops", "Keep shelves, stock receipts and counter sales connected so quantities stay accurate."],
  ["Service counters", "Charge for printing, repairs, setup or other services and keep each job's price on record."],
  ["Mixed businesses", "Sell products and services side by side, with materials tracked when a service uses stock."],
  ["Growing teams", "Give staff their own access and keep cost and profit details limited to the people who need them."],
];
const faqs = [
  ["What can I manage in the workspace?", "Inventory, a point of sale, services and reports. You choose the modules your business needs when you set it up."],
  ["Can my staff use it too?", "Yes. The owner adds staff in Settings and gives each person a role, such as cashier, inventory or accountant, that decides what they can see and do."],
  ["Is my business data kept separate?", "Yes. Your organization is the boundary for your products, locations, transactions and reports. Other subscribers cannot see them."],
  ["Can I run more than one business?", "You can switch between the businesses you are authorized to access, each with its own private workspace."],
  ["How are M-Pesa payments handled?", "Cash and M-Pesa payments are recorded manually alongside each sale, so your payment records sit next to your inventory."],
  ["How much does it cost?", "The first month is free. After that, Basic is KES 500 a month and Pro, with every feature, is KES 1,000 a month, paid by M-Pesa."],
];
export function PublicNavbar() {
  const [open, setOpen] = useState(false);
  return <header className="saasNav">
    <Link className="saasBrand" to="/"><PlatformLogo /></Link>
    <nav id="saas-navigation" aria-label="Main navigation" className={open ? "isOpen" : ""} onClick={() => setOpen(false)} onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}>
      <a href="/#features">Features</a><a href="/#business">Business management</a><a href="/#pricing">Pricing</a><a href="/#contact">Contact</a>
    </nav><div className="saasNavActions"><Link className="button saasGetStarted" to="/register">Get started <ArrowUpRight size={16} aria-hidden="true" /></Link><Link className="saasLogin" to="/login"><LogIn size={16} aria-hidden="true" />Login</Link><ThemePicker /><button className="saasMenu" aria-expanded={open} aria-controls="saas-navigation" aria-label={open ? "Close navigation" : "Open navigation"} onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button></div>
  </header>;
}
export function PublicFooter() {
  const platform = usePlatform();
  return <footer className="saasFooter">
    <div><PlatformLogo /></div>
    <div><b>Product</b><a href="/#features">Features</a><a href="/#pricing">Subscriptions</a><Link to="/login">Login</Link><Link to="/register">Register a business</Link></div>
    <div><b>Features</b><a href="/#inventory">Inventory</a><a href="/#pos">Point of sale</a><a href="/#services">Services</a><a href="/#analytics">Reports</a></div>
    <div><b>Company & support</b><a href="/#about">About</a><a href="/#contact">Contact</a><Link to="/forgot-password">Account recovery</Link>{platform.contact_email && <a href={`mailto:${platform.contact_email}`}>{platform.contact_email}</a>}</div>
  </footer>;
}
// Sections fade up as they scroll into view. Without IntersectionObserver, or with reduced
// motion, nothing is hidden: the class that hides sections is only added when this runs.
function useRevealOnScroll() {
  const root = useRef(null);
  const reduced = usePrefersReducedMotion();
  useEffect(() => {
    const page = root.current;
    if (!page || reduced || typeof IntersectionObserver === "undefined") return undefined;
    const sections = [...page.querySelectorAll(".saasSection")];
    page.classList.add("revealReady");
    const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
      if (entry.isIntersecting) { entry.target.classList.add("isVisible"); observer.unobserve(entry.target); }
    }), { rootMargin: "0px 0px -10% 0px" });
    sections.forEach((section) => observer.observe(section));
    return () => { observer.disconnect(); page.classList.remove("revealReady"); };
  }, [reduced]);
  return root;
}

export function PublicHome() {
  const platform = usePlatform();
  const page = useRevealOnScroll();
  return <div className="saasSite" ref={page}><PublicNavbar /><main>
    <section className="saasHero" id="home">
      <div><span className="eyebrow">One business. One clear view.</span><h1>Keep your business<br /><em>moving forward.</em></h1><p>Bring your stock, sales, services and business records into a workspace that belongs to you.</p><div className="saasActions"><Link className="button" to="/register">Set up your business <ArrowUpRight size={18} /></Link><a className="button secondary" href="#features">Explore the platform</a></div><p className="saasNote">For business owners and the people who help them run each day.</p><button type="button" className="homeAskLink" onClick={() => openHelpChat()}><MessageCircle size={18} aria-hidden="true" /> Questions? Ask our assistant</button></div>
      <div className="homeVisual">
        <PhotoCarousel slides={HERO_SLIDES} label="The platform at work" className="homeHeroPhoto">
          {(slide) => <div className="homePhotoCaption" key={slide.src}><span className="homeStatusDot" /> {slide.caption}</div>}
        </PhotoCarousel>
        <WeekOverview />
        <div className="homeFloatingBadge"><ShieldCheck size={22} /><span>Your business.<br /><b>Your own workspace.</b></span></div>
      </div>
    </section>
    <div className="homeModuleStrip" aria-label="Connected business tools">{[[Boxes, "Inventory"], [ReceiptText, "Point of sale"], [Wrench, "Services"], [ChartNoAxesCombined, "Analytics"], [Users, "Your team"]].map(([Icon, label]) => <span key={label}><Icon size={22} aria-hidden="true" />{label}</span>)}</div>
    <section className="saasSection homeWork" aria-labelledby="home-work-title"><span className="eyebrow">Your day, connected</span><h2 id="home-work-title">From the stockroom to the counter to the books.</h2>
      <div className="homeWorkGrid">{WORK_TILES.map((tile, index) => (
        <PhotoCarousel key={tile.title} slides={tile.slides} label={tile.title} startDelay={index * 1000} className="homeWorkTile">
          {() => <div className="homeWorkCaption"><strong>{tile.title}</strong><span>{tile.text}</span></div>}
        </PhotoCarousel>
      ))}</div>
    </section>
    <section id="features" className="saasSection"><span className="eyebrow">The work behind your business</span><h2>Connected tools for everyday operations.</h2><p className="homeSectionIntro">Everything shares the same records, so a sale, a received delivery or a completed job shows up everywhere it matters.</p><div className="saasFeatureGrid">{features.map(([id,Icon,title,description,points]) => <article id={id} key={id}><Icon size={27} aria-hidden="true" /><h3>{title}</h3><p>{description}</p><ul className="homeFeaturePoints">{points.map(point => <li key={point}><CircleCheck size={16} aria-hidden="true" />{point}</li>)}</ul></article>)}</div></section>
    <section className="saasSection homeSteps" aria-labelledby="home-steps-title"><span className="eyebrow">Getting started</span><h2 id="home-steps-title">From sign-up to your first sale.</h2><ol className="homeStepList">{steps.map(([Icon, title, description], index) => <li key={title}><span className="homeStepNumber">{index + 1}</span><Icon size={22} aria-hidden="true" /><h3>{title}</h3><p>{description}</p></li>)}</ol></section>
    <section className="saasSection homeAnalytics" aria-labelledby="home-analytics-title">
      <div><span className="eyebrow">Turn records into perspective</span><h2 id="home-analytics-title">See the bigger picture.<br /><em>Make your next move.</em></h2><p>Bring sales, purchases and expenses into focus. Understand the activity behind your day with reports built from your business records.</p><ul className="homeCheckList"><li><ShieldCheck size={19} /> Control access to cost and profit information</li><li><ChartNoAxesCombined size={19} /> Review sales and expense trends</li><li><Boxes size={19} /> Keep inventory in the picture</li></ul><Link className="button" to="/register">Bring your business together <ArrowUpRight size={18} /></Link></div>
      <SalesPreview />
    </section>
    <LiveDashboard />
    <section id="about" className="saasSection homePeople"><div className="homePeoplePhoto"><PhotoCarousel slides={PEOPLE_SLIDES} label="The people behind the business" startDelay={2000} className="homePeopleCarousel" /><div>Less scattered work.<br /><strong>More moving forward.</strong></div></div><div><span className="eyebrow">Built around your business</span><h2>Good business starts<br />with your people.</h2><p>{platform.name} gives each subscribed business its own management workspace. Your products, categories, physical locations and service offerings belong to your organization.</p><p>Create your account, enter your business details and choose your modules. Existing businesses can add products and locations without adopting another subscriber’s setup.</p></div></section>
    <section className="saasSection homeAudience" aria-labelledby="home-audience-title"><div><span className="eyebrow">Who it's for</span><h2 id="home-audience-title">Made for businesses that sell and serve.</h2><p>Whether you run a single counter or several locations, the workspace adapts to the modules you turn on.</p></div><div className="homeAudienceGrid">{audiences.map(([title, description]) => <article key={title}><h3>{title}</h3><p>{description}</p></article>)}</div></section>
    <PublicPricing />
    <section id="faq" className="saasSection homeFaq" aria-labelledby="home-faq-title"><span className="eyebrow">Questions</span><h2 id="home-faq-title">Frequently asked questions.</h2><button type="button" className="homeAskLink" onClick={() => openHelpChat()}><MessageCircle size={18} aria-hidden="true" /> Can't find your question? Ask our assistant</button><div className="homeFaqList">{faqs.map(([question, answer]) => <details key={question}><summary>{question}</summary><p>{answer}</p></details>)}</div></section>
    <section className="saasSection homeCta" aria-labelledby="home-cta-title"><div><h2 id="home-cta-title">Ready to bring your business together?</h2><p>Set up your workspace, add your products and services, and start recording your day.</p></div><div className="saasActions"><Link className="button" to="/register">Set up your business <ArrowUpRight size={18} /></Link><Link className="button secondary" to="/login">Sign in</Link></div></section>
    <section id="contact" className="saasSection homeContact"><span className="eyebrow">Contact & support</span><h2>Find your next step.</h2><p>{platform.contact_email ? <a href={`mailto:${platform.contact_email}`}>{platform.contact_email}</a> : "A public support contact has not yet been configured."}</p><Link to="/login">Sign in to your workspace</Link></section>
  </main><PublicFooter /><HelpChat /></div>;
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
// A typical small shop: quieter early in the week, busiest on Friday and Saturday.
const DAY_PATTERN = [42, 48, 46, 58, 72, 90, 78];
const nextDay = (day) => clamp(DAY_PATTERN[day % 7] + between(-14, 12), 18, 98);

// Hero card: the last seven days of sales. Each tick the week rolls forward one day.
function WeekOverview() {
  const [node, tick] = useLiveTick(2600);
  const [week, setWeek] = useState({ start: 0, values: [32, 48, 40, 68, 58, 82, 95], previousTotal: 380 });
  useEffect(() => {
    if (!tick) return;
    setWeek(({ start, values }) => ({ start: start + 1, values: [...values.slice(1), nextDay(start + 7)], previousTotal: values.reduce((sum, value) => sum + value, 0) }));
  }, [tick]);
  const total = week.values.reduce((sum, value) => sum + value, 0);
  const change = Math.round(((total - week.previousTotal) / week.previousTotal) * 100);
  return (
    <aside className="homeMiniReport" aria-label="Illustrative sales overview" ref={node}>
      <div className="homeReportHeading"><span><ChartNoAxesCombined size={18} /> Business overview</span><small><span className="homeLiveDot" aria-hidden="true" />Sample data</small></div>
      <strong>A clearer view. Every day.</strong>
      <p className="homeMiniTotal">Last 7 days <b>{Math.round(total)}k</b>
        <span className={change >= 0 ? "up" : "down"}>{change >= 0 ? <ArrowUpRight size={13} aria-label="Up" /> : <ArrowDownRight size={13} aria-label="Down" />}{Math.abs(change)}%</span></p>
      <div className="homeMiniBars" aria-hidden="true">
        {week.values.map((value, index) => <i key={index} className={index === 6 ? "today" : undefined} title={`${DAYS[(week.start + index) % 7]}: ${Math.round(value)}k`}
          style={{ height: `${value}%`, animationDelay: `${index * 70}ms` }} />)}
      </div>
      <div className="homeChartLabels">{week.values.map((_, index) => <span key={index}>{DAYS[(week.start + index) % 7]}</span>)}</div>
    </aside>
  );
}

const sampleWeeks = [
  { label: "Week 1", sales: 42, expenses: 27 },
  { label: "Week 2", sales: 58, expenses: 32 },
  { label: "Week 3", sales: 51, expenses: 29 },
  { label: "Week 4", sales: 76, expenses: 40 },
];
// A new month of sample figures: sales drift from last month's, expenses stay a believable share of sales.
function nextMonth(weeks) {
  return weeks.map((week, index) => {
    const sales = clamp(week.sales + between(-10, 12) + (index === 3 ? 4 : 0), 30, 78);
    return { ...week, sales, expenses: clamp(sales * between(0.48, 0.68), 16, 60) };
  });
}

function SalesPreview() {
  const [node, tick] = useLiveTick(3400);
  const [weeks, setWeeks] = useState(sampleWeeks);
  useEffect(() => { if (tick) setWeeks((current) => nextMonth(current)); }, [tick]);
  const net = weeks.reduce((sum, week) => sum + week.sales - week.expenses, 0);
  const describe = weeks.map((week) => `${week.label}: ${Math.round(week.sales)} and ${Math.round(week.expenses)}`).join("; ");
  return <figure className="homeSalesPreview" ref={node}>
    <figcaption><div><span className="eyebrow">Your performance at a glance</span><h3>Sales & expenses</h3></div><span className="homeSampleLabel"><span className="homeLiveDot" aria-hidden="true" />Sample data</span></figcaption>
    <p className="homeChartUnit">Illustrative monthly activity · thousands · net this month <b className="homeNet">{Math.round(net)}k</b></p>
    <div className="homeBarChart" role="img" aria-label={`Sample sales and expenses in thousands. ${describe}.`}>
      <div className="homeAxis" aria-hidden="true"><span>80</span><span>60</span><span>40</span><span>20</span><span>0</span></div>
      <div className="homeChartPlot" aria-hidden="true">{weeks.map(week => <div className="homeBarGroup" key={week.label}><div className="homeBarPair">
        <i style={{ height: `${week.sales / 80 * 100}%` }} title={`${week.label} sales: ${Math.round(week.sales)}k`} />
        <i style={{ height: `${week.expenses / 80 * 100}%` }} title={`${week.label} expenses: ${Math.round(week.expenses)}k`} />
      </div><span>{week.label}</span></div>)}</div>
    </div>
    <div className="homeChartLegend"><span><i /> Sales</span><span><i /> Expenses</span></div>
    <div className="homeReportFoot"><ShieldCheck size={17} /> Your records. A more informed next step.</div>
  </figure>;
}

// The plans on offer, straight from the platform's plan settings.
function PublicPricing() {
  const [data, setData] = useState(null);
  useEffect(() => { api("/api/v1/tenancy/plans/").then(setData).catch(() => setData({ plans: [] })); }, []);
  return <section id="pricing" className="saasSection" aria-labelledby="pricing-title">
    <span className="eyebrow">Subscriptions</span>
    <h2 id="pricing-title">Simple monthly plans. First month free.</h2>
    <p className="homeSectionIntro">Start with {data?.trial_days || 30} days free on the plan you choose, then pay monthly by M-Pesa. Change plan any time.</p>
    <div className="publicPlans">
      {(data?.plans || []).map((plan) => <article key={plan.code} className={`publicPlan${plan.code === "PRO" ? " pro" : ""}`}>
        <h3>{plan.name}</h3>
        <p className="publicPlanPrice"><strong>{plan.currency} {Number(plan.price).toLocaleString()}</strong> / month</p>
        <p>{plan.description}</p>
        <ul>{plan.features.map((feature) => <li key={feature}><CircleCheck size={16} aria-hidden="true" /> {feature}</li>)}</ul>
        <Link className={`button${plan.code === "PRO" ? "" : " secondary"}`} to="/register">Start free</Link>
      </article>)}
    </div>
  </section>;
}
