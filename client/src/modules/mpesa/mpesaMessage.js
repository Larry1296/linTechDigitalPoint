// Reads an M-Pesa confirmation message pasted by the operator, e.g.
// "SJK4ABC123 Confirmed. Ksh1,000.00 deposited to JANE WANJIRU 254712345678 on 26/9/26 at 10:15 AM. New M-PESA float balance is Ksh…"
// Only what is clearly there is taken: the transaction code (10 capital letters and digits), the first amount
// (the transaction; later amounts are balances and charges) and a Kenyan mobile number. Anything missing stays blank.
export function readMpesaMessage(text) {
  const message = String(text || "");
  const code = message.match(/\b(?=[A-Z0-9]{10}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)([A-Z0-9]{10})\b/)?.[1] || "";
  const amount = message.match(/K\s?sh\.?\s?([\d,]+(?:\.\d{1,2})?)/i)?.[1]?.replace(/,/g, "") || "";
  const number = message.match(/(?:\+?254|\b0)\s?([17]\d{2})\s?(\d{3})\s?(\d{3})\b/);
  const phone = number ? `0${number[1]}${number[2]}${number[3]}` : "";
  return { code, amount, phone };
}
