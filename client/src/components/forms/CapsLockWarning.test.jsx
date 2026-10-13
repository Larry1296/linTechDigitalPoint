import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { CapsLockWarning } from "./CapsLockWarning";
import { PasswordField } from "./PasswordField";

// jsdom's key events do not carry Caps Lock, so each event says whether it is on, as a browser's would.
const key = (element, type, capsLock, keyName = "a") => {
  const event = new KeyboardEvent(type, { key: keyName, bubbles: true });
  event.getModifierState = (name) => name === "CapsLock" && capsLock;
  act(() => { element.dispatchEvent(event); });
};

it("warns under a password box while Caps Lock is on, also with the password shown, and not in other boxes", async () => {
  render(<><CapsLockWarning /><PasswordField name="password" /><input aria-label="Username" /></>);
  const password = screen.getByLabelText("Password");
  password.focus();
  key(password, "keydown", true);
  expect(await screen.findByRole("status")).toHaveTextContent("Caps Lock is on.");
  key(password, "keyup", false, "CapsLock");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Show password"));  // shown as plain text: still a password
  key(password, "keydown", true);
  expect(await screen.findByRole("status")).toBeInTheDocument();
  fireEvent.focusOut(password);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  key(screen.getByLabelText("Username"), "keydown", true);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
