import { expect, it } from "vitest";
import { labelTableCells } from "./useTableLabels";

it("labels every body and footer cell with its column heading, following colspans", () => {
  document.body.innerHTML = `<table>
    <thead><tr><th>Month</th><th colspan="2">Money</th><th>Net profit / loss</th></tr></thead>
    <tbody><tr><th scope="row">Sep</th><td>100</td><td>40</td><td>60</td></tr></tbody>
    <tfoot><tr><th colspan="3">Total</th><td>60</td></tr></tfoot></table>`;
  labelTableCells(document.body);
  const labels = [...document.querySelectorAll("tbody :is(td, th), tfoot :is(td, th)")].map((cell) => cell.dataset.label);
  expect(labels).toEqual(["Month", "Money", "Money", "Net profit / loss", "Month", "Net profit / loss"]);
});
