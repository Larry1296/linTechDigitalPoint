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

it("labels the grid tables' cells from their heading row", () => {
  document.body.innerHTML = `<div class="table ledgerTable">
    <div><b>Time</b><b>Amount</b><b>Transaction ID</b></div>
    <div><span>09:12</span><span>KSh 500</span><span>SJK4H7XQ2P</span></div></div>`;
  labelTableCells(document.body);
  expect([...document.querySelectorAll(".table > div + div > span")].map((cell) => cell.dataset.label)).toEqual(["Time", "Amount", "Transaction ID"]);
  expect(document.querySelector(".table b").dataset.label).toBeUndefined();
});
