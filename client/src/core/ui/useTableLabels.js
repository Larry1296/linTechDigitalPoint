import { useEffect } from "react";

// Gives every body cell its column heading as data-label, so on small screens
// each table row can be shown as a labelled card instead of scrolling sideways.
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
          const label = headings[column] || "";
          if (label && cell.dataset.label !== label && !cell.hasAttribute("data-label-fixed")) cell.dataset.label = label;
          column += cell.colSpan || 1;
        }
      }
    }
  }
}

export function useTableLabels(ref) {
  useEffect(() => {
    const root = ref.current;
    if (!root) return undefined;
    labelTableCells(root);
    const observer = new MutationObserver(() => labelTableCells(root));
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, [ref]);
}
