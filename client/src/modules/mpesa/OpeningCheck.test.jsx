import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { expect, it } from "vitest";
import { OpeningCheck, emptyOpening, openingGaps } from "./OpeningCheck";

const last = { cash: "4000.00", float: "11000.00", updated_on: "2026-10-06" };

function Harness({ cash, electronicFloat }) {
  const [opening, setOpening] = useState(emptyOpening);
  return <OpeningCheck last={last} cash={cash} electronicFloat={electronicFloat} opening={opening} onChange={setOpening} canRecordCommission />;
}

it("works out what is left unexplained after commission", () => {
  expect(openingGaps(last, 4000, "12020", { commission: true, commissionAmount: "1020" })).toEqual({ cash: 0, float: 0, extraFloat: 1020 });
  expect(openingGaps(last, 3000, "11000.1", { commission: false })).toEqual({ cash: -1000, float: 0.1, extraFloat: 0.1 });
  expect(openingGaps(null, 3000, "1", emptyOpening())).toEqual({ cash: 0, float: 0, extraFloat: 0 });
});

it("shows the last close, offers commission for extra float and asks why anything else differs", () => {
  render(<Harness cash={4000} electronicFloat="12020" />);
  expect(screen.getByText(/The last shift closed with cash/)).toHaveTextContent("KSh 4,000");
  expect(screen.getByText(/Not matching the last shift/)).toHaveTextContent("float +KSh 1,020");
  expect(screen.getByLabelText("Why it differs")).toBeRequired();
  fireEvent.click(screen.getByRole("checkbox", { name: /Safaricom paid commission into it/ }));
  expect(screen.getByLabelText(/Commission in the float/)).toHaveValue(1020);
  expect(screen.queryByLabelText("Why it differs")).toBeNull();  // the commission explains it all
});

it("says nothing more when the counts match", () => {
  render(<Harness cash={4000} electronicFloat="11000" />);
  expect(screen.queryByText(/Not matching/)).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
});
