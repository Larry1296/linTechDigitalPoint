import { useEffect, useState } from "react";
import { api } from "../../core/api/client";

// The kinds of business and the tools each can use come from the server, so registration and settings follow one set of rules.
export function useBusinessProfiles() {
  const [catalogue, setCatalogue] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    api("/api/v1/tenancy/business-profiles/").then((data) => live && setCatalogue(data)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, []);
  return { catalogue, error };
}

export const moduleLabel = (catalogue, id) => catalogue.modules.find((module) => module.id === id)?.label || id;
export const allowedModules = (catalogue, model) => catalogue.models.find((item) => item.id === model)?.modules || [];

export const COUNTRIES = [
  { code: "KE", name: "Kenya", currency: "KES", timezone: "Africa/Nairobi" },
  { code: "UG", name: "Uganda", currency: "UGX", timezone: "Africa/Kampala" },
  { code: "TZ", name: "Tanzania", currency: "TZS", timezone: "Africa/Dar_es_Salaam" },
  { code: "RW", name: "Rwanda", currency: "RWF", timezone: "Africa/Kigali" },
  { code: "BI", name: "Burundi", currency: "BIF", timezone: "Africa/Bujumbura" },
  { code: "SS", name: "South Sudan", currency: "SSP", timezone: "Africa/Juba" },
  { code: "ET", name: "Ethiopia", currency: "ETB", timezone: "Africa/Addis_Ababa" },
  { code: "SO", name: "Somalia", currency: "SOS", timezone: "Africa/Mogadishu" },
  { code: "CD", name: "DR Congo", currency: "CDF", timezone: "Africa/Kinshasa" },
  { code: "ZM", name: "Zambia", currency: "ZMW", timezone: "Africa/Lusaka" },
  { code: "MW", name: "Malawi", currency: "MWK", timezone: "Africa/Blantyre" },
  { code: "NG", name: "Nigeria", currency: "NGN", timezone: "Africa/Lagos" },
  { code: "GH", name: "Ghana", currency: "GHS", timezone: "Africa/Accra" },
  { code: "ZA", name: "South Africa", currency: "ZAR", timezone: "Africa/Johannesburg" },
  { code: "AE", name: "United Arab Emirates", currency: "AED", timezone: "Asia/Dubai" },
  { code: "IN", name: "India", currency: "INR", timezone: "Asia/Kolkata" },
  { code: "GB", name: "United Kingdom", currency: "GBP", timezone: "Europe/London" },
  { code: "US", name: "United States", currency: "USD", timezone: "America/New_York" },
];
export const CURRENCIES = [...new Set([...COUNTRIES.map((country) => country.currency), "EUR", "CNY"])].sort();

export function timeZones() {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return [...new Set(COUNTRIES.map((country) => country.timezone))].sort();
  }
}

// Turning a tool on also turns on something it needs; turning one off also turns off tools left without what they need.
export function toggleModule(catalogue, model, selected, id) {
  const next = new Set(selected);
  const notes = [];
  const label = (module) => moduleLabel(catalogue, module);
  const needsOf = (module) => catalogue.modules.find((item) => item.id === module)?.needs || [];
  if (next.has(id)) {
    next.delete(id);
    for (const module of catalogue.modules) {
      const needs = needsOf(module.id);
      if (next.has(module.id) && needs.length && !needs.some((need) => next.has(need))) {
        next.delete(module.id);
        notes.push(`${module.label} was turned off because it needs ${needs.map(label).join(" or ")}.`);
      }
    }
  } else {
    next.add(id);
    const needs = needsOf(id);
    const available = needs.filter((need) => allowedModules(catalogue, model).includes(need));
    if (needs.length && !needs.some((need) => next.has(need)) && available.length) {
      next.add(available[0]);
      notes.push(`${label(available[0])} was turned on because ${label(id)} needs it.`);
    }
  }
  return { modules: next, notes };
}

// The first reason a set of tools does not suit the business, or "". The server checks the same rules.
function moduleProblem(catalogue, model, modules) {
  const rules = catalogue.models.find((item) => item.id === model);
  const label = (module) => moduleLabel(catalogue, module);
  if (!modules.size) return "Choose at least one tool.";
  if (!rules.requires.some((module) => modules.has(module))) return `Turn on ${rules.requires.map(label).join(" or ")}.`;
  return "";
}

// How the business makes money follows from the tools it uses, as on the server: goods (products, shelves, a menu),
// services (services, rooms), or both. Nothing is picked from a list.
const GOODS_TOOLS = ["inventory", "locations", "menu"];
const SERVICE_TOOLS = ["services", "rooms"];
export function modelFor(modules) {
  const has = (list) => list.some((id) => modules.has(id));
  if (has(GOODS_TOOLS) && has(SERVICE_TOOLS)) return "MIXED";
  return has(GOODS_TOOLS) ? "GOODS" : "SERVICES";
}

// The first thing missing before the business can be set up with these tools, or "".
export function setupProblem(catalogue, modules) {
  if (!catalogue.activities.some((activity) => modules.has(activity.id))) return "Tick at least one thing your business does to earn money.";
  return moduleProblem(catalogue, modelFor(modules), modules);
}

// The first plan on offer (in the platform owner's order) that includes every chosen tool, or null.
export const planFor = (plans, modules) => (plans || []).find((plan) => [...modules].every((id) => plan.enabled_modules.includes(id))) || null;

// What the owner's description suggests ticking, and a starter list (from the server, which knows every listed kind).
export async function suggestFor(description, size) {
  const query = new URLSearchParams({ q: description.slice(0, 1000), size });
  return api(`/api/v1/tenancy/business-profiles/suggest/?${query}`);
}
