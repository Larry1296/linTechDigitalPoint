import { useState } from "react";
import { businessCurrency } from "../../core/organization/presentation";
import { earnings, projectInterest } from "./interest";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const PERIODS = [[1, "1 month"], [3, "3 months"], [6, "6 months"], [12, "1 year"], [24, "2 years"], [36, "3 years"], [60, "5 years"]];

// A scratch calculator: nothing here is saved. It starts from the latest rate recorded, which can be changed to try others.
export function InterestCalculator({ defaultRate = "", defaultTax = 15, rateSource = "" }) {
  const [values, setValues] = useState({ amount: "100000", rate: String(defaultRate), months: "12", topUp: "", tax: String(defaultTax) });
  const set = (name) => (event) => setValues((current) => ({ ...current, [name]: event.target.value }));
  const ready = Number(values.amount) > 0 && Number(values.rate) > 0 && Number(values.months) > 0;
  const result = ready ? projectInterest({ amount: values.amount, annualRate: values.rate, months: values.months, topUp: values.topUp, taxRate: values.tax }) : null;
  const pace = ready ? earnings(values.amount, values.rate, values.tax) : null;
  return (
    <section className="panel investCalculator" aria-labelledby="calculator-heading">
      <h2 id="calculator-heading">What could it earn?</h2>
      <p className="muted">Try an amount before you invest it. Nothing here is saved.
        {rateSource ? ` The rate starts at the latest one recorded (${rateSource}); funds change it from month to month.` : " Enter the rate the fund quotes now."}</p>
      <div className="loanFields">
        <label>Amount to invest ({businessCurrency()})<input type="number" min="0" step="1" value={values.amount} onChange={set("amount")} /></label>
        <label>Yearly rate (%)<input type="number" min="0" max="100" step="0.01" value={values.rate} onChange={set("rate")} placeholder="e.g. 13.25" /></label>
        <label>For how long
          <select value={values.months} onChange={set("months")}>
            {PERIODS.map(([months, text]) => <option key={months} value={months}>{text}</option>)}
          </select>
        </label>
        <label>Added each month ({businessCurrency()}, optional)<input type="number" min="0" step="1" value={values.topUp} onChange={set("topUp")} placeholder="0" /></label>
        <label>Withholding tax (%)<input type="number" min="0" max="100" step="0.01" value={values.tax} onChange={set("tax")} /></label>
      </div>
      {result ? <>
        <div className="metrics investMetrics" aria-live="polite">
          <article><span>Interest after tax</span><strong>{money(result.net)}</strong></article>
          <article><span>Balance at the end</span><strong>{money(result.balance)}</strong></article>
          <article><span>{money(values.amount)} earns a day</span><strong>{money(pace.day)}</strong></article>
          <article><span>Withholding tax</span><strong>{money(result.tax)}</strong></article>
        </div>
        <p className="muted">You put in {money(result.putIn)}; interest before tax is {money(result.gross)}. Interest is worked out daily and added
          at the end of each month after tax, so it earns interest too.</p>
        <details className="investRates">
          <summary>Month by month</summary>
          <div className="trendTable"><table className="loanRepayments">
            <thead><tr><th>Month</th><th>Added</th><th>Interest (after tax)</th><th>Tax</th><th>Balance</th></tr></thead>
            <tbody>{result.rows.map((row) => <tr key={row.month}><td>{row.month}</td><td>{row.added ? money(row.added) : "—"}</td>
              <td>{money(row.interest)}</td><td>{money(row.tax)}</td><td>{money(row.balance)}</td></tr>)}</tbody>
          </table></div>
        </details>
      </> : <p className="muted">Enter an amount, a yearly rate and how long to see what it could earn.</p>}
    </section>
  );
}
