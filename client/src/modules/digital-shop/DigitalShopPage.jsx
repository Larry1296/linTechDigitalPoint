import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Empty, ErrorState, Loading } from "../../components/States";
import { loadZones, loadCategories } from "./api";
import { ShelfDetails } from "./ShelfDetails";
import { StackBuilder } from "./StackBuilder";
import { StackEditor } from "./StackEditor";
import { StackPreview } from "./StackPreview";
import { AreaManager } from "./AreaManager";
import { useAuth } from "../../core/auth/AuthContext";
export function DigitalShopPage() {
  const { user } = useAuth();
  const [categories, setCategories] = useState();
  const [zones, setZones] = useState();
  const [selected, setSelected] = useState();
  const [builder, setBuilder] = useState(false);
  const [shelf, setShelf] = useState();
  const [editingStack, setEditingStack] = useState();
  const [error, setError] = useState("");
  const load = () =>
    Promise.all([loadZones(), loadCategories()])
      .then(([rows, categoryRows]) => {
        setCategories(categoryRows);
        setZones(rows);
        setSelected((value) => value || rows[0]?.id);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, []);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!zones || !categories) return <Loading />;
  const hasCategories = categories.some((category) => category.active);
  if (builder)
    return (
      <StackBuilder
        zones={zones}
        initialZone={selected}
        onCancel={() => setBuilder(false)}
        onCreated={(zoneId) => {
          setBuilder(false);
          setSelected(zoneId);
          void load();
        }}
      />
    );
  const zone = zones.find((item) => item.id === selected);
  return (
    <>
      <span className="eyebrow">Physical locations · {user.organization?.name}</span>
      <h1>Shelf Management</h1>
      <p className="muted">Map your real shop so anyone can find the exact shelf where an item is kept.</p>
      <ol className="shopGuide" aria-label="How your shop is organised">
        <li><strong>Area</strong><span>A wall or section of the shop, such as Left Wall or Counter.</span></li>
        <li><strong>Rack</strong><span>A shelving unit standing in an area. It holds one or more product categories.</span></li>
        <li><strong>Shelf</strong><span>A compartment on a rack level, where stock is actually placed.</span></li>
      </ol>
      {!hasCategories && <p className="callout">
        Racks hold product categories. Create at least one on the <Link to="/admin/categories">Categories</Link> page before adding a rack.
      </p>}
      <AreaManager zones={zones} selected={selected} onSelect={setSelected}
        canAdd={user.is_superuser || user.permissions.includes("inventory.add_zone")}
        canChange={user.is_superuser || user.permissions.includes("inventory.change_zone")}
        canAddRack={hasCategories && (user.is_superuser || user.permissions.includes("inventory.add_shelfstack"))}
        onAddRack={() => setBuilder(true)}
        onChanged={async (zoneId) => {
          const rows = await loadZones();
          setZones(rows);
          setSelected((value) => (zoneId && rows.some((row) => row.id === zoneId)) ? zoneId
            : rows.some((row) => row.id === value) ? value : rows[0]?.id);
        }} />
      {zone && (
        <section
          className="shopLayout"
          style={{ aspectRatio: +zone.width / +zone.height }}
        >
          {zone.stacks.map((stack) => (
            <div
              className="placedStack"
              key={stack.id}
              style={{
                left: Math.max(0, Math.min(+stack.x / +zone.width, 1 - +stack.width / +zone.width)) * 100 + "%",
                top: (+stack.y / +zone.height) * 100 + "%",
                width: Math.min(100, (+stack.width / +zone.width) * 100) + "%",
              }}
            >
              <StackPreview
                stack={stack}
                name={stack.display_name}
                width={+stack.width}
                height={+stack.height}
                depth={+stack.depth}
                levels={[]}
                onShelf={setShelf}
                onEdit={setEditingStack}
              />
              {stack.categories?.length ? <small className="muted rackCategories">{stack.categories.map((category) => category.name).join(" · ")}</small> : null}
            </div>
          ))}
          {!zone.stacks.length && (
            <Empty>No racks in {zone.name} yet. Use “Add rack to {zone.name}” above.</Empty>
          )}
        </section>
      )}
      {zone?.unassigned_shelves.length ? (
        <section>
          <h2>Unassigned physical shelves</h2>
          <p className="muted">
            Legacy shelves remain safe with their inventory. Move them into a
            real rack when its structure is configured.
          </p>
        </section>
      ) : null}
      {shelf && (
        <ShelfDetails
          shelfId={shelf}
          onClose={() => setShelf(undefined)}
          onUpdated={() => void load()}
        />
      )}
      {editingStack && (
        <StackEditor
          stack={editingStack}
          zones={zones}
          onClose={() => setEditingStack(undefined)}
          onChanged={(zoneId) => {
            setEditingStack(undefined);
            if (zoneId) setSelected(zoneId);
            void load();
          }}
        />
      )}
    </>
  );
}
