import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SessionLockOverlay } from "./SessionLockOverlay";

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });
const show = (onUnlock) => render(<SessionLockOverlay locked seconds={0} username="owner" busy={false} error="" onStay={vi.fn()} onUnlock={onUnlock} onLogout={vi.fn()} />);
const field = () => screen.getByLabelText("Password");

it("opens at once when a saved or pasted password fills the field", async () => {
  const onUnlock = vi.fn(async () => true);
  show(onUnlock);
  await act(async () => { fireEvent.change(field(), { target: { value: "Safe-pass-1848" } }); });
  expect(onUnlock).toHaveBeenCalledWith("Safe-pass-1848", { quiet: true });
});

it("tries a typed password once typing pauses, quietly, and keeps what was typed when it is wrong", async () => {
  const onUnlock = vi.fn(async () => false);
  show(onUnlock);
  for (const value of ["S", "Sa", "Saf", "Safe", "Safe-", "Safe-p", "Safe-pa", "Safe-pas"]) fireEvent.change(field(), { target: { value } });
  expect(onUnlock).not.toHaveBeenCalled();  // still typing
  await act(async () => { vi.advanceTimersByTime(1000); });
  expect(onUnlock).toHaveBeenCalledTimes(1);
  expect(onUnlock).toHaveBeenCalledWith("Safe-pas", { quiet: true });
  expect(field()).toHaveValue("Safe-pas");
});

it("never tries a short password, the same text twice, or more than twice per lock", async () => {
  const onUnlock = vi.fn(async () => false);
  show(onUnlock);
  const type = async (value) => { fireEvent.change(field(), { target: { value } }); await act(async () => { vi.advanceTimersByTime(1000); }); };
  await type("short");
  expect(onUnlock).not.toHaveBeenCalled();
  await type("wrongpass1");
  await type("wrongpass");
  await type("wrongpass1");  // already tried
  await type("wrongpass12");  // a third automatic try is not made: Enter still works
  expect(onUnlock.mock.calls.map(([value]) => value)).toEqual(["wrongpass1", "wrongpass"]);
  await act(async () => { fireEvent.submit(field().closest("form")); });
  expect(onUnlock).toHaveBeenLastCalledWith("wrongpass12");
});
