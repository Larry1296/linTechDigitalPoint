import { useState } from "react";
import { saveCategory } from "./api";

export function CategoryManager({ categories, onSaved, canAdd = true, canChange = true }) {
  const [editing, setEditing] = useState(null);
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [active, setActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const reset = () => { setEditing(null); setName(""); setParent(""); setActive(true); setError(""); };
  const edit = (category) => {
    setEditing(category.id); setName(category.name); setParent(category.parent || "");
    setActive(category.active); setError(""); setMessage("");
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
    setSaving(true); setError(""); setMessage("");
    try {
      const result = await saveCategory(editing, { name: name.trim(), parent: parent ? Number(parent) : null, active });
      onSaved(result);
      reset();
      setMessage(`${result.name} ${editing ? "updated" : "created"}.`);
    } catch (error) { setError(error.message); }
    finally { setSaving(false); }
  };
  return <section className="onboarding" aria-labelledby="category-heading">
    <h2 id="category-heading">Merchandise categories</h2>
    {!categories.length ? <p>Start by creating your first category: Mobile Accessories. Choose “Root category” below. You can add photographed products and their locations later.</p> : <p>Organize the kinds of products you sell. Add subcategories when you need them.</p>}
    {message && <p role="status">{message}</p>}
    {error && <p role="alert">{error}</p>}
    {(editing ? canChange : canAdd) && <form onSubmit={submit}>
      <h3>{editing ? "Edit category" : "Create category"}</h3>
      <fieldset disabled={saving}>
        <label>Category name<input value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} placeholder="Mobile Accessories" /></label>
        <label>Parent category<select value={parent} onChange={(event) => setParent(event.target.value)}>
          <option value="">Root category</option>
          {categories.filter((category) => !isDescendant(category)).map((category) => <option key={category.id} value={category.id}>{category.name}{category.active ? "" : " (inactive)"}</option>)}
        </select></label>
        {editing && <label><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />Active category</label>}
        <button type="submit" disabled={!name.trim()}>{saving ? "Saving…" : editing ? "Save category" : "Create category"}</button>
        {editing && <button type="button" className="secondary" onClick={reset}>Cancel</button>}
      </fieldset>
    </form>}
    {categories.length > 0 && <table><thead><tr><th>Name</th><th>Parent</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>{[...categories].sort((a, b) => a.name.localeCompare(b.name)).map((category) => <tr key={category.id}>
        <td>{category.name}</td><td>{categories.find((item) => item.id === category.parent)?.name || "Root category"}</td>
        <td>{category.active ? "Active" : "Inactive"}</td><td>{canChange && <button type="button" disabled={saving} className="secondary" onClick={() => edit(category)} aria-label={`Edit ${category.name}`}>Edit</button>}</td>
      </tr>)}</tbody></table>}
  </section>;
}
