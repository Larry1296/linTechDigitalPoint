import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { expect, it } from "vitest";
import { CashCounter, countPayload, countTotal, emptyCount } from "./CashCounter";

function Harness() {
  const [count, setCount] = useState(emptyCount);
  return <CashCounter count={count} onChange={setCount} />;
}

it("adds up each note count and the coins into the physical cash", () => {
  render(<Harness />);
  const enter = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
  enter("Number of 1000 notes", "10");
  enter("Number of 500 notes", "4");
  enter("Number of 200 notes", "5");
  enter("Number of 100 notes", "7");
  enter("Number of 50 notes", "3");
  enter("Coins total", "85");
  expect(screen.getByLabelText("Physical cash total")).toHaveTextContent("13,935");
});

it("sends whole note counts and the coins amount", () => {
  const count = { ...emptyCount(), 1000: "2", 50: "1", coins: "12.5" };
  expect(countTotal(count)).toBe(2062.5);
  expect(countPayload(count)).toEqual({ 1000: 2, 500: 0, 200: 0, 100: 0, 50: 1, coins: "12.5" });
});
