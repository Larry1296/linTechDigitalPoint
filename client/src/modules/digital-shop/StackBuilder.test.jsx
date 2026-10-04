import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { StackBuilder } from "./StackBuilder";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn(async () => []) }));
beforeEach(() => vi.clearAllMocks());
const next = () => fireEvent.click(screen.getByRole("button", { name: "Continue" }));
const type = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

it("lets every box be emptied and retyped, and says what is missing instead of refilling it", async () => {
  const created = vi.fn();
  render(<StackBuilder zones={[{ id: 3, name: "Left wall" }]} onCreated={created} onCancel={() => {}} />);
  type("Rack name", "Phone accessories");
  next();

  type("Width", "");
  expect(screen.getByLabelText("Width")).toHaveValue(null);      // stays empty, no 0 forced in
  next();
  expect(screen.getByRole("alert")).toHaveTextContent("Enter the width in feet (more than 0).");
  type("Width", "4");
  type("X position", "");
  next();
  expect(screen.getByRole("alert")).toHaveTextContent("Enter the X position (0 or more).");
  type("X position", "2");
  next();

  type("Number of levels", "");
  expect(screen.getByLabelText("Number of levels")).toHaveValue(null);
  type("Number of levels", "2");
  type("Level 1 compartments", "");
  expect(screen.getByLabelText("Level 1 compartments")).toHaveValue(null);   // no longer jumps back to 1
  next();
  expect(screen.getByRole("alert")).toHaveTextContent("Enter how many compartments level 1 has (1 or more).");
  type("Level 1 compartments", "5");
  next();

  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create rack" })); });
  const body = JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/locations/stacks/")[1].body);
  expect(body).toMatchObject({ zone: 3, display_name: "Phone accessories", width: 4, height: 7, x: 2, y: 0, levels: [{ compartments: 5 }, { compartments: 2 }] });
  expect(created).toHaveBeenCalledWith(3);
});
