import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true), showError: vi.fn(), showSuccess: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { platform_admin: true } }) }));
import { api } from "../../core/api/client";
import { AssistantAdminPage } from "./AssistantAdminPage";

const settings = { enabled: true, greeting: "", suggestions: [], default_greeting: "Hi!", default_suggestions: ["How do I get started?"],
  providers: [{ id: "anthropic", label: "Claude (Anthropic)", available: false }, { id: "openai", label: "ChatGPT (OpenAI)", available: false }],
  models: { public: "claude-opus-5-5", business_claude: "claude-opus-5-5", business_chatgpt: "gpt-5.5" }, default_provider: "anthropic" };
const article = { slug: "08-mpesa", title: "M-Pesa", body: "## Does it work with M-Pesa?\nYes.", active: true, source: "built-in", original: null, updated_at: null };
const questions = { last_30_days: { questions: 2, unanswered: 1 }, keep_days: 180,
  questions: [{ id: 1, question: "Do you deliver?", articles: [], answered: false, asked_at: "2026-10-07T08:00:00Z" }] };

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path, options) => {
    if (path.includes("/settings/")) return options?.method === "PUT" ? { ...settings, ...JSON.parse(options.body) } : settings;
    if (path.includes("/questions/")) return questions;
    return { articles: [article] };
  });
});

it("says when the keys are missing and saves the website chat's switch, greeting and questions", async () => {
  render(<MemoryRouter><AssistantAdminPage /></MemoryRouter>);
  expect(await screen.findByText(/Without ANTHROPIC_API_KEY/)).toBeInTheDocument();
  const form = screen.getByRole("form", { name: "Public chat settings" });
  fireEvent.click(within(form).getByRole("checkbox", { name: /Show the chat/ }));
  fireEvent.change(within(form).getByLabelText("Greeting"), { target: { value: "Karibu!" } });
  fireEvent.change(within(form).getByLabelText(/Suggested questions/), { target: { value: "One?\nTwo?" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Save chat settings" })); });
  const [, options] = api.mock.calls.find(([p, o]) => p.endsWith("/settings/") && o?.method === "PUT");
  expect(JSON.parse(options.body)).toEqual({ enabled: false, greeting: "Karibu!", suggestions: ["One?", "Two?"] });
});

it("edits an article and turns an unanswered question into a new one", async () => {
  render(<MemoryRouter><AssistantAdminPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  const editor = screen.getByRole("form", { name: "Edit M-Pesa" });
  fireEvent.change(within(editor).getByLabelText("Questions and answers"), { target: { value: "## Does it work with M-Pesa?\nYes, fully." } });
  await act(async () => { fireEvent.click(within(editor).getByRole("button", { name: "Save article" })); });
  const [path, options] = api.mock.calls.find(([, o]) => o?.method === "PUT");
  expect(path).toBe("/api/v1/assistant/admin/articles/public/08-mpesa/");
  expect(JSON.parse(options.body)).toEqual({ title: "M-Pesa", body: "## Does it work with M-Pesa?\nYes, fully.", active: true });
  fireEvent.click(await screen.findByRole("button", { name: "Write an answer" }));
  const draft = screen.getByRole("form", { name: "New article" });
  expect(within(draft).getByLabelText("Questions and answers")).toHaveValue("## Do you deliver?\n");
});
