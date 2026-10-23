import { useEffect } from "react";

const label = (cell, text) => {
  if (text && cell.dataset.label !== text && !cell.hasAttribute("data-label-fixed")) cell.dataset.label = text;
};

// Gives every body cell its column heading as data-label, so on small screens
// each table row can be shown as a labelled card instead of scrolling sideways.
// The grid tables (.table: a heading row of divs, then a div per row) are labelled the same way.
export function labelTableCells(root) {
  for (const table of root.querySelectorAll("table")) {
    const headings = [];
    for (const cell of table.tHead?.rows[0]?.cells || []) {
      for (let span = 0; span < (cell.colSpan || 1); span += 1) headings.push(cell.textContent.trim());
    }
    if (!headings.length) continue;
    for (const section of [...table.tBodies, table.tFoot].filter(Boolean)) {
      for (const row of section.rows) {
        let column = 0;
        for (const cell of row.cells) {
          label(cell, headings[column] || "");
          column += cell.colSpan || 1;
        }
      }
    }
  }
  for (const grid of root.querySelectorAll(".table")) {
    const [head, ...rows] = grid.children;
    const headings = [...(head?.children || [])].map((cell) => cell.textContent.trim());
    for (const row of rows) [...row.children].forEach((cell, column) => label(cell, headings[column] || ""));
  }
}

// Labels the tables under ``ref`` (the whole app when none is given), and keeps them labelled as they change.
export function useTableLabels(ref) {
  useEffect(() => {
    const root = ref ? ref.current : document.getElementById("root") || document.body;
    if (!root) return undefined;
    labelTableCells(root);
    const observer = new MutationObserver(() => labelTableCells(root));
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, [ref]);
}
