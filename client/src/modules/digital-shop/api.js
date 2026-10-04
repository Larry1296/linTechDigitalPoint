import { api } from "../../core/api/client";
export const loadZones = () => api("/api/v1/locations/zones/");
// Shops that do not use Shelves & locations have no shelf map; their pages must still load (stock is kept unplaced).
export const usesShelves = (user) => Boolean(user?.organization?.enabled_modules?.includes("locations"));
export const loadZonesIfUsed = (user) => (usesShelves(user) ? loadZones() : Promise.resolve([]));
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
export const loadCategories = () => api("/api/v1/catalog/categories/");
export const saveCategory = (id, payload) =>
  api(`/api/v1/catalog/categories/${id ? `${id}/` : ""}`, {
    method: id ? "PATCH" : "POST",
    body: JSON.stringify(payload),
  });
export const deleteCategory = (id) =>
  api(`/api/v1/catalog/categories/${id}/`, { method: "DELETE" });
export const updateZone = (id, payload) =>
  api(`/api/v1/locations/zones/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
export const removeZone = (id) =>
  api(`/api/v1/locations/zones/${id}/`, { method: "DELETE" });
