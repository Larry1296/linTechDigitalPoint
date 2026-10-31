import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { centerNewForms } from "./centerForms";

let stop;
const scrolled = vi.fn();
beforeEach(() => {
  document.body.innerHTML = "<main></main>";
  HTMLElement.prototype.scrollIntoView = scrolled;
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((run) => { run(); return 0; });
  stop = centerNewForms();
});
afterEach(() => { stop(); scrolled.mockReset(); vi.restoreAllMocks(); });
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const open = (html) => { document.querySelector("main").insertAdjacentHTML("beforeend", html); };

it("brings a form opened by a click to the middle of the screen, ready to type in", async () => {
  window.dispatchEvent(new Event("pointerdown"));
  open("<section><form><input type='hidden' name='id'><input name='amount'></form></section>");
  await settle();
  expect(scrolled).toHaveBeenCalledWith(expect.objectContaining({ block: "center" }));
  expect(document.activeElement).toBe(document.querySelector("input[name='amount']"));
});

it("leaves forms alone that appear without the person doing anything, or inside a dialog", async () => {
  open("<form><input name='a'></form>");
  await settle();
  window.dispatchEvent(new Event("pointerdown"));
  open("<div role='dialog'><form><input name='b'></form></div>");
  await settle();
  expect(scrolled).not.toHaveBeenCalled();
});

it("keeps the field the form focused itself", async () => {
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
  open("<form><input name='first'><input name='second' id='second'></form>");
  document.getElementById("second").focus();
  await settle();
  expect(scrolled).toHaveBeenCalled();
  expect(document.activeElement.id).toBe("second");
});
