import { api } from "../../core/api/client";
export const loadZones = () => api("/api/v1/locations/zones/");
export const createZone = (payload) =>
  api("/api/v1/locations/zones/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const createStack = (payload) =>
  api("/api/v1/locations/stacks/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const updateStack = (id, payload) =>
  api(`/api/v1/locations/stacks/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
export const removeStack = (id) =>
  api(`/api/v1/locations/stacks/${id}/`, { method: "DELETE" });
export const updateShelf = (id, payload) =>
  api(`/api/v1/locations/shelves/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
export const loadShelfContents = (id) =>
  api(`/api/v1/locations/shelves/${id}/contents/`);
