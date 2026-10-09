import { api, apiBlob } from "../../core/api/client";
export const getMpesaDashboard = () => api("/api/v1/mpesa/dashboard/");
export const getMpesaOutlets = () => api("/api/v1/mpesa/outlets/");
export const createMpesaOutlet = (body) =>
  api("/api/v1/mpesa/outlets/", { method: "POST", body: JSON.stringify(body) });
// Only transactions in open shifts: the desk starts afresh when a shift closes.
export const getMpesaTransactions = () => api("/api/v1/mpesa/transactions/?shift=open");
// Closed shifts that hold records, newest first, and one shift's records, so a cleared desk's records can be looked at again.
export const getPastMpesaShifts = () => api("/api/v1/mpesa/sessions/past/");
export const getMpesaShiftTransactions = (id) => api(`/api/v1/mpesa/transactions/?session=${encodeURIComponent(id)}`);
export const openMpesaSession = (body) =>
  api("/api/v1/mpesa/sessions/", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const postMpesaTransaction = (body) =>
  api("/api/v1/mpesa/transactions/", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const reverseMpesaTransaction = (id, reason) =>
  api(`/api/v1/mpesa/transactions/${id}/reverse/`, {
    method: "POST",
    body: JSON.stringify({ reason, idempotency_key: crypto.randomUUID() }),
  });
export const reconcileMpesaSession = (id, body) =>
  api(`/api/v1/mpesa/sessions/${id}/reconcile/`, {
    method: "POST",
    body: JSON.stringify(body),
  });
export const updateMpesaOutlet = (id, body) =>
  api(`/api/v1/mpesa/outlets/${id}/`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteMpesaOutlet = (id) =>
  api(`/api/v1/mpesa/outlets/${id}/`, { method: "DELETE" });
export const addMpesaReference = (id, providerReference) =>
  api(`/api/v1/mpesa/transactions/${id}/reference/`, {
    method: "POST",
    body: JSON.stringify({ provider_reference: providerReference }),
  });
export const getMpesaReportMonths = () => api("/api/v1/mpesa/reports/months/");
export const downloadMpesaReport = (month) => apiBlob(`/api/v1/mpesa/reports/monthly/?month=${encodeURIComponent(month)}`);
export const correctMpesaTransaction = (id, body) =>
  api(`/api/v1/mpesa/transactions/${id}/correct/`, {
    method: "POST",
    body: JSON.stringify({ ...body, idempotency_key: crypto.randomUUID() }),
  });
export const lookupMpesaCustomer = (phone) => api(`/api/v1/mpesa/customers/lookup/?phone=${encodeURIComponent(phone)}`);
// Whether to ask for the commission balance after a transaction, or the commission the app has already learned for it.
export const getCommissionAdvice = (session, type, amount) =>
  api(`/api/v1/mpesa/transactions/commission-advice/?session=${encodeURIComponent(session)}&type=${encodeURIComponent(type)}&amount=${encodeURIComponent(amount)}`);
// The agency's last working days, busiest hours, transaction sizes and commission by kind.
export const getMpesaAnalysis = (days = 30) => api(`/api/v1/mpesa/analysis/?days=${encodeURIComponent(days)}`);
