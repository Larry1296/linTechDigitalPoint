import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SessionLockOverlay } from "./SessionLockOverlay";
import { forgetPasswordLength, rememberPasswordLength } from "./passwordLength";

beforeEach(() => { vi.useFakeTimers(); rememberPasswordLength("Safe-pass-1848"); });
afterEach(() => { vi.useRealTimers(); forgetPasswordLength(); });
const show = (onUnlock) => render(<SessionLockOverlay username="owner" pinLength={null} busy={false} error="" onUnlock={onUnlock} onPin={vi.fn()} onLogout={vi.fn()} />);
const field = () => screen.getByLabelText("Password");
const typeOut = async (text) => {
  for (let end = 1; end <= text.length; end += 1) await act(async () => { fireEvent.change(field(), { target: { value: text.slice(0, end) } }); });
};

it("opens at once when a saved or pasted password fills the field", async () => {
  const onUnlock = vi.fn(async () => true);
  show(onUnlock);
  await act(async () => { fireEvent.change(field(), { target: { value: "Safe-pass-1848" } }); });
  expect(onUnlock).toHaveBeenCalledWith("Safe-pass-1848", { quiet: true });
});

it("never tries a typed password part-way, even when typing pauses", async () => {
  const onUnlock = vi.fn(async () => true);
  show(onUnlock);
  await typeOut("Safe-pass-18");
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(onUnlock).not.toHaveBeenCalled();
});

it("tries a typed password quietly once it is as long as the real one, and keeps what was typed when it is wrong", async () => {
  const onUnlock = vi.fn(async () => false);
  show(onUnlock);
  await typeOut("Safe-pass-184x");
  expect(onUnlock).toHaveBeenCalledTimes(1);
  expect(onUnlock).toHaveBeenCalledWith("Safe-pass-184x", { quiet: true });
  expect(field()).toHaveValue("Safe-pass-184x");
});

it("waits for Enter when the password's length is not known", async () => {
  forgetPasswordLength();
  const onUnlock = vi.fn(async () => true);
  show(onUnlock);
  await typeOut("Safe-pass-1848");
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(onUnlock).not.toHaveBeenCalled();
  await act(async () => { fireEvent.submit(field().closest("form")); });
  expect(onUnlock).toHaveBeenLastCalledWith("Safe-pass-1848");
});

it("never tries a short pasted password, the same text twice, or more than twice per lock", async () => {
  forgetPasswordLength();
  const onUnlock = vi.fn(async () => false);
  show(onUnlock);
  const paste = async (value) => { fireEvent.change(field(), { target: { value: "" } }); await act(async () => { fireEvent.change(field(), { target: { value } }); }); };
  await paste("short");
  expect(onUnlock).not.toHaveBeenCalled();
  await paste("wrongpass1");
  await paste("wrongpass");
  await paste("wrongpass1");  // already tried
  await paste("wrongpass12");  // a third automatic try is not made: Enter still works
  expect(onUnlock.mock.calls.map(([value]) => value)).toEqual(["wrongpass1", "wrongpass"]);
  await act(async () => { fireEvent.submit(field().closest("form")); });
  expect(onUnlock).toHaveBeenLastCalledWith("wrongpass12");
});
