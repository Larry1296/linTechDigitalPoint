// What money in a money market fund could earn. Funds such as CIC's work interest out daily at the yearly rate ÷ 365
// and add it at the end of each month after withholding tax, so it earns interest from then on. A guide only:
// the rate changes from month to month.

const round = (value) => Math.round(value * 100) / 100;

/** Interest earned per day and per month on a balance, after tax. */
export function earnings(balance, annualRate, taxRate = 15) {
  const keep = 1 - Number(taxRate || 0) / 100;
  const daily = (Number(balance || 0) * Number(annualRate || 0)) / 100 / 365;
  return { day: round(daily * keep), month: round(((daily * 365) / 12) * keep), year: round(daily * 365 * keep) };
}

/**
 * Month by month: the amount put in at the start, plus a top-up at the start of each later month.
 * Returns the rows and the totals: put in, interest before tax, tax, interest after tax and the balance at the end.
 */
export function projectInterest({ amount, annualRate, months, topUp = 0, taxRate = 15 }) {
  const rate = Number(annualRate || 0) / 100;
  const tax = Number(taxRate || 0) / 100;
  const count = Math.max(0, Math.min(600, Math.floor(Number(months || 0))));
  let balance = Number(amount || 0);
  let putIn = balance;
  let gross = 0;
  let taxed = 0;
  const rows = [];
  for (let month = 1; month <= count; month += 1) {
    const added = month > 1 ? Number(topUp || 0) : 0;
    balance += added;
    putIn += added;
    const interest = (balance * rate) / 12;
    const withheld = interest * tax;
    balance += interest - withheld;
    gross += interest;
    taxed += withheld;
    rows.push({ month, added: round(added), interest: round(interest - withheld), tax: round(withheld), balance: round(balance) });
  }
  return { rows, putIn: round(putIn), gross: round(gross), tax: round(taxed), net: round(gross - taxed), balance: round(balance) };
}
