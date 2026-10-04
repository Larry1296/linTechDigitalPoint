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

// "Sales 1,150 − cost of what you sold 700 − running costs 0 + stock found 120 = 570 profit"
export function profitSum({ sales, cost, expenses, stock, profit }, money) {
  const parts = [`Sales ${money(sales)}`, `− what the sold items cost you ${money(cost)}`, `− running costs ${money(expenses)}`];
  if (Number(stock || 0)) parts.push(Number(stock) < 0 ? `+ stock found ${money(-Number(stock))}` : `− stock missing ${money(stock)}`);
  return `${parts.join(" ")} = ${profitText(profit, money)}`;
}
