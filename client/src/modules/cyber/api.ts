import { api } from "../../core/api/client";
import type { CyberDashboard, CyberJob, CyberService } from "./types";

export const getCyberDashboard = () => api<CyberDashboard>("/api/v1/cyber/dashboard/");
export const getCyberServices = () => api<CyberService[]>("/api/v1/cyber/services/");
export const getCyberJobs = () => api<CyberJob[]>("/api/v1/cyber/jobs/");
export const createCyberJob = (body: unknown) => api<CyberJob>("/api/v1/cyber/jobs/", { method: "POST", body: JSON.stringify(body) });
export const transitionCyberJob = (id: number, status: string) => api<CyberJob>(`/api/v1/cyber/jobs/${id}/transition/`, { method: "POST", body: JSON.stringify({ status }) });
export const completeCyberJob = (id: number, body: unknown) => api<{ receipt_number: string; total: string }>(`/api/v1/cyber/jobs/${id}/complete/`, { method: "POST", body: JSON.stringify(body) });
