// What the business has brought in since it started, by what it was: goods, services, commission and interest, and the
// total. It leads the dashboard, before the profit: first what came in, then what is left of it. The amounts are the
// books' own (the same as the profit card's), with the counts behind them; the bar shows each one's share of the total.
const PAGE = { "4000": "/admin/sales-history", "4030": "/admin/menu", "4020": "/admin/cyber", "4040": "/admin/rooms",
  "4010": "/admin/mpesa/commission", "4050": "/admin/mkopa", "4910": "/admin/investments", "6200": "/admin/investments", "4900": "/admin/reports" };
// What each kind is, in the words of the lines this business has.
const LINE_WORDS = { "4000": "products", "4030": "food and drinks", "4020": "work done for customers", "4040": "rooms let",
  "4010": "Safaricom", "4050": "M-KOPA" };
const join = (words) => words.join(", ").replace(/, ([^,]*)$/, " and $1");
function what(group) {
  const words = group.lines.map((line) => LINE_WORDS[line.code]).filter(Boolean);
  if (group.key === "GOODS") return `${join(words).replace(/^./, (c) => c.toUpperCase())} sold`;
  if (group.key === "SERVICES") return join(words).replace(/^./, (c) => c.toUpperCase());
  if (group.key === "COMMISSION") return `Paid to you by ${join(words)}`;
  if (group.key === "INTEREST") return "Earned on your investments, after fees";
  return "Income that is none of these";
}
const SEE = { "4000": "See sales", "4030": "See the menu", "4020": "See services", "4040": "See rooms", "4010": "See commission",
  "4050": "See M-KOPA", "4910": "See investments", "4900": "See reports" };

const number = (value) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 3 });
const plural = (count, one, many = `${one}s`) => `${number(count)} ${Number(count) === 1 ? one : many}`;
const share = (amount, total) => (Number(total) > 0 && Number(amount) > 0 ? (Number(amount) / Number(total)) * 100 : 0);
const percent = (value) => (value > 0 && value < 1 ? "under 1%" : `${Math.round(value)}%`);

// What sits behind a line's amount, in plain words.
function lineNote(line, money) {
  switch (line.code) {
    case "4000": return line.sales ? `${plural(line.sales, "sale")} · ${plural(line.quantity, "item")} sold` : "Nothing sold yet";
    case "4030": return Number(line.quantity) ? `${plural(line.quantity, "dish or drink", "dishes and drinks")} sold` : "Nothing sold yet";
    case "4020": return Number(line.quantity) ? `${plural(line.quantity, "service")} done` : "No services sold yet";
    case "4040": return Number(line.quantity) ? `${plural(line.quantity, "night")} paid for` : "No nights paid yet";
    case "4010": return [line.months_paid ? `Safaricom has paid ${plural(line.months_paid, "month")}` : "Safaricom has not paid any yet",
      Number(line.coming) > 0 && `${money(line.coming)} more worked out for ${line.coming_months.join(", ")}, counted once it is paid`].filter(Boolean).join(" · ");
    case "4050": return [line.phones ? `${plural(line.phones, "phone")} sold` : "No phones sold yet",
      Number(line.coming) > 0 && `${money(line.coming)} still expected for ${plural(line.waiting_phones, "phone")} M-KOPA has not paid for`].filter(Boolean).join(" · ");
    case "4910": return "From your fund statements";
    case "6200": return "Taken off the interest";
    default: return "";
  }
}

// The steps from the total sold and earned to the business's money now, in plain words (added, or taken away below 0).
const BRIDGE = {
  not_received: ["Received for sales recorded later (deposits and the like)", "Sold but not paid yet (customers still owe it)"],
  starting: ["Money the business started with"], own_for_suppliers: ["Your own money put in to pay suppliers"],
  found: ["Business money the app had not seen, found when you invested it"],
  agency: ["Moved in from the M-Pesa agency's cash", "Moved to the M-Pesa agency"],
  suppliers: ["Supplier refunds", "Paid to suppliers for stock"], expenses: ["Running costs refunded", "Spent on running costs"],
  loans: ["Loans repaid", "Money lent out, less what was repaid"], other: ["Other money in", "Other money out"],
};
const stepLabel = (line) => BRIDGE[line.key]?.[Number(line.amount) < 0 && BRIDGE[line.key].length > 1 ? 1 : 0] || line.key;

