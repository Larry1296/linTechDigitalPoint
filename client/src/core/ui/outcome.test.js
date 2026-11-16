import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Swal from "sweetalert2";
import { beginAction, mutationFinished, mutationStarted, pageRoot, setOutcomeNavigate, setOutcomeOverlays, showOutcome } from "./outcome";

let form;
beforeEach(() => {
  vi.useFakeTimers();
  vi.restoreAllMocks();
  vi.spyOn(Swal, "fire").mockResolvedValue({ isConfirmed: true });
  setOutcomeOverlays(true);
  document.body.innerHTML = '<form><h2>Customer deposit</h2><input name="amount" value=""></form>';
  form = document.querySelector("form");
  form.querySelector("input").value = "4200";
});
afterEach(() => { setOutcomeOverlays(false); vi.useRealTimers(); });

const submit = () => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

it("covers the screen when a submitted form saves, then clears the form", async () => {
  submit();
  expect(mutationStarted("/api/v1/mpesa/transactions/")).toBe(true);
  mutationFinished(true);
  await vi.advanceTimersByTimeAsync(1000);
  expect(Swal.fire).toHaveBeenCalledWith(expect.objectContaining({ icon: "success", title: "Saved", text: "Customer deposit", timer: 1600, showConfirmButton: false }));
  expect(form.querySelector("input").value).toBe("");
});

it("shows the page's own success message instead of a plain one", async () => {
  submit();
  mutationStarted("/api/v1/mpesa/transactions/");
  mutationFinished(true);
  await showOutcome("success", "Done", "Recorded deposit of KSh 4,200.");
  await vi.advanceTimersByTimeAsync(1000);
  expect(Swal.fire).toHaveBeenCalledTimes(1);
  expect(Swal.fire.mock.calls[0][0]).toEqual(expect.objectContaining({ text: "Recorded deposit of KSh 4,200.", showConfirmButton: false }));
  expect(form.querySelector("input").value).toBe("");
});

it("does not close a question already on screen with a success note", async () => {
  vi.spyOn(Swal, "isVisible").mockReturnValue(true);
  vi.spyOn(Swal, "getPopup").mockReturnValue(Object.assign(document.createElement("div"), { className: "swal2-popup" }));
  submit();
  mutationStarted("/api/v1/locations/stacks/4/");
  mutationFinished(true);
  await vi.advanceTimersByTimeAsync(1000);
  expect(Swal.fire).not.toHaveBeenCalled();
  expect(form.querySelector("input").value).toBe("");
});

it("covers the screen with the error and keeps what was typed", async () => {
  submit();
  mutationStarted("/api/v1/mpesa/transactions/");
  mutationFinished(false, "Insufficient electronic float for this operation.");
  await vi.advanceTimersByTimeAsync(1000);
  expect(Swal.fire).toHaveBeenCalledTimes(1);
  expect(Swal.fire).toHaveBeenCalledWith(expect.objectContaining({ icon: "error", text: "Insufficient electronic float for this operation.", confirmButtonText: "Close" }));
  expect(form.querySelector("input").value).toBe("4200");
});

it("counts a confirmed dialog as a save, but not reading data or signing in", async () => {
  expect(mutationStarted("/api/v1/mpesa/transactions/")).toBe(false); // nothing submitted or confirmed
  submit();
  expect(mutationStarted("/api/v1/auth/login/")).toBe(false);
  beginAction();
  mutationStarted("/api/v1/mpesa/transactions/9/reverse/");
  mutationFinished(true);
  await vi.advanceTimersByTimeAsync(1000);
  expect(Swal.fire).toHaveBeenCalledWith(expect.objectContaining({ icon: "success", title: "Saved" }));
});

const saveOn = async (path) => {
  window.history.replaceState({ idx: 3 }, "", path);
  const back = vi.spyOn(window.history, "back").mockImplementation(() => {});
  const go = vi.fn();
  setOutcomeNavigate(go);
  submit();
  mutationStarted("/api/v1/anything/");
  mutationFinished(true);
  await vi.advanceTimersByTimeAsync(1000);
  setOutcomeNavigate(null);
  expect(back).not.toHaveBeenCalled();  // never back to whatever page was open before
  return go;
};

it("after a save goes to the page's own main view, never the page open before", async () => {
  expect(await saveOn("/admin/products?edit=5")).toHaveBeenCalledWith("/admin/products");
  expect(await saveOn("/admin/receipts/12")).toHaveBeenCalledWith("/admin/receipts");
  expect(await saveOn("/admin/quick-receive?variant=9")).toHaveBeenCalledWith("/admin/quick-receive");
});

it("stays on a page that is already its own main view, ready for the next entry", async () => {
  expect(await saveOn("/admin/quick-receive")).not.toHaveBeenCalled();
  expect(await saveOn("/admin/investments")).not.toHaveBeenCalled();
});

it("keeps the till, the M-Pesa agency and other entry-after-entry screens as they are", async () => {
  expect(await saveOn("/admin/pos?sale=3")).not.toHaveBeenCalled();
  expect(await saveOn("/admin/mpesa/transactions?x=1")).not.toHaveBeenCalled();
  expect(await saveOn("/admin/to-buy?x=1")).not.toHaveBeenCalled();
});

it("leaves a form in a dialog where it is", async () => {
  form.setAttribute("role", "dialog");
  expect(await saveOn("/admin/expenses?edit=2")).not.toHaveBeenCalled();
});

it("finds a page's main view", () => {
  expect(pageRoot("/admin/rooms/stays/5")).toBe("/admin/rooms");
  expect(pageRoot("/admin/cyber/income/4")).toBe("/admin/cyber/income");
  expect(pageRoot("/admin/chama/setup")).toBe("/admin/chama/setup");
});
