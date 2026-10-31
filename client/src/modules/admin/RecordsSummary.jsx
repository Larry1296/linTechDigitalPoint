import { interestText, profitText, stockText } from "./plainMoney";

const CHANNELS = { POS: "at the counter", CYBER: "services", ONLINE: "online" };
const METHODS = { CASH: "Cash", MPESA: "M-Pesa", BANK: "Bank", OTHER: "Other", CASH_ON_PICKUP: "Cash on pickup", DEPOSIT: "Paid in advance (guests)" };

function Group({ title, rows }) {
  const shown = rows.filter(Boolean);
  return <article className="recordsGroup"><h3>{title}</h3><dl>
    {shown.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
  </dl></article>;
}

// Everything the business has recorded since it started, part by part, with exact figures. Parts the viewer may
// not see are left out. Money matches the rest of the dashboard: sales, cost and profit come from the same books.
export function RecordsSummary({ records, money }) {
  if (!records) return null;
  const { catalogue, stock, sales, services, mpesa, money: cash, profit } = records;
  const count = (value) => Number(value || 0).toLocaleString();
  const many = (value, one, other) => `${count(value)} ${Number(value) === 1 ? one : other}`;
  return <section className="recordsSummary" aria-labelledby="records-summary-title">
    <h2 id="records-summary-title">Everything recorded so far</h2>
    <p>All of the business's records{records.since ? ` since ${records.since}` : ""}, not just the dates picked above.</p>
    {profit && <p className="profitSum"><b>Sales {money(profit.revenue)} − what the sold items cost you {money(profit.cogs)} − running costs {money(profit.expenses)}
      {Number(profit.stock_corrections || 0) ? ` ${stockText(profit.stock_corrections, money)}` : ""}
      {Number(profit.interest || 0) ? ` ${interestText(profit.interest, money)}` : ""} = {profitText(profit.profit, money)}</b></p>}
    <div className="recordsGrid">
      {catalogue && <Group title="What you sell" rows={[
        ["Products", count(catalogue.products)],
        ["Items (sizes, colours, packs)", `${count(catalogue.items)} (${count(catalogue.items_active)} on sale)`],
        ["Services", count(catalogue.services)],
        ["Categories", count(catalogue.categories)],
        ["Brands", count(catalogue.brands)],
      ]} />}
      {stock && <Group title="Stock" rows={[
        ["Items on the shelves now", count(stock.units_on_shelves)],
        ["Different items in stock", count(stock.items_in_stock)],
        ["Items ever received", count(stock.units_received)],
        ["Deliveries and opening stock entered", count(stock.deliveries)],
        Number(stock.without_buying_price) > 0 && ["Still without a buying price", count(stock.without_buying_price)],
      ]} />}
      {sales && <Group title="Sales" rows={[
        ["Sales made", `${count(sales.completed)}${Object.keys(sales.by_channel).length ? ` (${Object.entries(sales.by_channel).map(([key, n]) => `${count(n)} ${CHANNELS[key] || key}`).join(", ")})` : ""}`],
        ["Sales cancelled", count(sales.cancelled)],
        ["Items sold", count(sales.units_sold)],
        ["Sales", money(sales.revenue)],
        sales.cogs != null && ["What the sold items cost you", money(sales.cogs)],
        sales.gross_profit != null && ["Profit before running costs", profitText(sales.gross_profit, money)],
        ["Returns", `${count(sales.returns)} · ${money(sales.refunded)} refunded`],
      ]} />}
      {sales && <Group title="Payments from customers" rows={[
        ["Paid in total", money(sales.paid)],
        ...Object.entries(sales.paid_by_method).map(([method, amount]) => [`Paid by ${(METHODS[method] || method).toLowerCase().replace("m-pesa", "M-Pesa")}`, money(amount)]),
        Number(sales.waiting_payments) > 0 && ["Waiting to be confirmed", money(sales.waiting_payments)],
        Number(sales.refunded_payments) > 0 && ["Given back to customers", money(sales.refunded_payments)],
        Number(sales.reversed_payments) > 0 && ["Recorded by mistake and undone", money(sales.reversed_payments)],
        Number(sales.failed_payments) > 0 && ["Failed (no money came in)", money(sales.failed_payments)],
      ]} />}
      {services && <Group title="Service jobs" rows={[
        ["Done", `${count(services.completed)} · ${money(services.completed_value)}`],
        ["Still being worked on", `${count(services.in_progress)} · ${money(services.in_progress_value)}`],
        ["Cancelled or refunded", count(services.cancelled)],
      ]} />}
      {mpesa && <Group title="M-Pesa agency" rows={[
        ["Outlets", count(mpesa.outlets)],
        ["Shifts", `${count(mpesa.shifts_closed)} closed · ${count(mpesa.shifts_open)} open`],
        ["Customer deposits", `${many(mpesa.deposits, "deposit", "deposits")} · ${money(mpesa.deposits_value)}`],
        ["Customer withdrawals", `${many(mpesa.withdrawals, "withdrawal", "withdrawals")} · ${money(mpesa.withdrawals_value)}`],
        Number(mpesa.airtime) > 0 && ["Airtime sold", `${many(mpesa.airtime, "sale", "sales")} · ${money(mpesa.airtime_value)}`],
        Number(mpesa.float_topups) > 0 && ["Float bought", money(mpesa.float_topups)],
        ["Commission earned", money(mpesa.commission)],
      ]} />}
      {cash && <Group title="Money spent, lent and invested" rows={[
        ["Running costs", `${many(cash.expenses, "bill", "bills")} · ${money(cash.expenses_value)}`],
        ["Money lent", `${many(cash.loans, "loan", "loans")} · ${money(cash.loans_value)}`],
        ["Still to be repaid", money(cash.loans_outstanding)],
        ["Investments", `${count(cash.investments)} · ${money(cash.investments_value)} held`],
      ]} />}
    </div>
    {mpesa && <p className="muted">M-Pesa deposits and withdrawals are customers' money, so they are not sales. Only the commission is the business's.</p>}
    {stock?.below_cost?.length > 0 && <div className="formNotice formNoticeInfo" role="note"><b>Check these prices: they sell for less than they cost you</b>
      <ul>{stock.below_cost.map(row => <li key={row.id}>{row.name}: {count(row.quantity)} in stock, cost {money(row.unit_cost)} each, selling price {money(row.selling_price)}.
        Either the buying cost or the selling price was entered wrong, or each one sold loses {money(Number(row.unit_cost) - Number(row.selling_price))}.</li>)}</ul>
    </div>}
  </section>;
}
