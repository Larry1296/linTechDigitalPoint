// Plain-language money for owners who are not accountants: a loss is written as a loss, never as a minus sign.

// "KSh 570 profit", "KSh 200 loss" or "Break-even (KSh 0)".
export function profitText(value, money) {
  if (value == null) return money(value);
  const number = Number(value);
  if (number > 0) return `${money(number)} profit`;
  if (number < 0) return `${money(-number)} loss`;
  return `Break-even (${money(0)})`;
}

// Stock count corrections are kept like an expense (a loss is positive): show them as found or missing stock.
export function stockText(value, money) {
  const number = Number(value || 0);
  if (!number) return money(0);
  return number < 0 ? `+ ${money(-number)} (stock found)` : `− ${money(number)} (stock missing)`;
}

// Interest from investments less their fees: "+ KSh 120 (interest on investments)", or a loss when fees were more.
export function interestText(value, money) {
  const number = Number(value || 0);
  if (!number) return money(0);
  return number > 0 ? `+ ${money(number)} (interest on investments)` : `− ${money(-number)} (investment fees)`;
}

// The profit in sales customers have not paid for yet: taken off until they pay. Below zero when more was paid off
// in the dates than newly owed, which adds profit from earlier sales.
export function owedText(value, money) {
  const number = Number(value || 0);
  if (!number) return money(0);
  return number > 0 ? `− ${money(number)} (still owed by customers)` : `+ ${money(-number)} (paid for earlier sales)`;
}

// "Sales 1,150 − cost of what you sold 700 − running costs 0 + stock found 120 + interest on investments 60
//  − profit still owed by customers 100 = 530 profit"
// ``investing``: the business uses investments, so their interest is always shown, even before any is recorded.
export function profitSum({ sales, cost, expenses, stock, interest, owed, profit, investing = false }, money) {
  const parts = [`Sales ${money(sales)}`, `− what the sold items cost you ${money(cost)}`, `− running costs ${money(expenses)}`];
  if (Number(stock || 0)) parts.push(Number(stock) < 0 ? `+ stock found ${money(-Number(stock))}` : `− stock missing ${money(stock)}`);
  if (investing || Number(interest || 0)) parts.push(Number(interest || 0) >= 0 ? `+ interest on investments ${money(interest)}` : `− investment fees ${money(-Number(interest))}`);
  if (Number(owed || 0)) parts.push(Number(owed) > 0 ? `− profit still owed by customers ${money(owed)}` : `+ profit paid for earlier sales ${money(-Number(owed))}`);
  return `${parts.join(" ")} = ${profitText(profit, money)}`;
}
