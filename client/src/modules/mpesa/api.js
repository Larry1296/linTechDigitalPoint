import { api } from "../../core/api/client";
export const getMpesaDashboard = () => api("/api/v1/mpesa/dashboard/");
export const getMpesaOutlets = () => api("/api/v1/mpesa/outlets/");
export const getMpesaTransactions = () => api("/api/v1/mpesa/transactions/");
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
