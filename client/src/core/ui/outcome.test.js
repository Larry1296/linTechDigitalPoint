import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Swal from "sweetalert2";
import { beginAction, mutationFinished, mutationStarted, setOutcomeOverlays, showOutcome } from "./outcome";

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
