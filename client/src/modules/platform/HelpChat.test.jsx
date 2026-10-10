import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act } from "@testing-library/react";
import { Answer, HelpChat, openHelpChat } from "./HelpChat";

vi.mock("./PlatformContext", () => ({ usePlatform: () => ({ name: "DukaFlow" }) }));

// A streamed response made of server-sent events, split across chunks like a real network read.
function streamed(events) {
  const bytes = new TextEncoder().encode(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""));
  const chunks = [bytes.slice(0, 20), bytes.slice(20)];
  return { ok: true, status: 200, body: { getReader: () => ({ read: async () => (chunks.length ? { value: chunks.shift(), done: false } : { value: undefined, done: true }) }) } };
}
const show = () => render(<MemoryRouter><HelpChat /></MemoryRouter>);

// The chat's settings come from /config/; every other request is the chat itself (``chat``).
let chat;
let chatConfig;
beforeEach(() => {
  sessionStorage.clear();
  chat = vi.fn();
  chatConfig = { enabled: true, greeting: "", suggestions: [] };
  globalThis.fetch = vi.fn((url, options) => (String(url).includes("/assistant/config/")
    ? Promise.resolve({ ok: true, json: async () => chatConfig }) : chat(url, options)));
});
afterEach(() => vi.restoreAllMocks());

it("renders answers as safe Markdown: lists, bold and only trusted links", () => {
  render(<MemoryRouter><Answer text={"Steps:\n1. Open **Products**\n2. See [Create an account](/register)\n\nAvoid [this](javascript:alert(1)) and [that](//evil.test)."} /></MemoryRouter>);
  expect(screen.getByRole("list").tagName).toBe("OL");
  expect(screen.getByText("Products").tagName).toBe("STRONG");
  expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/register");
  expect(screen.queryByRole("link", { name: "this" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "that" })).not.toBeInTheDocument();
});

it("opens from the launcher, asks a suggested question and streams the answer with its sources", async () => {
  chat.mockResolvedValue(streamed([
    { type: "text", text: "Go to [Create an account](/register) " }, { type: "text", text: "and follow the steps." },
    { type: "sources", items: ["Getting started"] }, { type: "done" },
  ]));
  show();
  fireEvent.click(screen.getByRole("button", { name: /Ask us anything/ }));
  const panel = screen.getByRole("dialog", { name: "DukaFlow assistant" });
  fireEvent.click(within(panel).getByRole("button", { name: "How do I get started?" }));
  expect(await within(panel).findByText(/and follow the steps\./)).toBeInTheDocument();
  expect(within(panel).getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/register");
  expect(within(panel).getByText("From: Getting started")).toBeInTheDocument();
  const [url, options] = chat.mock.calls[0];
  expect(url).toBe("/api/v1/assistant/chat/");
  expect(JSON.parse(options.body)).toEqual({ messages: [{ role: "user", content: "How do I get started?" }] });
});

it("sends the earlier conversation with a follow-up question typed by the visitor", async () => {
  chat.mockResolvedValueOnce(streamed([{ type: "text", text: "It is a business platform." }, { type: "done" }]))
    .mockResolvedValueOnce(streamed([{ type: "text", text: "Pricing is not published yet." }, { type: "done" }]));
  show();
  fireEvent.click(screen.getByRole("button", { name: /Ask us anything/ }));
  const box = screen.getByLabelText("Your question");
  fireEvent.change(box, { target: { value: "What is it?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  await screen.findByText("It is a business platform.");
  fireEvent.change(box, { target: { value: "How much?" } });
  fireEvent.click(screen.getByRole("button", { name: "Send question" }));
  await screen.findByText("Pricing is not published yet.");
  expect(JSON.parse(chat.mock.calls[1][1].body).messages).toEqual([
    { role: "user", content: "What is it?" }, { role: "assistant", content: "It is a business platform." }, { role: "user", content: "How much?" },
  ]);
});

it("explains when the assistant is unavailable or busy", async () => {
  chat.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: "The help assistant isn't available right now. Please contact the team instead." }) })
    .mockResolvedValueOnce({ ok: false, status: 429, json: async () => ({}) });
  show();
  fireEvent.click(screen.getByRole("button", { name: /Ask us anything/ }));
  fireEvent.click(screen.getByRole("button", { name: "Does it work with M-Pesa?" }));
  expect(await screen.findByText(/isn't available right now/)).toBeInTheDocument();
  const box = screen.getByLabelText("Your question");
  fireEvent.change(box, { target: { value: "Hello?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await screen.findByText(/sending questions quickly/)).toBeInTheDocument();
  // A failed answer and its question are not sent back, so the old question is not answered with the new one.
  await waitFor(() => expect(JSON.parse(chat.mock.calls[1][1].body).messages).toEqual([{ role: "user", content: "Hello?" }]));
});

it("opens from a link elsewhere on the page and can ask a question straight away", async () => {
  chat.mockResolvedValue(streamed([{ type: "text", text: "Yes, with manual M-Pesa payments." }, { type: "done" }]));
  show();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  act(() => openHelpChat("Does it work with M-Pesa?"));
  expect(await screen.findByText("Yes, with manual M-Pesa payments.")).toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "DukaFlow assistant" })).toBeInTheDocument();
});

it("follows the platform owner's settings: greeting, suggestions, or switched off", async () => {
  chatConfig = { enabled: true, greeting: "Karibu! Ask me anything.", suggestions: ["Do you work in Uganda?"] };
  const { unmount } = render(<MemoryRouter><HelpChat /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /Ask us anything/ }));
  expect(await screen.findByText("Karibu! Ask me anything.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Do you work in Uganda?" })).toBeInTheDocument();
  unmount();
  chatConfig = { enabled: false, greeting: "", suggestions: [] };
  render(<MemoryRouter><HelpChat /></MemoryRouter>);
  await waitFor(() => expect(screen.queryByRole("button", { name: /Ask us anything/ })).toBeNull());
});

