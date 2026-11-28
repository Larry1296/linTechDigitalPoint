import { NotInvested } from "../investments/NotInvested";
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

// Each step of the cash book in a few plain words, as money that came in from elsewhere (above 0) or was paid out (below).
const CAME_IN = { starting: "the money it started with", found: "already in the investment before the app saw it", agency: "moved in from the M-Pesa agency",
  suppliers: "supplier refunds", expenses: "running costs refunded", loans: "loans repaid", taken_by_owner: "profit put back", other: "other money in", not_received: "paid ahead for later sales" };
const PAID_OUT = { suppliers: "paid to suppliers", expenses: "running costs", loans: "money lent out", agency: "moved to the M-Pesa agency",
  taken_by_owner: "profit taken to your own account", other: "other money out", found: "counted twice: already in the investment" };

// The simple sum from what was earned to the money the business has: earned, plus money that came from elsewhere, less
// what was paid out, less what customers still owe. Stock the owner paid for from their own pocket never came out of the
// business's money, so it is said in a note, not added and taken away. Every amount is the cash book's (money_bridge).
function MoneySum({ bridge, total, money }) {
  const amount = (key) => Number(bridge.lines.find((line) => line.key === key)?.amount || 0);
  const own = amount("own_for_suppliers");
  const owed = amount("not_received");
  // In the cash book's order; suppliers less what the owner paid them from their own pocket.
  const steps = bridge.lines.filter((line) => line.key !== "own_for_suppliers" && (line.key !== "not_received" || owed > 0))
    .map((line) => ({ key: line.key, amount: line.key === "suppliers" ? Number(line.amount) + own : Number(line.amount) }))
    .filter((step) => Math.abs(step.amount) > 0.004);
  const cameIn = steps.filter((step) => step.amount > 0);
  const paidOut = steps.filter((step) => step.amount < 0);
  const sum = (rows) => rows.reduce((all, row) => all + row.amount, 0);
  const which = (rows, words) => rows.map((row) => `${money(Math.abs(row.amount))} ${words[row.key] || row.key}`).join(" · ");
  const funds = bridge.funds?.length === 1 ? bridge.funds[0] : "investments";
  const inPlaces = Number(bridge.in_places);
  const invested = Number(bridge.in_investments);
  return <section className="soldSum" aria-labelledby="sold-sum-title">
    <h3 id="sold-sum-title">From what was earned to the money you have</h3>
    <dl className="soldSteps">
      <div className="first"><dt>Earned from sales and work<small>The total above</small></dt><dd>{money(total)}</dd></div>
      {cameIn.length > 0 && <div><dt>+ Money that came from elsewhere<small>{which(cameIn, CAME_IN)}</small></dt><dd>+ {money(sum(cameIn))}</dd></div>}
      {paidOut.length > 0 && <div><dt>− Paid out<small>{which(paidOut, PAID_OUT)}</small></dt><dd>− {money(-sum(paidOut))}</dd></div>}
      {owed < 0 && <div><dt>− Still owed by customers<small>Sold, not paid yet</small></dt><dd>− {money(-owed)}</dd></div>}
      <div className="last"><dt>= The business's money now<small>
        {invested ? <><a href="/admin/investments">{money(invested)} in {funds}</a>{Number(bridge.interest) ? `, with the ${money(bridge.interest)} interest it earned there` : ""}</> : null}
        {invested && inPlaces ? " · " : null}
        {inPlaces ? <a href="/admin/money-check">{money(inPlaces)} in the drawer, till and bank: sold, not invested yet</a>
          : invested ? " · nothing in the drawer, till or bank" : null}
      </small></dt><dd>{money(bridge.money_now)}</dd></div>
    </dl>
    {own > 0 && <p className="soldWhere">You paid suppliers {money(own)} from your own pocket, so it never came out of the business's money.</p>}
  </section>;
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
          what the goods cost you and the money you spent come off in the profit below. It is not the money you have now{bridge ? ", which is shown with it" : ""}.</p>
      </div>
    </header>
    {/* The two figures owners ask about: what was sold and earned, and the money the business holds now. */}
    <div className="soldFigures">
      <div className="soldTotal">
        <span>Total sold and earned</span>
        <strong>{money(total)}</strong>
        <small>{sold.groups.length > 1 ? sold.groups.map((group) => group.name.toLowerCase()).join(" + ") : "Since you started"}</small>
      </div>
      {bridge && <a className="soldTotal soldMoney" href={Number(bridge.in_places) ? "/admin/money-check" : "/admin/investments"}>
        <span>The business's money now</span>
        <strong>{money(bridge.money_now)}</strong>
        <small>{!Number(bridge.in_places) && Number(bridge.in_investments) ? "All of it kept in investments"
          : Number(bridge.in_investments) ? `${money(bridge.in_investments)} in ${bridge.funds?.length === 1 ? bridge.funds[0] : "investments"} · ${money(bridge.in_places)} sold, not invested yet`
          : "In the drawer, till and bank"}</small>
      </a>}
      {bridge && Number(bridge.in_investments) !== 0 && <NotInvested as="a" href="/admin/money-check" className="soldTotal" total={bridge.in_places}
        places={bridge.places} split={bridge.split} money={money} />}
    </div>

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
    {bridge && <MoneySum bridge={bridge} total={total} money={money} />}
  </section>;
}
