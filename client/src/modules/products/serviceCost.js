import { businessCurrency } from "../../core/organization/presentation";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;

// A service whose cost is as much as its price makes no profit on any sale, and one with a cost but no price was almost
// certainly typed the wrong way round (2026-11-28: MIX TAPE saved as price 0, cost 10 counted every sale as all cost).
// Returns the warning to show, or "" when the price and cost look right.
export function serviceCostWarning(price, cost) {
  const p = Number(price) || 0;
  const c = Number(cost) || 0;
  if (c <= 0) return "";
  if (p <= 0) return `The price is ${money(0)} but the service cost is ${money(c)}. Were they typed the wrong way round? `
    + "As it is, every sale counts all its money as cost and none as profit.";
  if (c >= p) return `The service cost (${money(c)}) is ${c === p ? "the same as" : "more than"} the price (${money(p)}), so each sale makes no profit. `
    + "Check they are not the wrong way round.";
  return "";
}
