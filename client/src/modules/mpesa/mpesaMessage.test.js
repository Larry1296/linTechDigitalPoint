import { expect, it } from "vitest";
import { readMpesaMessage } from "./mpesaMessage";

it("takes the code, the transaction amount and the phone number from a confirmation", () => {
  expect(readMpesaMessage("SJK4ABC123 Confirmed. Ksh1,000.00 deposited to JANE WANJIRU 254712345678 on 26/9/26 at 10:15 AM. New M-PESA float balance is Ksh25,400.00."))
    .toEqual({ code: "SJK4ABC123", amount: "1000.00", phone: "0712345678" });
  expect(readMpesaMessage("TJQ8XY12AB confirmed. Give Ksh 500 cash to 0110 000 000")).toEqual({ code: "TJQ8XY12AB", amount: "500", phone: "0110000000" });
});

it("leaves out what the message does not say instead of guessing", () => {
  expect(readMpesaMessage("CONFIRMED deposit")).toEqual({ code: "", amount: "", phone: "" });
});
