import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ChatWidget } from "./ChatWidget";

const widget = () => <ChatWidget storageKey="resize-test" historyKey="resize-q" title="Assistant" subtitle="" greeting="Hi" launcherLabel="Ask"
  inputId="resize-input" send={vi.fn()} />;

beforeEach(() => {
  localStorage.clear();
  window.innerWidth = 1400;
  // The panel sits 20px above the bottom of an 900px-high window; the navbar ends at 116px.
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function rect() {
    return this.classList.contains("workspaceTopbar") ? { bottom: 116 } : { bottom: 812 };
  });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(520);
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(620);
  document.body.innerHTML = '<header class="workspaceTopbar"></header>';
});
afterEach(() => vi.restoreAllMocks());

it("maximises to half the screen and up to just below the navbar, restores to its usual size, and remembers it", async () => {
  const { unmount } = render(widget());
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  const panel = screen.getByRole("dialog");
  expect(panel.style.width).toBe("");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Make the chat bigger" })); });
  expect(panel.style.width).toBe("700px");
  expect(panel.style.height).toBe(`${812 - 116 - 12}px`);
  unmount();
  render(widget());
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  expect(screen.getByRole("dialog").style.width).toBe("700px");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Make the chat smaller" })); });
  expect(screen.getByRole("dialog").style.width).toBe("");
});

it("never goes below its usual size or past the navbar with the keyboard", async () => {
  render(widget());
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  const grip = screen.getByRole("separator", { name: /Resize the chat/ });
  fireEvent.keyDown(grip, { key: "ArrowRight" });
  expect(screen.getByRole("dialog").style.width).toBe("");
  fireEvent.keyDown(grip, { key: "ArrowLeft" });
  expect(screen.getByRole("dialog").style.width).toBe("560px");
  for (let i = 0; i < 10; i += 1) fireEvent.keyDown(grip, { key: "ArrowUp" });
  expect(screen.getByRole("dialog").style.height).toBe("684px");
});
