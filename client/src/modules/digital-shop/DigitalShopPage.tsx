import { useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "../../components/States";
import type { ShelfStack, Zone } from "../../types";
import { loadZones } from "./api";
import { ShelfDetails } from "./ShelfDetails";
import { StackBuilder } from "./StackBuilder";
import { StackEditor } from "./StackEditor";
import { StackPreview } from "./StackPreview";

export function DigitalShopPage() {
  const [zones, setZones] = useState<Zone[]>();
  const [selected, setSelected] = useState<number>();
  const [builder, setBuilder] = useState(false);
  const [shelf, setShelf] = useState<number>();
  const [editingStack, setEditingStack] = useState<ShelfStack>();
  const [error, setError] = useState("");
  const load = () =>
    loadZones()
      .then((rows) => {
        setZones(rows);
        setSelected((value) => value || rows[0]?.id);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, []);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!zones) return <Loading />;
  if (builder)
    return (
      <StackBuilder
        zones={zones}
        onCancel={() => setBuilder(false)}
        onCreated={(zoneId) => {
          setBuilder(false);
          setSelected(zoneId);
          void load();
        }}
      />
    );
  const zone = zones.find((item) => item.id === selected);
  const hasStacks = zones.some((item) => item.stacks.length);
  return (
    <>
      <span className="eyebrow">Digital twin of LinTech Digital Point</span>
      <div className="heading">
        <div>
          <h1>Digital Shop</h1>
          <p className="muted">
            Reproduce where each real shelving stack stands, then locate stock
            in its exact level and compartment.
          </p>
        </div>
        <button onClick={() => setBuilder(true)}>
          {hasStacks ? "Add Shelf Stack" : "Create First Shelf Stack"}
        </button>
      </div>
      {!hasStacks && (
        <section className="onboarding">
          <h2>Configure Your Physical Shop</h2>
          <p>
            Recreate the shelving structures that already exist in LinTech
            Digital Point.
          </p>
          <ol>
            <li>
              Define any area that exists in your shop and enter its real size
            </li>
            <li>Add the shelving unit that physically stands there</li>
            <li>Enter its dimensions and levels</li>
            <li>Create and label each compartment</li>
            <li>Assign products to exact physical locations</li>
          </ol>
        </section>
      )}
      <div className="tabs">
        {zones.map((item) => (
          <button
            className={item.id === selected ? "active" : ""}
            onClick={() => setSelected(item.id)}
            key={item.id}
          >
            {item.name}
          </button>
        ))}
      </div>
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
                left: (+stack.x / +zone.width) * 100 + "%",
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
            </div>
          ))}
          {!zone.stacks.length && (
            <Empty>No shelf stacks configured in {zone.name}.</Empty>
          )}
        </section>
      )}
      {zone?.unassigned_shelves.length ? (
        <section>
          <h2>Unassigned physical shelves</h2>
          <p className="muted">
            Legacy shelves remain safe with their inventory. Move them into a
            real stack when its structure is configured.
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
