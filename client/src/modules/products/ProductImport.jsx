import { useState } from "react";
import { api, apiBlob } from "../../core/api/client";
import { businessCurrency } from "../../core/organization/presentation";
import { FormError, FormInfo, FormSuccess } from "../../components/forms/FormNotice";

const count = (value) => Number(value || 0).toLocaleString();
const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const plural = (n, one, many) => `${count(n)} ${Number(n) === 1 ? one : many}`;
const ACTIONS = { create: "New", skip: "Already in system" };

// The Excel template comes from the server so its dropdowns list this business's categories, brands and shelves.
export async function downloadTemplate() {
  save(await apiBlob("/api/v1/catalog/products/import-template/"), "products-template.xlsx");
}

function save(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  link.click();
  URL.revokeObjectURL(url);
}

const csvCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;

/** One line per problem: row, column, SKU, product and the message, ready to fix in Excel. */
export function errorReport(result) {
  const lines = [["row", "column", "sku", "name", "error"]];
  for (const message of result.summary.file_errors || []) lines.push(["", "", "", "", message]);
  for (const row of result.rows) {
    for (const error of row.errors) lines.push([row.row, error.column || "", row.sku, row.name, error.message]);
  }
  return lines.map((line) => line.map(csvCell).join(",")).join("\r\n");
}

