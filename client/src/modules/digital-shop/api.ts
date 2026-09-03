import { api } from "../../core/api/client";
import type { ShelfStack, Zone } from "../../types";

export const loadZones = () => api<Zone[]>("/api/v1/locations/zones/");
export const createZone = (payload: {
  name: string;
  width: number;
  height: number;
}) =>
  api<Zone>("/api/v1/locations/zones/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const createStack = (payload: unknown) =>
  api<ShelfStack>("/api/v1/locations/stacks/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const updateStack = (id: number, payload: unknown) =>
  api<ShelfStack>(`/api/v1/locations/stacks/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
export const removeStack = (id: number) =>
  api<void>(`/api/v1/locations/stacks/${id}/`, { method: "DELETE" });
export const updateShelf = (id: number, payload: unknown) =>
  api(`/api/v1/locations/shelves/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
export const loadShelfContents = (id: number) =>
  api<ShelfContents>(`/api/v1/locations/shelves/${id}/contents/`);

export type ShelfContents = {
  shelf: { code: string; display_name: string; physical_label: string };
  items: {
    variant_id: number;
    product: string;
    variant: string;
    quantity: string;
    reserved: string;
    available: string;
    cost_value: string;
    retail_value: string;
  }[];
  recent_movements: { type: string; quantity: string; reference: string }[];
};
