import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MpesaPaymentsSetup } from "./MpesaPaymentsSetup";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", async (original) => ({ ...(await original()), api: vi.fn() }));

const REQUIREMENTS = [{ id: "number", label: "Your till or paybill number", help: "…" }, { id: "daraja", label: "A Safaricom Daraja account", help: "…" },
  { id: "keys", label: "The app's Consumer Key and Consumer Secret", help: "…" }, { id: "passkey", label: "The Lipa na M-Pesa Online passkey", help: "…" }];
const none = { kind: "NONE", ready: false, can_change: true, requirements: REQUIREMENTS, callback_ready: true, environment: "PRODUCTION" };
beforeEach(() => vi.clearAllMocks());

it("lists what Safaricom needs for a till, saves it and says prompts are on", async () => {
  api.mockImplementation(async (path, options = {}) => (options.method === "PUT"
    ? { ...none, kind: "TILL", ready: true, till_number: "9876543", shortcode: "5123456", consumer_key_hint: "…1234", has_consumer_secret: true, has_passkey: true,
      verified_at: "2026-10-10T10:00:00Z", status_detail: "Safaricom accepted your keys. Send a test prompt to your own phone to finish." }
    : none));
  render(<MpesaPaymentsSetup />);
  expect(await screen.findByText("Manual M-Pesa only.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: /^Till number/ }));
  expect(screen.getByRole("heading", { name: "What you need from Safaricom" })).toBeInTheDocument();
  expect(screen.getByText("The Lipa na M-Pesa Online passkey")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Till number"), { target: { value: "9876543" } });
  fireEvent.change(screen.getByLabelText("Store number (head office number)"), { target: { value: "5123456" } });
  fireEvent.change(screen.getByLabelText("Consumer Key"), { target: { value: "key-1234" } });
  fireEvent.change(screen.getByLabelText("Consumer Secret"), { target: { value: "secret" } });
  fireEvent.change(screen.getByLabelText("Lipa na M-Pesa Online passkey"), { target: { value: "pass" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save and check with Safaricom" })); });
  expect(JSON.parse(api.mock.calls.find(([, o]) => o?.method === "PUT")[1].body)).toEqual(expect.objectContaining(
    { kind: "TILL", till_number: "9876543", shortcode: "5123456", consumer_key: "key-1234", passkey: "pass", environment: "PRODUCTION" }));
  await waitFor(() => expect(screen.getByText("Prompts are on")).toBeInTheDocument());
  expect(screen.getByLabelText("Consumer Key")).toHaveAttribute("placeholder", expect.stringContaining("…1234"));
  expect(screen.getByRole("button", { name: "Send test prompt" })).toBeInTheDocument();
});

it("tells staff who are not the owner that only the owner can change it", async () => {
  api.mockResolvedValue({ kind: "NONE", ready: false, can_change: false });
  render(<MpesaPaymentsSetup />);
  expect(await screen.findByText(/Only the business owner can change/)).toBeInTheDocument();
});
