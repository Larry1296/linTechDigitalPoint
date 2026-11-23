import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ askForm: vi.fn(async () => ({ outcome: "Called, she came for two" })), confirmAction: vi.fn(async () => true) }));
const auth = { user: { permissions: ["core.view_customerpromise", "core.add_customerpromise", "core.change_customerpromise", "core.delete_customerpromise"] } };
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => auth }));
import { api } from "../../core/api/client";
import { PromisesPage } from "./PromisesPage";
import { PromiseReminder } from "./PromiseReminder";
import { quickPick } from "./promiseTime";

const hour = 3600000;
const at = (ms) => new Date(Date.now() + ms).toISOString();
const promise = (id, wanted, state, due, extra = {}) => ({ id, customer_name: "Wanjiru", phone: "0712 345 678", wanted, promised: "Check and call back",
  due_at: at(due), status: "OPEN", outcome: "", closed_at: null, created_at: at(-hour), created_by_name: "Larry", state, ...extra });
const data = {
  open: [promise(1, "Type-C earphones", "late", -2 * hour), promise(2, "iPhone 13 screen protectors", "soon", 3 * hour), promise(3, "Laptop bag", "later", 72 * hour)],
  done: [promise(4, "Tecno charger", "done", -48 * hour, { status: "MET", closed_at: at(-hour), outcome: "Came for it" })],
  late: 1, soon: 1, met: 1, not_met: 0, soon_hours: 24,
};

beforeEach(() => {
  vi.clearAllMocks();
  auth.user.permissions = ["core.view_customerpromise", "core.add_customerpromise", "core.change_customerpromise", "core.delete_customerpromise"];
  api.mockImplementation(async (path) => (path.endsWith("/due/") ? { due: data.open.slice(0, 2), soon_hours: 24 } : data));
});

it("shows open promises soonest first, marks the late and due ones, and lets you call the customer", async () => {
  render(<PromisesPage />);
  const open = await screen.findByRole("region", { name: /Still to answer/ });
  const cards = within(open).getAllByRole("listitem");
  expect(cards.map((card) => card.className)).toEqual(["promiseCard late", "promiseCard soon", "promiseCard later"]);
  expect(within(cards[0]).getByText("Late")).toBeInTheDocument();
  expect(within(cards[0]).getByText(/Late by 2 hours/)).toBeInTheDocument();
  expect(within(cards[1]).getByText(/Due in 3 hours/)).toBeInTheDocument();
  expect(within(cards[0]).getByRole("link", { name: "Call Wanjiru" })).toHaveAttribute("href", "tel:0712345678");
  expect(within(cards[0]).getByText(/by Larry/)).toBeInTheDocument();
  const done = screen.getByRole("region", { name: "Done" });
  expect(within(done).getByText(/Came for it/)).toBeInTheDocument();
});

it("records a new promise with when to answer, a quick pick filling the time", async () => {
  render(<PromisesPage />);
  const form = await screen.findByRole("form", { name: "New promise" });
  fireEvent.change(within(form).getByLabelText("Customer's phone"), { target: { value: "0722 000 111" } });
  fireEvent.change(within(form).getByLabelText("What they are looking for"), { target: { value: "iPhone screen protectors" } });
  fireEvent.change(within(form).getByLabelText("What you promised"), { target: { value: "Check and call him" } });
  fireEvent.click(within(form).getByRole("button", { name: "In a week" }));
  fireEvent.click(within(form).getByRole("button", { name: "Save the promise" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/promises/", expect.objectContaining({ method: "POST" })));
  const body = JSON.parse(api.mock.calls.find(([path, options]) => path === "/api/v1/promises/" && options?.method === "POST")[1].body);
  expect(body).toMatchObject({ phone: "0722 000 111", customer_name: "", wanted: "iPhone screen protectors", promised: "Check and call him" });
  expect(new Date(body.due_at).getTime()).toBe(quickPick("week").getTime());
});

it("closes a promise as met with what happened, and removes one", async () => {
  render(<PromisesPage />);
  const open = await screen.findByRole("region", { name: /Still to answer/ });
  fireEvent.click(within(within(open).getAllByRole("listitem")[0]).getByRole("button", { name: "Met: they got it" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/promises/1/", { method: "PATCH", body: JSON.stringify({ status: "MET", outcome: "Called, she came for two" }) }));
  fireEvent.click(within(within(open).getAllByRole("listitem")[2]).getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/promises/3/", { method: "DELETE" }));
});

it("an employee without removing can still record and close promises", async () => {
  auth.user.permissions = ["core.view_customerpromise", "core.add_customerpromise", "core.change_customerpromise"];
  render(<PromisesPage />);
  const open = await screen.findByRole("region", { name: /Still to answer/ });
  expect(within(open).queryByRole("button", { name: "Remove" })).toBeNull();
  expect(within(open).getAllByRole("button", { name: "Met: they got it" })).toHaveLength(3);
});

it("the dashboard reminds in red of promises late or due soon", async () => {
  render(<PromiseReminder />);
  const reminder = await screen.findByRole("alert", { name: "Customer promises due" });
  expect(reminder).toHaveClass("promiseReminder");
  expect(within(reminder).getByText("1 customer promise is late, 1 due soon")).toBeInTheDocument();
  expect(within(reminder).getByText("Type-C earphones")).toBeInTheDocument();
  expect(within(reminder).getByRole("link", { name: "Open promises" })).toHaveAttribute("href", "/admin/promises");
});

it("shows no reminder when nothing is due, or to someone who cannot see promises", async () => {
  api.mockImplementation(async () => ({ due: [] }));
  const { container } = render(<PromiseReminder />);
  await waitFor(() => expect(api).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
  auth.user.permissions = [];
  api.mockClear();
  render(<PromiseReminder />);
  expect(api).not.toHaveBeenCalled();
});

it("quick picks land at 10 am on whole days and never on a Sunday", () => {
  const saturday = new Date(2026, 10, 28, 15, 0);
  expect(quickPick("tomorrow", saturday)).toEqual(new Date(2026, 10, 30, 10, 0));  // Sunday moves to Monday
  expect(quickPick("three", saturday)).toEqual(new Date(2026, 11, 1, 10, 0));
  expect(quickPick("hours", saturday)).toEqual(new Date(2026, 10, 28, 17, 0));
});
