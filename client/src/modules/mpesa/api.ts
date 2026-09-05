import { api } from "../../core/api/client";
import type { MpesaDashboard, MpesaOutlet, MpesaSession, MpesaTransaction } from "./types";

export const getMpesaDashboard = () => api<MpesaDashboard>("/api/v1/mpesa/dashboard/");
export const getMpesaOutlets = () => api<MpesaOutlet[]>("/api/v1/mpesa/outlets/");
export const getMpesaTransactions = () => api<MpesaTransaction[]>("/api/v1/mpesa/transactions/");
export const openMpesaSession = (body: unknown) => api<MpesaSession>("/api/v1/mpesa/sessions/", { method: "POST", body: JSON.stringify(body) });
export const postMpesaTransaction = (body: unknown) => api<MpesaTransaction>("/api/v1/mpesa/transactions/", { method: "POST", body: JSON.stringify(body) });
export const reverseMpesaTransaction = (id: number, reason: string) => api<MpesaTransaction>(`/api/v1/mpesa/transactions/${id}/reverse/`, { method: "POST", body: JSON.stringify({ reason, idempotency_key: crypto.randomUUID() }) });
export const reconcileMpesaSession = (id: number, body: unknown) => api(`/api/v1/mpesa/sessions/${id}/reconcile/`, { method: "POST", body: JSON.stringify(body) });
