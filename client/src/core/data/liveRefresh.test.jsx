import { act, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { announceDataChanged, useLiveRefresh } from "./liveRefresh";
import { api } from "../api/client";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

function Page({ load }) {
  useLiveRefresh(load);
  return null;
}

it("refreshes once after a burst of changes, without a manual reload", () => {
  vi.useFakeTimers();
  const load = vi.fn(async () => {});
  render(<Page load={load} />);
  act(() => { announceDataChanged("/api/v1/commerce/pos/complete/"); announceDataChanged("/api/v1/commerce/sales/1/payments/"); });
  act(() => vi.advanceTimersByTime(300));
  expect(load).toHaveBeenCalledOnce();
});

it("announces a saved change but not a read or a failed save", async () => {
  const heard = vi.fn();
  window.addEventListener("lintech:data-changed", heard);
  const reply = (status) => Promise.resolve(new Response(JSON.stringify({ id: 1 }), { status, headers: { "Content-Type": "application/json" } }));
  vi.spyOn(globalThis, "fetch").mockImplementation((url) => (String(url).includes("/auth/csrf/") ? reply(200).then((r) => r) : reply(200)));
  await api("/api/v1/inventory/stock-check/");
  expect(heard).not.toHaveBeenCalled();
  await api("/api/v1/inventory/stock-check/", { method: "POST", body: "{}" });
  expect(heard).toHaveBeenCalledOnce();
  globalThis.fetch.mockImplementation((url) => (String(url).includes("/auth/csrf/") ? reply(200) : reply(400)));
  await api("/api/v1/inventory/stock-check/", { method: "POST", body: "{}" }).catch(() => {});
  expect(heard).toHaveBeenCalledOnce();
  window.removeEventListener("lintech:data-changed", heard);
});
