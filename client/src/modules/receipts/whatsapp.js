const CALLING_CODES = { KE: "254", UG: "256", TZ: "255", RW: "250", NG: "234", GH: "233", ZA: "27" };

// Turns what staff type ("0712 345 678", "+254712345678") into the digits wa.me expects.
export function whatsappNumber(input, country = "KE") {
  const raw = String(input || "").trim();
  let digits = raw.replace(/[^\d]/g, "");
  if (!digits) return "";
  if (raw.startsWith("+") || raw.startsWith("00")) return digits.replace(/^00/, "");
  const code = CALLING_CODES[country];
  if (code && digits.startsWith("0")) return code + digits.slice(1);
  if (code && digits.length <= 9) return code + digits;
  return digits;
}

export function whatsappLink(number, receipt, link) {
  const currency = receipt.currency === "KES" ? "KSh" : receipt.currency;
  const greeting = receipt.customer && receipt.customer !== "Walk-in customer" ? `Hello ${receipt.customer}, thank` : "Thank";
  const text = `${greeting} you for shopping at ${receipt.business.name}.\nReceipt ${receipt.number} · Total ${currency} ${Number(receipt.total).toLocaleString("en-KE", { minimumFractionDigits: 2 })}\nView your receipt: ${link}`;
  return `https://wa.me/${number}?text=${encodeURIComponent(text)}`;
}
