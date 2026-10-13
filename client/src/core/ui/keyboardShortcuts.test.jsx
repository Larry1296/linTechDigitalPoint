import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, it } from "vitest";
import { useKeyboardShortcuts } from "./keyboardShortcuts";

function Where() {
  useKeyboardShortcuts();
  const { pathname, state } = useLocation();
  return <><p>At {pathname}{state?.focusStockSearch ? " to search" : ""}</p><input aria-label="Amount" /></>;
}
const app = () => render(<MemoryRouter initialEntries={["/admin/products"]}><Routes><Route path="*" element={<Where />} /></Routes></MemoryRouter>);

it("Home goes back to the dashboard, except while typing in a box", () => {
  app();
  fireEvent.keyDown(screen.getByLabelText("Amount"), { key: "Home" });  // moves the cursor in the box instead
  expect(screen.getByText("At /admin/products")).toBeInTheDocument();
  fireEvent.keyDown(document.body, { key: "Home", ctrlKey: true });
  expect(screen.getByText("At /admin/products")).toBeInTheDocument();
  fireEvent.keyDown(document.body, { key: "Home" });
  expect(screen.getByText("At /admin/dashboard")).toBeInTheDocument();
});

it("/ opens the dashboard's stock search", () => {
  app();
  fireEvent.keyDown(document.body, { key: "/" });
  expect(screen.getByText("At /admin/dashboard to search")).toBeInTheDocument();
});
