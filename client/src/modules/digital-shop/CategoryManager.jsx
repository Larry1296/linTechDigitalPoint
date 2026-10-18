import { useMemo, useRef, useState } from "react";
import { deleteCategory, saveCategory } from "./api";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { TextBox } from "../../components/forms/TextBox";

const byName = (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" });

/** Categories in tree order (each parent followed by its sub-categories, A–Z per level), with depth, path and rack details. */
export function categoryTree(categories) {
  const byId = new Map(categories.map((c) => [c.id, c]));
  const children = new Map();
  for (const category of categories) {
    const parent = byId.has(category.parent) ? category.parent : null;
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(category);
  }
  const rows = [];
  const seen = new Set();
  const walk = (parentId, depth, path, inheritedRacks) => {
    for (const category of (children.get(parentId) || []).sort(byName)) {
      if (seen.has(category.id)) continue;
      seen.add(category.id);
      const row = { category, depth, path: [...path, category.name], inheritedRacks, index: rows.length };
      rows.push(row);
      const own = category.racks?.length ? { from: category.name, racks: category.racks } : null;
      walk(category.id, depth + 1, row.path, own || inheritedRacks);
      row.descendants = rows.length - row.index - 1;
      row.totalProducts = rows.slice(row.index).reduce((sum, r) => sum + (r.category.product_count || 0), 0);
    }
  };
  walk(null, 0, [], null);
  // A broken parent loop is still listed rather than hidden.
  for (const category of categories.filter((c) => !seen.has(c.id)).sort(byName)) {
    rows.push({ category, depth: 0, path: [category.name], inheritedRacks: null, descendants: 0, totalProducts: category.product_count || 0 });
  }
  return rows;
}

function RackCell({ row }) {
  const { category, inheritedRacks } = row;
  if (category.racks?.length) return category.racks.join(", ");
  if (inheritedRacks) return <span className="muted">{inheritedRacks.racks.join(", ")} <small>(through {inheritedRacks.from})</small></span>;
  return <span className="categoryWarning">Not on a rack</span>;
}

export function CategoryManager({ categories, onSaved, onDeleted, canAdd = true, canChange = true, canDelete = true }) {
  const [editing, setEditing] = useState(null);
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [active, setActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [confirmingId, setConfirmingId] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [place, setPlace] = useState("form");
  const [search, setSearch] = useState("");
  const formRef = useRef(null);
  const tree = useMemo(() => categoryTree(categories), [categories]);
  const pathOf = useMemo(() => new Map(tree.map((row) => [row.category.id, row.path.join(" › ")])), [tree]);

  const showForm = () => formRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  const reset = () => { setEditing(null); setName(""); setParent(""); setActive(true); setError(""); };
  const edit = (category) => {
    setEditing(category.id); setName(category.name); setParent(category.parent || "");
    setActive(category.active); setError(""); setMessage(""); showForm();
  };
  const addChild = (category) => {
    reset(); setParent(String(category.id)); setMessage(""); showForm();
  };
  const remove = async (category) => {
    setDeletingId(category.id); setError(""); setMessage(""); setPlace("list");
    try {
      await deleteCategory(category.id);
      if (editing === category.id) reset();
      onDeleted(category.id);
      setMessage(`${category.name} deleted.`);
    } catch (error) { setError({ title: `Could not delete ${category.name}.`, message: error.message }); }
    finally { setDeletingId(null); setConfirmingId(null); }
  };
  const isDescendant = (category) => {
    const seen = new Set();
    let current = category;
    while (current && !seen.has(current.id)) {
      if (current.id === editing) return true;
      seen.add(current.id);
      current = categories.find((item) => item.id === current.parent);
    }
    return false;
  };
  const submit = async (event) => {
    event.preventDefault();
    if (saving || !name.trim()) return;
    setSaving(true); setError(""); setMessage(""); setPlace("form");
    try {
      const result = await saveCategory(editing, { name: name.trim(), parent: parent ? Number(parent) : null, active });
      onSaved(result);
      reset();
      setMessage(`${result.name} ${editing ? "updated" : "created"}.`);
    } catch (error) { setError({ title: editing ? "Could not save the category." : "Could not create the category.", message: error.message }); }
    finally { setSaving(false); }
  };

  // A search keeps each match's parents visible, so it is clear where the match sits.
  const query = search.trim().toLowerCase();
  const visible = useMemo(() => {
    if (!query) return tree;
    const keep = new Set();
    for (const row of tree) {
      if (row.category.name.toLowerCase().includes(query)) {
        let current = row.category;
        while (current && !keep.has(current.id)) {
          keep.add(current.id);
          current = categories.find((item) => item.id === current.parent);
        }
      }
    }
    return tree.filter((row) => keep.has(row.category.id));
  }, [tree, query, categories]);
  const unracked = tree.filter((row) => row.category.active && !row.category.racks?.length && !row.inheritedRacks).length;

  return <section className="onboarding categoryManager" aria-labelledby="category-heading">
    <h2 id="category-heading">Merchandise categories</h2>
    {!categories.length
      ? <p>Start by creating your first category: Mobile Accessories. Choose “Root category” below. You can add photographed products and their locations later.</p>
      : <>
        <p>Top-level categories are listed with their sub-categories indented beneath them. A sub-category is stored on its parent’s rack.</p>
        <dl className="factTiles">
          <div><dt>Categories</dt><dd>{categories.length}</dd></div>
          <div><dt>Top-level</dt><dd>{tree.filter((row) => row.depth === 0).length}</dd></div>
          <div className={unracked ? "restock" : ""}><dt>Not on a rack</dt><dd>{unracked}</dd></div>
        </dl>
      </>}
    {(editing ? canChange : canAdd) && <form onSubmit={submit} ref={formRef}>
      <h3>{editing ? "Edit category" : parent ? "Add sub-category" : "Create category"}</h3>
      <fieldset disabled={saving}>
        <label>Category name<TextBox value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} placeholder="Mobile Accessories" /></label>
        <label>Parent category<select value={parent} onChange={(event) => setParent(event.target.value)}>
          <option value="">Root category</option>
          {tree.filter((row) => !isDescendant(row.category)).map(({ category }) => (
            <option key={category.id} value={category.id}>{pathOf.get(category.id)}{category.active ? "" : " (inactive)"}</option>
          ))}
        </select></label>
        {editing && <label className="checkRow"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} /> Active category</label>}
        <button type="submit" className="categorySubmit" disabled={!name.trim()}>{saving ? "Saving…" : editing ? "Save category" : "Create category"}</button>
        {(editing || parent) && <button type="button" className="secondary" onClick={reset}>Cancel</button>}
      </fieldset>
      {place === "form" && <><FormSuccess message={message} /><FormError title={error.title} message={error.message} /></>}
    </form>}
    {categories.length > 0 && <>
      {categories.length > 8 && <label className="categorySearch">Find a category
        <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="e.g. Tapes" />
      </label>}
      {query && !visible.length && <p className="muted">No category matches “{search}”.</p>}
      <div className="tableWrap"><table className="responsiveTable categoryTree">
        <thead><tr><th>Category</th><th>Products</th><th>Rack</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>{visible.map((row) => {
          const { category, depth } = row;
          const hasChildren = row.descendants > 0;
          return <tr key={category.id} data-depth={Math.min(depth, 4)} className={category.active ? "" : "inactiveCategory"}>
            <td data-label="Category" className="categoryName" style={{ "--depth": depth }}>
              <span>{category.name}</span>
              {depth > 0 && <small className="muted categoryPath">{row.path.slice(0, -1).join(" › ")}</small>}
            </td>
            <td data-label="Products">
              <span>{category.product_count ?? "—"}</span>
              {hasChildren && row.totalProducts > (category.product_count || 0) && <small className="muted"> ({row.totalProducts} with sub-categories)</small>}
            </td>
            <td data-label="Rack"><RackCell row={row} /></td>
            <td data-label="Status">{category.active ? "Active" : "Inactive"}</td>
            <td data-label="Actions"><div className="categoryActions">
              {canAdd && <button type="button" className="categoryAdd" disabled={saving} onClick={() => addChild(category)} aria-label={`Add sub-category to ${category.name}`}>+ Sub-category</button>}
              {canChange && <button type="button" disabled={saving || deletingId === category.id} className="categoryEdit" onClick={() => edit(category)} aria-label={`Edit ${category.name}`}>Edit</button>}
              {canDelete && (confirmingId === category.id ? <>
                <button type="button" className="categoryDelete" disabled={deletingId === category.id} onClick={() => void remove(category)} aria-label={`Confirm delete ${category.name}`}>
                  {deletingId === category.id ? "Deleting…" : "Confirm delete"}
                </button>
                <button type="button" className="categoryCancel" disabled={deletingId === category.id} onClick={() => setConfirmingId(null)}>Cancel</button>
              </> : <button
                type="button"
                className="categoryDelete"
                disabled={saving || hasChildren}
                title={hasChildren ? "Remove or reassign its subcategories first" : undefined}
                onClick={() => setConfirmingId(category.id)}
                aria-label={`Delete ${category.name}`}
              >
                Delete
              </button>)}
            </div></td>
          </tr>;
        })}</tbody>
      </table></div>
    </>}
    {place === "list" && <><FormSuccess message={message} /><FormError title={error.title} message={error.message} /></>}
  </section>;
}