function RackChoices({ summary, choices, onChoose }) {
  if (!summary.rack_issues.length) return null;
  const racks = summary.racks || [];
  return (
    <section className="importRacks" aria-label="Categories that need a rack">
      <h3>Categories that need a rack</h3>
      <p className="muted">
        Racks are in use, so each category must be on a rack before it can hold products. Choose a rack for each category below
        (a parent category covers its sub-categories), then check again. Nothing is assigned until you choose.
      </p>
      {racks.length === 0 && <FormInfo>There are no active racks yet. Add one under Shelf management first.</FormInfo>}
      {summary.rack_issues.map((issue) => (
        <div key={issue.category} className="importRackChoice">
          <label>
            {issue.category}{issue.new ? " (new)" : ""} — rows {issue.rows.join(", ")}
            <select value={choices[issue.category] ?? ""} onChange={(event) => onChoose(issue.category, event.target.value)}>
              <option value="">Choose a rack…</option>
              {racks.map((rack) => (
                <option key={rack.id} value={rack.id}>
                  {rack.name} ({rack.area}){issue.suggested_racks.includes(rack.id) ? " — holds this file's shelf" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
      ))}
    </section>
  );
}

function RowTable({ rows }) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr><th>Row</th><th>Product</th><th>SKU</th><th>Category</th><th>Shelf</th><th>Qty</th><th>Unit cost</th><th>Value</th><th>Result</th></tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.row}>
              <th scope="row">{row.row}</th>
              <td>{row.name || "—"}{row.variant_name && row.variant_name !== "Standard" ? ` · ${row.variant_name}` : ""}{row.product_type === "SERVICE" ? " (service)" : ""}</td>
              <td><code>{row.sku || "—"}</code></td>
              <td>{row.category || "—"}</td>
              <td>{row.shelf || "—"}</td>
              <td>{Number(row.opening_quantity) ? count(row.opening_quantity) : "—"}</td>
              <td>{Number(row.opening_quantity) ? money(row.opening_unit_cost) : "—"}</td>
              <td>{Number(row.opening_quantity) ? money(row.opening_value) : "—"}</td>
              <td>
                {row.errors.length ? (
                  <ul className="importErrors">
                    {row.errors.map((error, index) => <li key={index}><strong>{error.column}</strong>: {error.message}</li>)}
                  </ul>
                ) : (
                  <>{ACTIONS[row.action]}{row.notes.length > 0 && <small className="muted"> {row.notes.join(" ")}</small>}</>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Upload, review every row, then import all of them together. Nothing is saved until the review is clean and confirmed.
export function ProductImport({ onClose, onImported }) {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [choices, setChoices] = useState({});
  const [onlyProblems, setOnlyProblems] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const send = async (commit) => {
    const data = new FormData();
    data.set("file", file);
    data.set("commit", commit ? "true" : "false");
    const chosen = Object.fromEntries(Object.entries(choices).filter(([, rack]) => rack));
    if (Object.keys(chosen).length) data.set("rack_choices", JSON.stringify(chosen));
    setBusy(true);
    setError("");
    try {
      setResult(await api("/api/v1/catalog/products/import/", { method: "POST", body: data }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const summary = result?.summary;
  const problems = result?.rows.filter((row) => row.errors.length) || [];
  const blocked = summary && summary.error_count > 0;

  if (result?.committed)
    return (
      <section className="formCard productImport">
        <h2>{result.reference ? "Products imported" : "Nothing new to import"}</h2>
        {result.reference ? (
          <FormSuccess>
            {plural(summary.create, "product", "products")} created under reference {result.reference}
            {Number(summary.total_quantity) > 0 && `, with ${count(summary.total_quantity)} units of opening stock worth ${money(summary.opening_value)}`}.
            {summary.skip > 0 && ` ${plural(summary.skip, "row was", "rows were")} already in the system and skipped.`}
          </FormSuccess>
        ) : (
          <FormInfo>Every row in this file is already in the system{summary.previous_import ? ` (${summary.previous_import.reference})` : ""}. No products or stock were added.</FormInfo>
        )}
        {summary.new_categories.length > 0 && result.reference && <p><strong>Categories created:</strong> {summary.new_categories.join(", ")}</p>}
        {summary.rack_choices.length > 0 && result.reference && (
          <p><strong>Racks assigned:</strong> {summary.rack_choices.map((c) => `${c.category} → ${c.rack}`).join(", ")}</p>
        )}
        <p className="muted">Imported products are for stock management only: they are not visible or orderable online. Add photos and publish them from each product page if you ever want them online.</p>
        <button type="button" onClick={onImported}>Done</button>
      </section>
    );

  return (
    <section className="formCard productImport">
      <button type="button" className="pageBackLink" onClick={onClose}>← Back</button>
      <h2>Import products from Excel</h2>
      <p>
        Download the template, fill one row per sellable product or variant, then upload it here. Each row is saved exactly as
        the Add Product form would save it. Required columns: <code>name</code>, <code>category</code> and <code>selling_price</code>.
        Keep the file and add new rows at the bottom next time: rows already imported are skipped.
      </p>
      <ul className="muted">
        <li>
          Write each category as its full path from the top, levels separated by <code>&gt;</code>:
          {" "}<code>Parent &gt; Child &gt; Grandchild</code> (any number of levels), e.g. <code>Mobile Accessories &gt; Chargers &gt; Car Chargers</code>.
          Existing levels are reused (case and spaces ignored); every missing level is created, parent first, exactly where you wrote it.
        </li>
        <li>Leave <code>sku</code> empty to use the code the form would suggest from the brand, name and variant.</li>
        <li>Sold in packs? Put the pieces in one pack in <code>pack_size</code> and what a piece is called in <code>piece_name</code>. The price is for one pack, and opening stock is counted in pieces at the buying price of one piece.</li>
        <li>Opening stock without a buying price is marked cost pending until you add the price; without a <code>preferred_shelf</code> it is kept as not yet placed.</li>
        <li><code>SERVICE</code> rows have no stock, shelf or barcode, and may have a <code>service_cost</code>.</li>
        <li>Imported products stay offline (not visible or orderable online), so photos aren't needed.</li>
        <li>Nothing is saved until you confirm, and then every row is saved or none. Uploading the same file again never doubles products or stock.</li>
      </ul>
      <button type="button" className="secondary" onClick={() => downloadTemplate().catch((e) => setError(e.message))}>Download Excel template</button>
      <label>
        Completed template (.xlsx)
        <input type="file" accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
          onChange={(event) => { setFile(event.target.files[0] || null); setResult(null); setChoices({}); setError(""); }} />
      </label>
      <button type="button" disabled={!file || busy} onClick={() => send(false)}>{busy ? "Checking…" : result ? "Check again" : "Check file"}</button>
      <FormError title="Could not check the file." message={error} />
      {summary && (
        <>
          {summary.previous_import && (
            <FormInfo>
              This exact file was imported before ({summary.previous_import.reference}, {new Date(summary.previous_import.created_at).toLocaleString()}).
              Rows already in the system are skipped.
            </FormInfo>
          )}
          <dl className="factTiles">
            <div><dt>New products</dt><dd>{count(summary.create)}</dd></div>
            <div><dt>Already in system</dt><dd>{count(summary.skip)}</dd></div>
            <div className={summary.errors ? "restock" : ""}><dt>Rows with errors</dt><dd>{count(summary.errors)}</dd></div>
            <div><dt>Opening units</dt><dd>{count(summary.total_quantity)}</dd></div>
            <div><dt>Opening stock value</dt><dd>{money(summary.opening_value)}</dd></div>
          </dl>
          {summary.new_categories.length > 0 && <p><strong>Categories to create:</strong> {summary.new_categories.join(", ")}</p>}
          {summary.new_brands.length > 0 && <p><strong>Brands to create:</strong> {summary.new_brands.join(", ")}</p>}
          {summary.rack_choices.length > 0 && <p><strong>Racks to assign:</strong> {summary.rack_choices.map((c) => `${c.category} → ${c.rack}`).join(", ")}</p>}
          <RackChoices summary={summary} choices={choices} onChoose={(category, rack) => setChoices((current) => ({ ...current, [category]: rack }))} />
          {summary.file_errors.map((message) => <FormError key={message} title="Check this" message={message} />)}
          {blocked ? (
            <>
              <FormError title={`${plural(summary.error_count, "problem", "problems")} in ${plural(summary.errors, "row", "rows")}.`}
                message="Fix them in your spreadsheet (or choose racks above), save, and check again. Nothing has been imported." />
              <button type="button" className="secondary"
                onClick={() => save(new Blob([errorReport(result)], { type: "text/csv" }), `${(file?.name || "products").replace(/\.[^.]+$/, "")}-errors.csv`)}>
                Download error report
              </button>
              <label className="inlineCheck">
                <input type="checkbox" checked={onlyProblems} onChange={(event) => setOnlyProblems(event.target.checked)} /> Show only rows with errors
              </label>
            </>
          ) : summary.create === 0 ? (
            <FormInfo>Nothing new to import: every row in this file is already in the system.</FormInfo>
          ) : (
            <FormInfo>
              Ready: {plural(summary.create, "new product", "new products")}
              {summary.services > 0 && ` (${plural(summary.services, "service", "services")})`}
              {summary.with_opening_stock > 0 && `, ${count(summary.with_opening_stock)} with opening stock: ${count(summary.total_quantity)} units worth ${money(summary.opening_value)}`}
              {summary.skip > 0 && `. ${plural(summary.skip, "row was", "rows were")} already in the system and will be skipped`}.
              Check the new categories and brands above for typos before importing.
            </FormInfo>
          )}
          <RowTable rows={blocked && onlyProblems ? problems : result.rows} />
          {!blocked && summary.create > 0 && (
            <button type="button" disabled={busy} onClick={() => send(true)}>
              {busy ? "Importing…" : `Import ${plural(summary.create, "product", "products")}`}
            </button>
          )}
        </>
      )}
    </section>
  );
}
