import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import { Answer, parse } from "./answerFormat";

const show = (text) => render(<MemoryRouter><div data-testid="answer"><Answer text={text} /></div></MemoryRouter>);

it("renders a lead, section headings, a table with numbers on the right, a callout and a note", () => {
  show([
    "**Profit of KES 1,257** for this month.",
    "",
    "### By business unit",
    "| Unit | Revenue | Net |",
    "|---|---|---|",
    "| Shop | KES 2,460 | KES 907 |",
    "| Cyber | KES 350 | KES 350 |",
    "",
    "> No running costs are recorded, so the real profit is lower.",
    "",
    "_Answered directly from your records._",
  ].join("\n"));
  const answer = screen.getByTestId("answer");
  expect(answer.querySelector("p.answerLead strong")).toHaveTextContent("Profit of KES 1,257");
  expect(screen.getByRole("heading", { name: "By business unit" })).toBeInTheDocument();
  const table = screen.getByRole("table");
  expect(within(table).getAllByRole("columnheader").map((c) => c.textContent)).toEqual(["Unit", "Revenue", "Net"]);
  expect(within(table).getByText("KES 2,460")).toHaveClass("num");
  expect(within(table).getByText("Shop")).not.toHaveClass("num");
  expect(answer.querySelector(".answerCallout")).toHaveTextContent("real profit is lower");
  expect(answer.querySelector(".answerNote")).toHaveTextContent("Answered directly from your records.");
});

it("nests indented bullets and keeps numbered steps, bold, italics and code", () => {
  show("Steps:\n1. Open **Rules**\n2. Change *Contributions*\n\n- Shop money: KES 12,010\n  - Cash in the drawer: KES 12,010\n- Use `KES`");
  const answer = screen.getByTestId("answer");
  expect(answer.querySelectorAll("ol > li")).toHaveLength(2);
  expect(answer.querySelector("ol strong")).toHaveTextContent("Rules");
  expect(answer.querySelector("ol em")).toHaveTextContent("Contributions");
  expect(answer.querySelector("ul > li > ul > li")).toHaveTextContent("Cash in the drawer");
  expect(answer.querySelector("code")).toHaveTextContent("KES");
});

it("never turns text into markup and only links to our pages or https", () => {
  show("<img src=x onerror=alert(1)> [Sign in](/login) [bad](javascript:alert(1)) [docs](https://example.com)");
  const answer = screen.getByTestId("answer");
  expect(answer.querySelector("img")).toBeNull();
  expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("target", "_blank");
  expect(screen.queryByRole("link", { name: "bad" })).toBeNull();
});

it("does not take snake_case words or a lone asterisk for italics", () => {
  expect(parse("Use the stock_levels tool * twice")[0].kind).toBe("paragraph");
  show("Use the stock_levels tool * twice");
  expect(screen.getByTestId("answer").querySelector("em")).toBeNull();
});
