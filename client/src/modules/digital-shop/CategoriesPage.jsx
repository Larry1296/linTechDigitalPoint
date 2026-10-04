import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorState, Loading } from "../../components/States";
import { BackLink } from "../../components/navigation/BackLink";
import { useAuth } from "../../core/auth/AuthContext";
import { loadCategories } from "./api";
import { CategoryManager } from "./CategoryManager";

export function CategoriesPage() {
  const { user } = useAuth();
  const [categories, setCategories] = useState();
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    loadCategories().then(setCategories).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  if (error && !categories) return <ErrorState message={error} retry={load} />;
  if (!categories) return <Loading />;
  // Changes reload the list so product counts and rack names stay accurate.
  const can = (action) => user.is_superuser || user.permissions.includes(`catalog.${action}_category`);
  return <>
    <BackLink />
    <span className="eyebrow">Inventory</span>
    <h1>Product categories</h1>
    <p className="muted">
      Categories group the kinds of items you sell, such as Mobile Accessories or Computer Accessories.
      Every product belongs to one category, and each rack in{" "}
      <Link to="/admin/shelf-management">Shelf Management</Link> holds one or more categories.
    </p>
    <CategoryManager categories={categories}
      canAdd={can("add")} canChange={can("change")} canDelete={can("delete")}
      onSaved={load} onDeleted={load} />
  </>;
}
