import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { usePreventNumberScroll } from "./usePreventNumberScroll";

function Form() {
  usePreventNumberScroll();
  return (
    <>
      <input
        aria-label="Selling price"
        type="number"
        step="0.01"
        defaultValue="200"
      />
      <input aria-label="Product name" />
    </>
  );
}

it("stops wheel stepping without cancelling page scrolling or manual editing", () => {
  render(<Form />);
  const price = screen.getByLabelText("Selling price");
  price.focus();
  const wheel = new WheelEvent("wheel", {
    bubbles: true,
    cancelable: true,
    deltaY: 120,
  });
  price.dispatchEvent(wheel);
  expect(price).not.toHaveFocus();
  expect(price).toHaveValue(200);
  expect(wheel.defaultPrevented).toBe(false);
  price.focus();
  fireEvent.change(price, { target: { value: "250.50" } });
  expect(price).toHaveValue(250.5);
  const name = screen.getByLabelText("Product name");
  name.focus();
  fireEvent.wheel(name, { deltaY: 120 });
  expect(name).toHaveFocus();
});
