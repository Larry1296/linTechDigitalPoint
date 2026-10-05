import { api } from "../../core/api/client";
export const getCyberDashboard = () => api("/api/v1/cyber/dashboard/");
export const getCyberServices = () => api("/api/v1/cyber/services/");
export const createCyberService = (body) =>
  api("/api/v1/cyber/services/", { method: "POST", body: JSON.stringify(body) });
export const updateCyberService = (id, body) =>
  api(`/api/v1/cyber/services/${id}/`, { method: "PATCH", body: JSON.stringify(body) });
export const getCyberJobs = () => api("/api/v1/cyber/jobs/");
export const createCyberJob = (body) =>
  api("/api/v1/cyber/jobs/", { method: "POST", body: JSON.stringify(body) });
export const deleteCyberJob = (id) => api(`/api/v1/cyber/jobs/${id}/`, { method: "DELETE" });
export const transitionCyberJob = (id, status) =>
  api(`/api/v1/cyber/jobs/${id}/transition/`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
export const completeCyberJob = (id, body) =>
  api(`/api/v1/cyber/jobs/${id}/complete/`, {
    method: "POST",
    body: JSON.stringify(body),
  });
// A paid service recorded wrongly: its whole sale is deleted (money out of that day's figures, off the desk and income).
export const deleteCyberSale = (saleId, reason) =>
  api(`/api/v1/commerce/sales/${saleId}/delete/`, { method: "POST", body: JSON.stringify({ reason }) });