it("copies a whole answer or question in one tap, as plain text", async () => {
  const writeText = vi.fn(async () => {});
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
  chat.mockResolvedValue(streamed([{ type: "text", text: "### Steps\n1. Open **Products**\n2. See [Pricing](/pricing)" }, { type: "done" }]));
  show();
  fireEvent.click(screen.getByRole("button", { name: /Ask us anything/ }));
  const panel = screen.getByRole("dialog", { name: "DukaFlow assistant" });
  fireEvent.click(within(panel).getByRole("button", { name: "How do I get started?" }));
  fireEvent.click(await within(panel).findByRole("button", { name: "Copy answer" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("STEPS\n\n1. Open Products\n2. See Pricing"));
  expect(within(panel).getByRole("button", { name: "Copied" })).toBeInTheDocument();
  fireEvent.click(within(panel).getByRole("button", { name: "Copy question" }));
  await waitFor(() => expect(writeText).toHaveBeenLastCalledWith("How do I get started?"));
});

it("copies on a plain-http page too, where the clipboard API is missing", async () => {
  Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
  document.execCommand = vi.fn(() => true);
  const { copyText } = await import("./messageActions");
  expect(await copyText("KES 1,200")).toBe(true);
  expect(document.execCommand).toHaveBeenCalledWith("copy");
  expect(document.querySelector("textarea[readonly]")).toBeNull();
});

it("edits a question in place and asks it again, replacing what came after it", async () => {
  chat.mockResolvedValueOnce(streamed([{ type: "text", text: "It costs KES 1,000." }, { type: "done" }]))
    .mockResolvedValueOnce(streamed([{ type: "text", text: "Yes, staff accounts are included." }, { type: "done" }]));
  show();
  fireEvent.click(screen.getByRole("button", { name: /Ask us anything/ }));
  const panel = screen.getByRole("dialog", { name: "DukaFlow assistant" });
  fireEvent.click(within(panel).getByRole("button", { name: "How much does it cost?" }));
  await within(panel).findByText("It costs KES 1,000.");
  fireEvent.click(within(panel).getByRole("button", { name: "Edit question" }));
  const box = within(panel).getByLabelText("Edit your question");
  expect(box).toHaveValue("How much does it cost?");
  fireEvent.change(box, { target: { value: "Can my staff use it?" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Send" }));
  expect(await within(panel).findByText("Yes, staff accounts are included.")).toBeInTheDocument();
  expect(within(panel).queryByText("It costs KES 1,000.")).not.toBeInTheDocument();
  expect(JSON.parse(chat.mock.calls[1][1].body)).toEqual({ messages: [{ role: "user", content: "Can my staff use it?" }] });
});

it("shares an answer through the phone's share sheet, or WhatsApp where there is none", async () => {
  chat.mockResolvedValue(streamed([{ type: "text", text: "Open **Products**." }, { type: "done" }]));
  const share = vi.fn(async () => {});
  Object.defineProperty(navigator, "share", { value: share, configurable: true });
  show();
  fireEvent.click(screen.getByRole("button", { name: /Ask us anything/ }));
  const panel = screen.getByRole("dialog", { name: "DukaFlow assistant" });
  fireEvent.click(within(panel).getByRole("button", { name: "How do I get started?" }));
  fireEvent.click(await within(panel).findByRole("button", { name: "Share answer" }));
  await waitFor(() => expect(share).toHaveBeenCalledWith({ text: "Open Products." }));
  Object.defineProperty(navigator, "share", { value: undefined, configurable: true });
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  fireEvent.click(within(panel).getByRole("button", { name: "Share answer" }));
  await waitFor(() => expect(open).toHaveBeenCalledWith("https://wa.me/?text=Open%20Products.", "_blank", "noopener,noreferrer"));
});
