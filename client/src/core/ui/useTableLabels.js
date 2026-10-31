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

// Table text stays on one line, so a table can be wider than the space it is in: such a table scrolls sideways on its
// own (class tableScrolls), and one that fits keeps its full width. Measured again as tables and the window change.
export function fitTables(root) {
  for (const table of root.querySelectorAll("table")) {
    const scrolls = table.classList.contains("tableScrolls");
    const wide = scrolls ? table.scrollWidth > table.clientWidth + 1 : table.offsetWidth > (table.parentElement?.clientWidth ?? Infinity) + 1;
    if (wide !== scrolls) table.classList.toggle("tableScrolls", wide);
  }
}

// Labels the tables under ``ref`` (the whole app when none is given), and keeps them labelled and fitted as they change.
export function useTableLabels(ref) {
  useEffect(() => {
    const root = ref ? ref.current : document.getElementById("root") || document.body;
    if (!root) return undefined;
    let frame = 0;
    const fit = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => fitTables(root)); };
    labelTableCells(root);
    fit();
    const observer = new MutationObserver(() => { labelTableCells(root); fit(); });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    window.addEventListener("resize", fit);
    return () => { observer.disconnect(); window.removeEventListener("resize", fit); cancelAnimationFrame(frame); };
  }, [ref]);
}
