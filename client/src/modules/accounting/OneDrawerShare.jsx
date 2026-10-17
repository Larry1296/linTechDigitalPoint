import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { businessCurrency } from "../../core/organization/presentation";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

// One drawer for the whole business (server mpesa/combined.py shares): all the money it holds is the M-Pesa money in
// operation, and each part shows what it put into it. Without ``part`` (the M-Pesa desk) every part's share is listed;
// with it (the shop's or cyber's page) that part's own. Shows nothing for a business that keeps its parts' money apart,
// or for someone not allowed to see the money.
export function OneDrawerShare({ part }) {
  const [shares, setShares] = useState(null);
  useEffect(() => {
    let live = true;
    api("/api/v1/accounting/one-drawer/").then((data) => live && setShares(data?.shares || null)).catch(() => live && setShares(null));
    return () => { live = false; };
  }, []);
  if (!shares) return null;
  if (!part) {
    return <section className="dashCard oneDrawerShare" aria-labelledby="one-drawer-title">
      <h2 id="one-drawer-title">Money in operation: {money(shares.total)}</h2>
      <p className="muted">All the money the business holds, in the one drawer and on the agent line. Each part's share of it:</p>
      <dl className="dashList">
        {shares.parts.map((row) => <div key={row.key}><dt>{row.label}</dt><dd>{money(row.amount)}</dd></div>)}
        <div className="ownerSummaryTotal"><dt>All together</dt><dd>{money(shares.total)}</dd></div>
      </dl>
    </section>;
  }
  const own = shares.parts.find((row) => row.key === part);
  if (!own) return null;
  const steps = [`sold ${money(own.sales)}`, Number(own.cogs) && `items cost ${money(own.cogs)} (buying price)`,
    Number(own.expenses) && `running costs ${money(own.expenses)}`].filter(Boolean);
  return <section className="dashCard oneDrawerShare" aria-label={`${own.label}'s share of the money`}>
    <p><strong>{own.label}'s share of the money the business holds: {money(own.amount)}</strong> of {money(shares.total)} (the M-Pesa money in operation, one drawer for everything).</p>
    <p className="muted">Since the start: {steps.join(", ")}{own.profit != null ? `; profit ${money(own.profit)}` : ""}. Its share is what it took in less what it paid out from the drawer.</p>
  </section>;
}
