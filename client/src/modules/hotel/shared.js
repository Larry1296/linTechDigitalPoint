import { businessCurrency } from "../../core/organization/presentation";

export const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
export const day = (value) => (value ? new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" }) : "—");
export const isoDay = (date) => date.toLocaleDateString("en-CA");
export const addDays = (iso, count) => { const date = new Date(`${iso}T12:00:00`); date.setDate(date.getDate() + count); return isoDay(date); };
export const nightsBetween = (from, to) => Math.max(0, Math.round((new Date(`${to}T12:00:00`) - new Date(`${from}T12:00:00`)) / 86400000));
export const can = (user, permission) => Boolean(user?.permissions?.includes(permission));
export const METHODS = [["CASH", "Cash"], ["MPESA", "M-Pesa"], ["BANK", "Bank"]];
export const methodName = (value) => ({ CASH: "Cash", MPESA: "M-Pesa", BANK: "Bank" }[value] || value);
export const ROOM_STATES = { OCCUPIED: "Guest in", BOOKED: "Booked", FREE: "Free", OUT_OF_ORDER: "Out of order" };
export const CONDITIONS = { READY: "Ready", DIRTY: "Needs cleaning", OUT: "Out of order" };
