import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../core/api/client";
import { StayPage } from "./StayPage";
import { FrontDeskPage } from "./FrontDeskPage";
import { KitchenPage } from "./MenuKitchenPages";
import { CheckoutPanel } from "../pos/CheckoutPanel";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
const user = { id: 1, organization: { enabled_modules: ["rooms", "menu", "pos"] },
  permissions: ["hotel.view_stay", "hotel.add_stay", "hotel.change_stay", "hotel.add_staydeposit", "hotel.add_room", "hotel.view_kitchenuse",
    "hotel.add_kitchenuse", "hotel.add_kitcheningredient", "commerce.add_sale"] };
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user }) }));
beforeEach(() => vi.clearAllMocks());

const bill = (changes = {}) => ({ charges: [{ id: 1, kind: "NIGHT", night: "2026-10-05", at: "2026-10-05T14:00:00Z", lines: [{ name: "Night of Mon 05 Oct", quantity: "1", amount: "3000" }], total: "3000", owing: "0" },
  { id: 2, kind: "TILL", night: null, at: "2026-10-05T19:00:00Z", lines: [{ name: "Chapati", quantity: "10.000", amount: "300" }], total: "300", owing: "300" }],
  total: "3300", owing: "300", held: "0", balance: "300", paid: "3000", payments: [{ id: 1, amount: "3000", method: "MPESA", reference: "RKT1", used: "3000", refunded: "0", at: "2026-10-05T14:00:00Z" }], ...changes });
const stay = (changes = {}) => ({ id: 7, number: "ST-261005-AB12", room: { id: 1, number: "101", type: "Double room" }, guest_id: 4, guest: "Otieno Okoth",
  phone: "0711000111", id_number: "23456789", guests: 1, arrival: "2026-10-05", departure: "2026-10-07", nights: 2, rate: "3000", status: "IN",
  status_label: "Checked in", note: "", bill: bill(), ...changes });

it("shows the guest's bill and checks them out with what they still owe", async () => {
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? stay({ status: "OUT", status_label: "Checked out", bill: bill({ owing: "0", balance: "0", paid: "3300" }) }) : stay()));
  render(<MemoryRouter initialEntries={["/admin/rooms/stays/7"]}><Routes><Route path="/admin/rooms/stays/:id" element={<StayPage />} /></Routes></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Otieno Okoth" })).toBeInTheDocument();
  expect(screen.getByText("Chapati × 10")).toBeInTheDocument();
  expect(within(screen.getByText("Still owed").parentElement).getByText(/300/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Check out" }));
  const form = screen.getByRole("form", { name: "Check out" });
  expect(within(form).getByLabelText("Paid now")).toHaveValue(300);
  fireEvent.click(within(form).getByRole("button", { name: "Check out" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/hotel/stays/7/check-out/", expect.objectContaining({ method: "POST" })));
  const body = JSON.parse(api.mock.calls.find(([path]) => path.endsWith("/check-out/"))[1].body);
  expect(body).toEqual({ payment: { amount: "300", method: "CASH", reference: "" }, leave_owing: false });
  expect(await screen.findByText(/Checked out/)).toBeInTheDocument();
});

it("shows every room's state on the front desk and books a free one", async () => {
  api.mockImplementation(async (path) => path.startsWith("/api/v1/hotel/rooms/") ? { date: "2026-10-05", counts: { OCCUPIED: 1, BOOKED: 0, FREE: 1, OUT_OF_ORDER: 0, to_clean: 1, arrivals: 0, departures: 0 },
    rooms: [{ id: 1, number: "101", type: "Double room", rate: "3000", condition: "READY", state: "OCCUPIED", stay: { id: 7, guest: "Otieno Okoth", arrival: "2026-10-05", departure: "2026-10-07", status: "IN" } },
      { id: 2, number: "102", type: "Double room", rate: "3000", condition: "DIRTY", state: "FREE", stay: null }] } : stay());
  render(<MemoryRouter><FrontDeskPage /></MemoryRouter>);
  const occupied = await screen.findByRole("article", { name: "Room 101" });
  expect(within(occupied).getByText("Guest in")).toBeInTheDocument();
  const free = screen.getByRole("article", { name: "Room 102" });
  expect(within(free).getByText("Needs cleaning")).toBeInTheDocument();
  fireEvent.click(within(free).getByRole("button", { name: "Book" }));
  const form = screen.getByRole("form", { name: "Book a room" });
  expect(within(form).getByLabelText("Room")).toHaveValue("2");
});

it("works out what the kitchen used from what is left", async () => {
  api.mockImplementation(async (path, options) => (path === "/api/v1/hotel/kitchen/ingredients/" ? [{ id: 3, name: "Wheat flour", unit: "kg", in_store: "20.000", value: "3000" }]
    : options?.method === "POST" ? { id: 1 } : []));
  render(<MemoryRouter><KitchenPage /></MemoryRouter>);
  const left = await screen.findByLabelText("Wheat flour left");
  fireEvent.change(left, { target: { value: "16" } });
  expect(screen.getByText("4 kg")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Record kitchen use" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/hotel/kitchen/use/", expect.objectContaining({ method: "POST" })));
  const body = JSON.parse(api.mock.calls.find(([path, options]) => path === "/api/v1/hotel/kitchen/use/" && options?.method === "POST")[1].body);
  expect(body.lines).toEqual([{ ingredient_id: 3, left: "16" }]);
  expect(body.way).toBe("COUNTED");
});

it("charges a sale at the till to a guest's room", async () => {
  const checkout = { id: 5, number: "POS-1", status: "AWAITING", total: "300", left: "300", paid: "0", items: 1, payments: [] };
  api.mockImplementation(async (path) => (path === "/api/v1/hotel/stays/in-house/" ? [{ id: 7, number: "ST-1", room: "101", guest: "Otieno Okoth" }] : checkout));
  render(<CheckoutPanel checkout={checkout} user={user} onChange={() => {}} onDone={() => {}} onBack={() => {}} />);
  fireEvent.click(screen.getByRole("tab", { name: /Room/ }));
  fireEvent.change(await screen.findByLabelText("Guest's room"), { target: { value: "7" } });
  fireEvent.click(screen.getByRole("button", { name: /to the room/ }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/commerce/pos/checkouts/5/pay/", { method: "POST", body: JSON.stringify({ method: "ROOM", stay_id: "7" }) }));
});
