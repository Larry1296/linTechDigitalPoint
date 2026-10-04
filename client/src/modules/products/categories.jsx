// Category choices come from /inventory/categories/available/: every active category, in hierarchy
// order, labelled child first ("Wall Chargers – Mobile Accessories"). A sub-category is stored on its
// nearest parent's rack; one with no rack yet is shown but can't be chosen.
const find = (categories, id) => categories.find((c) => String(c.id) === String(id));

export const categoryUsable = (category) => category.available !== false;

/** The category and all of its sub-categories, for filtering products. */
export function categoryFamily(categories, id) {
  return (find(categories, id)?.descendant_ids ?? [id]).map(Number);
}

/** Whether a rack may hold stock of this category (directly or through a parent). */
export function rackHolds(stack, categories, id) {
  const rackIds = find(categories, id)?.rack_ids;
  if (rackIds) return rackIds.includes(stack.id);
  return (stack.categories || []).some((c) => String(c.id) === String(id));
}

export function CategoryOptions({ categories }) {
  return categories.map((category) => (
    <option key={category.id} value={category.id} disabled={!categoryUsable(category)}>
      {category.name}{categoryUsable(category) ? "" : " (not on a rack yet)"}
    </option>
  ));
}

export function UnrackedHint({ categories }) {
  if (categories.every(categoryUsable)) return null;
  return <small className="muted">Greyed-out categories aren't on a rack yet. Assign them to a rack in Shelf management to use them.</small>;
}
