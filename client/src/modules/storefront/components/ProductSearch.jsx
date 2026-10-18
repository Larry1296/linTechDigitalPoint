import { businessCurrency } from "../../../core/organization/presentation";
import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../../core/api/client";
import { ProductImage } from "./ProductImage";
import { TextBox } from "../../../components/forms/TextBox";

export function ProductSearch({
  value,
  onChange,
  onSearch,
  endpoint = "/api/v1/store/search-suggestions/",
  onSelect,
  renderResult,
  renderActions,
  isDisabled = () => false,
  exactScan = false,
  placeholder = "Search all available products…",
  minLength = 2,
  limit = 8,
  embedded = false,
  label = "Search products",
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
  const scanVersion = useRef(0);
  useEffect(
    () => () => {
      scanVersion.current++;
    },
    [],
  );
  const trimmed = query.trim();
  const expanded = open && trimmed.length >= minLength;

  useEffect(() => {
    if (!expanded) return;
    let current = true;
    const version = scanVersion.current;
    const controller = new AbortController();
    setRows([]);
    setActive(-1);
    setStatus("loading");
    const timer = setTimeout(() => {
      api(endpoint + "?q=" + encodeURIComponent(trimmed), {
        signal: controller.signal,
      })
        .then((results) => {
          if (!current || version !== scanVersion.current) return;
          setRows(results.slice(0, limit));
          setStatus("ready");
        })
        .catch(() => {
          if (current && version === scanVersion.current) setStatus("error");
        });
    }, 250);
    return () => {
      current = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, expanded, endpoint, limit]);

  useEffect(() => {
    const outside = (event) => {
      if (!root.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);

  useEffect(() => {
    if (expanded && active >= 0) {
      document
        .getElementById(listId + "-" + active)
        ?.scrollIntoView?.({ block: "nearest" });
    }
  }, [active, expanded, listId]);

  const select = (product) => {
    if (isDisabled(product)) return;
    scanVersion.current++;
    setOpen(false);
    if (onSelect) onSelect(product);
    else navigate("/products/" + product.id);
  };
  const search = async (event) => {
    event.preventDefault();
    setOpen(false);
    if (exactScan && !trimmed) return;
    if (exactScan && trimmed) {
      const version = ++scanVersion.current;
      setStatus("loading");
      setOpen(true);
      try {
        const results = await api(
          endpoint + "?q=" + encodeURIComponent(trimmed),
        );
        if (version !== scanVersion.current) return;
        setRows(results.slice(0, limit));
        setStatus("ready");
        const exact = results.find((row) =>
          [row.sku, row.barcode].some(
            (code) => code?.toLowerCase() === trimmed.toLowerCase(),
          ),
        );
        if (exact) select(exact);
      } catch {
        if (version === scanVersion.current) setStatus("error");
      }
      return;
    }
    if (onSearch) onSearch(trimmed);
    else navigate("/shop?" + new URLSearchParams({ search: trimmed }));
  };

  // Inside another form (e.g. Stock Adjustment) a nested <form> would submit the outer one, so render a div.
  const Root = embedded ? "div" : "form";
  return (
    <Root
      className="productSearch"
      ref={root}
      onSubmit={embedded ? undefined : search}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <div className="productSearchControls">
        <TextBox
          role="combobox"
          aria-label={label}
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
            scanVersion.current++;
            updateQuery(event.target.value);
            setRows([]);
            setActive(-1);
            setOpen(Boolean(event.target.value.trim()));
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              scanVersion.current++;
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
            } else if (
              event.key === "Enter" &&
              !event.nativeEvent.isComposing
            ) {
              search(event);
            }
          }}
        />
        <button type={embedded ? "button" : "submit"} onClick={embedded ? search : undefined}>Search</button>
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
                aria-disabled={isDisabled(product)}
                className={index === active ? "selected" : ""}
                onMouseEnter={() => setActive(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => select(product)}
              >
                {renderResult ? (
                  renderResult(product)
                ) : (
                  <>
                    <ProductImage product={product} />
                    <span className="productSearchDetails">
                      <strong>{product.display_name}</strong>
                      <span>{product.category}</span>
                      <span>
                        {businessCurrency()} {product.selling_price} · {product.available}{" "}
                        available
                      </span>
                    </span>
                  </>
                )}
              </li>
            ))}
          </ul>
          {renderActions && rows[active] && renderActions(rows[active])}
        </div>
      )}
    </Root>
  );
}
