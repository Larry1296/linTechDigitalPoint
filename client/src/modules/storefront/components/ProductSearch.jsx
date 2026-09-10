import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../../core/api/client";
import { ProductImage } from "./ProductImage";

export function ProductSearch({
  value,
  onChange,
  onSearch,
  placeholder = "Search all available products…",
}) {
  const [localQuery, setLocalQuery] = useState("");
  const query = value ?? localQuery;
  const updateQuery = onChange ?? setLocalQuery;
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("idle");
  const [active, setActive] = useState(-1);
  const root = useRef(null);
  const listId = useId();
  const navigate = useNavigate();
  const trimmed = query.trim();
  const expanded = open && trimmed.length >= 2;

  useEffect(() => {
    if (!expanded) return;
    let current = true;
    const controller = new AbortController();
    setRows([]);
    setActive(-1);
    setStatus("loading");
    const timer = setTimeout(() => {
      api(
        "/api/v1/store/search-suggestions/?q=" + encodeURIComponent(trimmed),
        { signal: controller.signal },
      )
        .then((results) => {
          if (!current) return;
          setRows(results.slice(0, 8));
          setStatus("ready");
        })
        .catch(() => {
          if (current) setStatus("error");
        });
    }, 250);
    return () => {
      current = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, expanded]);

  useEffect(() => {
    const outside = (event) => {
      if (!root.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);

  useEffect(() => {
    if (expanded && active >= 0) {
      document.getElementById(listId + "-" + active)?.scrollIntoView?.({ block: "nearest" });
    }
  }, [active, expanded, listId]);

  const select = (product) => {
    setOpen(false);
    navigate("/products/" + product.id);
  };
  const search = (event) => {
    event.preventDefault();
    setOpen(false);
    if (onSearch) onSearch(trimmed);
    else navigate("/shop?" + new URLSearchParams({ search: trimmed }));
  };

  return (
    <form
      className="productSearch"
      ref={root}
      onSubmit={search}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <div className="productSearchControls">
        <input
          role="combobox"
          aria-label="Search products"
          autoComplete="off"
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-activedescendant={
            expanded && active >= 0 && rows[active]
              ? listId + "-" + active
              : undefined
          }
          value={query}
          placeholder={placeholder}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            updateQuery(event.target.value);
            setRows([]);
            setActive(-1);
            setOpen(Boolean(event.target.value.trim()));
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
              setActive(-1);
            } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              setOpen(true);
              if (rows.length)
                setActive((index) =>
                  event.key === "ArrowDown"
                    ? (index + 1) % rows.length
                    : index <= 0
                      ? rows.length - 1
                      : index - 1,
                );
            } else if (
              event.key === "Enter" &&
              expanded &&
              active >= 0 &&
              rows[active]
            ) {
              event.preventDefault();
              select(rows[active]);
            } else if (event.key === "Enter" && !event.nativeEvent.isComposing) {
              search(event);
            }
          }}
        />
        <button type="submit">Search</button>
      </div>
      {expanded && (
        <div className="productSearchPanel">
          {status === "loading" && <p role="status">Searching…</p>}
          {status === "error" && (
            <p role="alert">
              Unable to load suggestions. Try changing your search.
            </p>
          )}
          {status === "ready" && !rows.length && (
            <p role="status">No available products found.</p>
          )}
          <ul id={listId} role="listbox" aria-label="Product suggestions">
            {rows.map((product, index) => (
              <li
                key={product.id}
                id={listId + "-" + index}
                role="option"
                aria-selected={index === active}
                className={index === active ? "selected" : ""}
                onMouseEnter={() => setActive(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => select(product)}
              >
                <ProductImage product={product} />
                <span className="productSearchDetails">
                  <strong>{product.display_name}</strong>
                  <span>{product.category}</span>
                  <span>
                    KSh {product.selling_price} · {product.available} available
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </form>
  );
}
