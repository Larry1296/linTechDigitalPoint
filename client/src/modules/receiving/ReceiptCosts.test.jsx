import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
let permissions = [];
let modules = ["investments"];
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions, organization: { enabled_modules: modules } } }) }));
import { api } from "../../core/api/client";
import { NEW_RECEIPT_COSTS, ReceiptCostFields, paymentSummary, receiptCostsPayload, receiptCostsProblem } from "./ReceiptCosts";

const mmf = { id: 3, name: "Sanlam MMF", value: "30000.00" };
const seen = [];
function Harness() {
  const [details, setDetails] = useState({ ...NEW_RECEIPT_COSTS, supplier_name: "Phone Hub", external_reference: "INV-77" });
  return <ReceiptCostFields details={details} onChange={(next) => { seen.push(next); setDetails(next); }} goodsTotal={20000} />;
}
const latest = () => seen.at(-1);

beforeEach(() => {
  vi.clearAllMocks();
  seen.length = 0;
  permissions = ["accounting.view_investment", "accounting.add_investmentmovement"];
  api.mockResolvedValue({ investments: [mmf, { id: 4, name: "Empty fund", value: "0.00" }] });
});

it("pays the supplier from the MMF as the owner's own money, never through the till or bank", async () => {
  render(<Harness />);
  const paid = screen.getByLabelText("Paid the supplier now?");
  fireEvent.change(paid, { target: { value: (await screen.findByRole("option", { name: "Yes, from my investment (MMF)" })).value } });
  expect(screen.queryByLabelText("Take it out of")).toBeNull();  // the only fund holding money is chosen for you
  expect(screen.getByText(/Sanlam MMF holds KSh 30,000/)).toBeInTheDocument();
  expect(screen.queryByLabelText("Withdrawn to")).toBeNull();
  expect(screen.getByText(/paid straight to the supplier as your own money/)).toBeInTheDocument();
  expect(receiptCostsProblem(latest())).toBe("");
  expect(receiptCostsPayload(latest()).payment).toEqual({ method: "INVESTMENT", amount: "20000", investment_id: 3 });
  expect(receiptCostsPayload(latest())).not.toHaveProperty("investment_name");
  expect(paymentSummary(latest())).toBe("20000 paid now from Sanlam MMF (your own money, not the business's)");
  fireEvent.change(screen.getByLabelText(/Amount paid now/), { target: { value: "35000" } });
  expect(screen.getByText(/record interest from its statement first/)).toBeInTheDocument();
});

it("does not offer investments to people who cannot take money out of them", () => {
  permissions = [];
  render(<Harness />);
  expect(api).not.toHaveBeenCalled();
  expect(screen.queryByRole("option", { name: /from my investment/ })).toBeNull();
});
