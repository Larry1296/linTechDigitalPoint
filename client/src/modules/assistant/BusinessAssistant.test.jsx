import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, apiStream, ApiError } from "../../core/api/client";
import { BusinessAssistant } from "./BusinessAssistant";

vi.mock("../../core/api/client", async (original) => ({ ...(await original()), api: vi.fn(), apiStream: vi.fn() }));

function streamed(events) {
  const bytes = new TextEncoder().encode(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""));
  const chunks = [bytes.slice(0, 25), bytes.slice(25)];
  return { ok: true, status: 200, body: { getReader: () => ({ read: async () => (chunks.length ? { value: chunks.shift(), done: false } : { value: undefined, done: true }) }) } };
}
const SETTINGS = { provider: "anthropic", can_manage: true, providers: [{ id: "anthropic", label: "Claude (Anthropic)", available: true }, { id: "openai", label: "ChatGPT (OpenAI)", available: true }] };
const DUKA = { id: 7, name: "Duka" };
const show = (organization = DUKA) => render(<MemoryRouter><BusinessAssistant organization={organization} /></MemoryRouter>);
const openPanel = () => { fireEvent.click(screen.getByRole("button", { name: /Ask your assistant/ })); return screen.getByRole("dialog", { name: "Duka assistant" }); };

beforeEach(() => { sessionStorage.clear(); localStorage.clear(); api.mockResolvedValue(SETTINGS); });
afterEach(() => vi.clearAllMocks());

it("asks a suggested question and streams an answer that looked up the business's records", async () => {
  apiStream.mockResolvedValue(streamed([
    { type: "tool", name: "sales_statistics", label: "Analysing sales trends" },
    { type: "text", text: "Sales are **rising**: " }, { type: "text", text: "about 120 a day more." }, { type: "done" },
  ]));
  show();
  const panel = openPanel();
  fireEvent.click(within(panel).getByRole("button", { name: "How are my sales trending over the last 90 days?" }));
  expect(await within(panel).findByText(/about 120 a day more\./)).toBeInTheDocument();
  expect(within(panel).getByText("rising").tagName).toBe("STRONG");
  const [url, body] = apiStream.mock.calls[0];
  expect(url).toBe("/api/v1/business-assistant/chat/");
  expect(body).toEqual({ messages: [{ role: "user", content: "How are my sales trending over the last 90 days?" }] });
});

it("keeps each business's conversation separate", async () => {
  apiStream.mockResolvedValue(streamed([{ type: "text", text: "You have 8 chargers." }, { type: "done" }]));
  const { unmount } = show();
  const panel = openPanel();
  fireEvent.change(within(panel).getByLabelText("Your question"), { target: { value: "How many chargers?" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Send question" }));
  await within(panel).findByText("You have 8 chargers.");
  unmount();
  render(<MemoryRouter><BusinessAssistant organization={{ id: 8, name: "Rival" }} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: /Ask your assistant/ }));
  expect(screen.queryByText("You have 8 chargers.")).not.toBeInTheDocument();
  expect(JSON.parse(sessionStorage.getItem("business-assistant-7"))).toHaveLength(2);
});

it("lets an owner switch the AI provider", async () => {
  api.mockResolvedValueOnce(SETTINGS).mockResolvedValueOnce({ ...SETTINGS, provider: "openai" });
  show();
  const panel = openPanel();
  const picker = await within(panel).findByLabelText("AI provider");
  fireEvent.change(picker, { target: { value: "openai" } });
  await waitFor(() => expect(api).toHaveBeenLastCalledWith("/api/v1/business-assistant/settings/", { method: "PUT", body: JSON.stringify({ provider: "openai" }) }));
  await waitFor(() => expect(picker).toHaveValue("openai"));
});

it("hides the provider choice from staff and explains errors", async () => {
  api.mockResolvedValue({ ...SETTINGS, can_manage: false });
  apiStream.mockRejectedValueOnce(new ApiError(429, "Too many")).mockRejectedValueOnce(new ApiError(503, "The business assistant isn't set up on this platform yet."));
  show();
  const panel = openPanel();
  await waitFor(() => expect(api).toHaveBeenCalled());
  expect(within(panel).queryByLabelText("AI provider")).not.toBeInTheDocument();
  fireEvent.click(within(panel).getByRole("button", { name: "What is running low and how much should I reorder?" }));
  expect(await within(panel).findByText(/asking quickly/)).toBeInTheDocument();
  fireEvent.change(within(panel).getByLabelText("Your question"), { target: { value: "Hello?" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Send question" }));
  expect(await within(panel).findByText(/isn't set up on this platform yet/)).toBeInTheDocument();
});


it("brings back earlier questions with the up and down arrows, then what was being typed", async () => {
  apiStream.mockImplementation(async () => streamed([{ type: "text", text: "Done." }, { type: "done" }]));
  show();
  const panel = openPanel();
  const box = within(panel).getByLabelText("Your question");
  for (const question of ["What is in stock?", "Who owes me?"]) {
    fireEvent.change(box, { target: { value: question } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(within(panel).getAllByText("Done.").length).toBeGreaterThan(0));
    await waitFor(() => expect(within(panel).getByRole("button", { name: "Send question" })).toBeDisabled());
  }
  fireEvent.change(box, { target: { value: "half typed" } });
  box.setSelectionRange(0, 0);
  fireEvent.keyDown(box, { key: "ArrowUp" });
  expect(box).toHaveValue("Who owes me?");
  fireEvent.keyDown(box, { key: "ArrowUp" });
  expect(box).toHaveValue("What is in stock?");
  fireEvent.keyDown(box, { key: "ArrowUp" });
  expect(box).toHaveValue("What is in stock?");  // the oldest stays
  fireEvent.keyDown(box, { key: "ArrowDown" });
  expect(box).toHaveValue("Who owes me?");
  fireEvent.keyDown(box, { key: "ArrowDown" });
  expect(box).toHaveValue("half typed");
  // A new conversation keeps the history.
  fireEvent.click(within(panel).getByRole("button", { name: "Start a new conversation" }));
  fireEvent.change(box, { target: { value: "" } });
  fireEvent.keyDown(box, { key: "ArrowUp" });
  expect(box).toHaveValue("Who owes me?");
});

it("closes when the person clicks outside it, not inside", () => {
  show();
  const panel = openPanel();
  fireEvent.pointerDown(within(panel).getByLabelText("Your question"));
  expect(screen.getByRole("dialog", { name: "Duka assistant" })).toBeInTheDocument();
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("dialog", { name: "Duka assistant" })).toBeNull();
});
