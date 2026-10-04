// Plain words for the codes the server stores, so every screen names things the same way.
// An unknown code is shown tidied ("SOME_CODE" → "Some code") rather than hidden.

export const PAYMENT_METHODS = [["CASH", "Cash"], ["MPESA", "Lipa na M-Pesa (till)"], ["BANK", "Bank"], ["OTHER", "Other"]];

const WORDS = {
  ...Object.fromEntries(PAYMENT_METHODS),
  CASH_ON_PICKUP: "Cash on pickup",
  // Sales and payments
  COMPLETED: "Completed", PENDING: "Waiting", MANUAL_REVIEW: "Waiting for confirmation", FAILED: "Failed",
  REFUNDED: "Returned and refunded", REVERSED: "Reversed (not received)",
  // Orders and jobs
  AWAITING_PAYMENT: "Waiting for payment", PAID: "Paid", PROCESSING: "Being prepared", READY_FOR_PICKUP: "Ready for pickup",
  OUT_FOR_DELIVERY: "Out for delivery", CANCELLED: "Cancelled", IN_PROGRESS: "In progress", OPEN: "Open", QUEUED: "Waiting",
  // Stock movements
  OPENING_STOCK: "Opening stock", PURCHASE_RECEIPT: "Received from supplier", SALE: "Sold", ONLINE_ORDER: "Online order",
  CYBER_CONSUMPTION: "Used for a service", TRANSFER: "Moved", CUSTOMER_RETURN: "Customer return", SALE_RETURN: "Customer return",
  SUPPLIER_RETURN: "Returned to supplier", DAMAGE: "Damaged", LOSS: "Lost", STOCKTAKE_ADJUSTMENT: "Stock count correction",
  STOCK_ADJUSTMENT: "Stock correction", MANUAL_ADJUSTMENT: "Manual correction", ORDER_RESERVATION: "Held for an order",
  RESERVATION_RELEASE: "Released from an order",
  // Supplier payment on receipts
  SUPPLIER_INVOICE: "On the supplier's invoice",
};

export function label(code) {
  if (code === null || code === undefined || code === "") return "";
  const text = String(code);
  return WORDS[text] || text.charAt(0) + text.slice(1).toLowerCase().replaceAll("_", " ");
}