// Why the business's money is not the total: every step from one to the other, from the cash book, and where it is now.
function MoneyBridge({ bridge, total, money }) {
  const signed = (value) => `${Number(value) < 0 ? "−" : "+"} ${money(Math.abs(Number(value)))}`;
  return <details className="soldBridge">
    <summary>Why the business's money now ({money(bridge.money_now)}{Number(bridge.in_investments) ? `, ${money(bridge.in_investments)} of it in investments` : ""}) is not this total</summary>
    <p>The total above is what was sold and earned. The business's money is what it holds. They differ because money also came in and
      went out without being a sale, and some sales are not paid yet:</p>
    <dl className="soldSteps">
      <div className="first"><dt>Total sold and earned</dt><dd>{money(total)}</dd></div>
      {bridge.lines.map((line) => <div key={line.key}><dt>{stepLabel(line)}</dt><dd>{signed(line.amount)}</dd></div>)}
      <div className="last"><dt>The business's money now</dt><dd>{money(bridge.money_now)}</dd></div>
    </dl>
    <p className="soldWhere">Where it is: <a href="/admin/money-check">{money(bridge.in_places)} in the drawer, till and bank</a>
      {Number(bridge.in_investments) ? <> and <a href="/admin/investments">{money(bridge.in_investments)} kept in investments</a>
        {Number(bridge.interest) ? `, including the ${money(bridge.interest)} interest it earned there` : ""}</> : null}.</p>
  </details>;
}

export function SoldSummary({ sold, since, owedSales, bridge, money }) {
  if (!sold?.groups?.length) return null;
  const total = Number(sold.total || 0);
  const started = since ? new Date(`${since}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" }) : "";
  const parts = sold.groups.filter((group) => Number(group.amount) > 0);
  return <section className="soldSummary" aria-labelledby="sold-summary-title">
    <header className="soldHead">
      <div>
        <span className="eyebrow">Since you started{started ? ` · ${started}` : ""}</span>
        <h2 id="sold-summary-title">Everything sold and earned</h2>
        <p>All the money the business's sales, services, commission and interest have made since you started. Nothing is taken off yet:
          what the goods cost you and the money you spent come off in the profit below. It is not the money you have now.</p>
      </div>
      <div className="soldTotal">
        <span>Total sold and earned</span>
        <strong>{money(total)}</strong>
        {sold.groups.length > 1 && <small>{sold.groups.map((group) => group.name.toLowerCase()).join(" + ")}</small>}
      </div>
    </header>

    {/* Each part's share of the total. Every share is also written in its card below, so colour is never the only key. */}
    {total > 0 && <div className="soldBar" role="img" aria-label={`Share of the total: ${parts.map((group) => `${group.name} ${percent(share(group.amount, total))}`).join(", ")}`}>
      {parts.map((group) => <span key={group.key} className={`soldSeg ${group.key.toLowerCase()}`} style={{ flexGrow: Number(group.amount) }}
        title={`${group.name}: ${money(group.amount)} · ${percent(share(group.amount, total))} of the total`} />)}
    </div>}

    <div className="soldGroups">
      {sold.groups.map((group) => {
        const part = share(group.amount, total);
        return <article key={group.key} className={`soldGroup ${group.key.toLowerCase()}`} aria-labelledby={`sold-${group.key}`}>
          <header>
            <span className="soldDot" aria-hidden="true" />
            <h3 id={`sold-${group.key}`}>{group.name}</h3>
            <span className="soldShare">{total > 0 && Number(group.amount) > 0 ? percent(part) : "—"}</span>
          </header>
          <strong className={Number(group.amount) < 0 ? "loss" : undefined}>{money(group.amount)}</strong>
          <p className="soldWhat">{what(group)}</p>
          {/* One line: what is behind the amount and where to see it. Several: each with its own amount. */}
          {group.lines.length === 1 ? <div className="soldOne">
            {lineNote(group.lines[0], money) && <small>{lineNote(group.lines[0], money)}</small>}
            <a href={PAGE[group.lines[0].code]}>{SEE[group.lines[0].code] || "See more"} <span aria-hidden="true">→</span></a>
          </div> : <ul>{group.lines.map((line) => <li key={line.code}>
            <div><a href={PAGE[line.code]}>{line.name}</a><b className={Number(line.amount) < 0 ? "loss" : undefined}>{money(line.amount)}</b></div>
            {lineNote(line, money) && <small>{lineNote(line, money)}</small>}
          </li>)}</ul>}
        </article>;
      })}
    </div>

    <footer className="soldFoot">
      <p><b>{sold.groups.map((group) => group.name).join(" + ")} = total sold and earned</b> <span>{sold.groups.map((group) => money(group.amount)).join(" + ")} = <b>{money(total)}</b></span></p>
      {Number(owedSales || 0) > 0 && <p className="muted">Includes {money(owedSales)} sold on credit that customers have not paid yet. <a href="/admin/sales-history">See who owes</a></p>}
    </footer>
    {bridge && <MoneyBridge bridge={bridge} total={total} money={money} />}
  </section>;
}
