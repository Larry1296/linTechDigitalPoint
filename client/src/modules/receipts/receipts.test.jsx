import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReceiptPanel } from "./ReceiptPanel";
import { PublicReceiptPage } from "./PublicReceiptPage";
import { whatsappLink, whatsappNumber } from "./whatsapp";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { organization: { country: "KE" } } }) }));

const receipt = {
  business: { name: "Mama Mboga Kiandas", logo: "/api/v1/tenancy/public/logos/abc.png", phone: "0700 111 222", email: "", address: "Kiandas market" },
  branch: { name: "Main branch", phone: "", email: "", address: "" }, number: "POS-42", channel: "POS", status: "COMPLETED",
  date: "2026-09-24T10:30:00+03:00", currency: "KES", cashier: "Wanjiku", customer: "Walk-in customer",
  items: [{ name: "Sukuma wiki", variant: "Bunch", sku: "SUK-1", quantity: "3.000", unit_price: "20.00", discount: "0.00", total: "60.00" }],
  subtotal: "60.00", discount: "0.00", total: "60.00", payments: [{ method: "M-Pesa", amount: "60.00", reference: "QWE123", status: "COMPLETED" }],
  paid: "60.00", balance: "0.00", footer: "Karibu tena!",
};
let opened;
beforeEach(() => {
  vi.clearAllMocks();
  opened = { location: { href: "" } };
  vi.spyOn(window, "open").mockReturnValue(opened);
  api.mockImplementation(async (path, options = {}) => {
    if (path.endsWith("/receipt/")) return { sale_id: 7, receipt, link: null };
    if (path.endsWith("/receipt/link/") && options.method === "POST") return { link: "https://app.example/r/tok_abcdefghijklmnopqrstuv" };
    if (path.endsWith("/receipt/email/")) return { sent_to: JSON.parse(options.body).email, link: "https://app.example/r/tok_abcdefghijklmnopqrstuv" };
    return undefined;
  });
});
afterEach(() => vi.restoreAllMocks());

it("formats Kenyan and international numbers for WhatsApp and writes a friendly message", () => {
  expect(whatsappNumber("0712 345 678")).toBe("254712345678");
  expect(whatsappNumber("+254 712-345-678")).toBe("254712345678");
  expect(whatsappNumber("712345678")).toBe("254712345678");
  expect(whatsappNumber("+256 772 000111", "KE")).toBe("256772000111");
  const url = new URL(whatsappLink("254712345678", receipt, "https://app.example/r/x"));
  expect(url.origin + url.pathname).toBe("https://wa.me/254712345678");
  expect(url.searchParams.get("text")).toContain("Thank you for shopping at Mama Mboga Kiandas.");
  expect(url.searchParams.get("text")).toContain("View your receipt: https://app.example/r/x");
});

it("shows the receipt in the business's own name and sends it on WhatsApp", async () => {
  render(<ReceiptPanel saleId={7} onClose={vi.fn()} />);
  const doc = await screen.findByRole("article", { name: "Receipt POS-42" });
  expect(within(doc).getByRole("img", { name: "Mama Mboga Kiandas" })).toHaveAttribute("src", receipt.business.logo);
  expect(within(doc).getByText("Karibu tena!")).toBeInTheDocument();
  expect(within(doc).queryByText(/LinTech/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Send on WhatsApp" }));
  fireEvent.change(screen.getByLabelText("Customer's WhatsApp number"), { target: { value: "0712 345 678" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Open WhatsApp" })); });
  expect(opened.location.href).toMatch(/^https:\/\/wa\.me\/254712345678\?text=/);
  expect(decodeURIComponent(opened.location.href)).toContain("https://app.example/r/tok_abcdefghijklmnopqrstuv");
  expect(screen.getByRole("status")).toHaveTextContent("WhatsApp opened");
  expect(screen.getByRole("button", { name: "Turn off link" })).toBeInTheDocument();
});

it("emails the receipt and can turn the private link off again", async () => {
  render(<ReceiptPanel saleId={7} onClose={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Send by email" }));
  fireEvent.change(screen.getByLabelText("Customer's email"), { target: { value: "shopper@example.com" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Send receipt" })); });
  expect(screen.getByRole("status")).toHaveTextContent("Receipt emailed to shopper@example.com.");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Turn off link" })); });
  expect(api).toHaveBeenCalledWith("/api/v1/commerce/sales/7/receipt/link/", { method: "DELETE" });
  expect(screen.queryByRole("button", { name: "Turn off link" })).not.toBeInTheDocument();
});

it("warns about a mistyped WhatsApp number without opening WhatsApp", async () => {
  render(<ReceiptPanel saleId={7} onClose={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Send on WhatsApp" }));
  fireEvent.change(screen.getByLabelText("Customer's WhatsApp number"), { target: { value: "0712" } });
  fireEvent.click(screen.getByRole("button", { name: "Open WhatsApp" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Check the phone number.");
  expect(window.open).not.toHaveBeenCalled();
});

it("lets a customer open the receipt from the link, or explains a dead link", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify(receipt), { status: 200 }));
  const { unmount } = render(<MemoryRouter initialEntries={["/r/tok_abcdefghijklmnopqrstuv"]}><Routes><Route path="/r/:token" element={<PublicReceiptPage />} /></Routes></MemoryRouter>);
  expect(await screen.findByRole("article", { name: "Receipt POS-42" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Print or save as PDF" })).toBeInTheDocument();
  expect(document.title).toBe("Receipt POS-42 · Mama Mboga Kiandas");
  unmount();
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ detail: "This receipt link is not valid or has been turned off by the business." }), { status: 404 }));
  render(<MemoryRouter initialEntries={["/r/tok_dead_dead_dead_dead_dead"]}><Routes><Route path="/r/:token" element={<PublicReceiptPage />} /></Routes></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Receipt unavailable" })).toBeInTheDocument();
});
