import { api } from "../../core/api/client";
export const getCyberDashboard = () => api("/api/v1/cyber/dashboard/");
export const getCyberServices = () => api("/api/v1/cyber/services/");
export const getCyberJobs = () => api("/api/v1/cyber/jobs/");
export const createCyberJob = (body) =>
  api("/api/v1/cyber/jobs/", { method: "POST", body: JSON.stringify(body) });
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
