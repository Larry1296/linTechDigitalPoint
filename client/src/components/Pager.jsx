import { useEffect, useMemo, useState } from "react";
import { api } from "../core/api/client";

export const PAGE_SIZE = 10;

// Page numbers to offer: the first, the last, and the ones around the current page, with gaps between.
const numbers = (page, pages) => {
  const wanted = new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages));
  const sorted = [...wanted].sort((a, b) => a - b);
  return sorted.flatMap((n, i) => (i && n - sorted[i - 1] > 1 ? ["gap" + n, n] : [n]));
};

/** "21–30 of 340 jobs" with Previous, page numbers and Next. Shows nothing while everything fits on one page. */
export function Pager({ page, pages, count, size = PAGE_SIZE, onPage, noun = "items", busy = false }) {
  if (!pages || pages <= 1) return null;
  const from = (page - 1) * size + 1;
  const to = Math.min(page * size, count);
  return (
    <nav className="pager" aria-label={`Pages of ${noun}`}>
      <span className="pagerCount">{from.toLocaleString()}–{to.toLocaleString()} of {count.toLocaleString()} {noun}</span>
      <div className="pagerButtons">
        <button type="button" className="secondary" disabled={busy || page <= 1} onClick={() => onPage(page - 1)}>‹ Previous</button>
        {numbers(page, pages).map((n) => (typeof n === "string"
          ? <span key={n} className="pagerGap" aria-hidden="true">…</span>
          : <button key={n} type="button" className={n === page ? "pagerOn" : "secondary"} aria-current={n === page ? "page" : undefined}
            aria-label={`Page ${n}`} disabled={busy} onClick={() => onPage(n)}>{n}</button>))}
        <button type="button" className="secondary" disabled={busy || page >= pages} onClick={() => onPage(page + 1)}>Next ›</button>
      </div>
    </nav>
  );
}

/** Pages a list already on the page. `reset` (e.g. a search or filter) goes back to page 1 when it changes. */
export function usePages(rows, { size = PAGE_SIZE, reset } = {}) {
  const list = rows || [];
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [reset]);
  const pages = Math.max(1, Math.ceil(list.length / size));
  const current = Math.min(page, pages); // a row removed from the last page falls back a page
  const shown = useMemo(() => list.slice((current - 1) * size, current * size), [list, current, size]);
  return { rows: shown, page: current, pages, count: list.length, size, onPage: setPage };
}

/** Loads one page at a time from a list the server pages (?page=N). `version` reloads the current page. */
export function useServerPages(path, { size = PAGE_SIZE, version = 0 } = {}) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ results: [], count: 0, pages: 1, page: 1 });
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => setPage(1), [path]);
  useEffect(() => {
    if (!path) return undefined; // nothing to load yet (e.g. a detail page is open instead)
    let live = true;
    setBusy(true);
    const join = path.includes("?") ? "&" : "?";
    api(`${path}${join}page=${page}&page_size=${size}`)
      .then((body) => {
        if (!live) return;
        // A page that emptied (its last row deleted) steps back to the one before.
        if (!body.results?.length && page > 1) { setPage(page - 1); return; }
        setData(body); setError("");
      })
      .catch((err) => { if (live) setError(err.message); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [path, page, size, version]);
  return { rows: data.results || [], page: data.page || page, pages: data.pages || 1, count: data.count || 0, size, onPage: setPage, busy, error };
}

/** For a list worked out after a page's early returns, where a hook cannot go: `children` gets this page's rows. */
export function Paged({ rows, size = PAGE_SIZE, reset, noun, children }) {
  const pages = usePages(rows, { size, reset });
  return <>{children(pages.rows)}<Pager {...pages} noun={noun} /></>;
}
