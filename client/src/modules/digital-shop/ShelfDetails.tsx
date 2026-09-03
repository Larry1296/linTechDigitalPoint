import { useEffect, useState } from "react";
import { Empty, Loading } from "../../components/States";
import { loadShelfContents, updateShelf, type ShelfContents } from "./api";

export function ShelfDetails({
  shelfId,
  onClose,
  onUpdated,
}: {
  shelfId: number;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const [data, setData] = useState<ShelfContents>();
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    void loadShelfContents(shelfId).then(setData);
  }, [shelfId]);
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  const save = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    await updateShelf(
      shelfId,
      Object.fromEntries(new FormData(e.currentTarget)),
    );
    setEditing(false);
    onUpdated();
    setData(await loadShelfContents(shelfId));
  };
  return (
    <div className="shelfOverlay" role="presentation" onMouseDown={onClose}>
      <aside
        className="shelfPanel"
        role="dialog"
        aria-modal="true"
        aria-label="Shelf details"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="shelfPanelHeader">
          <span className="eyebrow">Exact physical shelf</span>
          <button
            className="shelfClose"
            onClick={onClose}
            aria-label="Close shelf details"
          >
            × <span>Close</span>
          </button>
        </div>
        {!data ? (
          <Loading />
        ) : (
          <>
            <h2>{data.shelf.code}</h2>
            <p>
              {data.shelf.physical_label || "No physical sticker label"} ·{" "}
              {data.shelf.display_name}
            </p>
            {editing ? (
              <form className="formCard" onSubmit={save}>
                <label>
                  Physical label
                  <input
                    name="physical_label"
                    defaultValue={data.shelf.physical_label}
                  />
                </label>
                <label>
                  Display name
                  <input
                    name="display_name"
                    defaultValue={data.shelf.display_name}
                  />
                </label>
                <button>Save shelf</button>
              </form>
            ) : (
              <button onClick={() => setEditing(true)}>Edit Shelf</button>
            )}
            <h3>Items</h3>
            {data.items.length ? (
              data.items.map((item) => (
                <article key={item.variant_id}>
                  <b>
                    {item.product} / {item.variant}
                  </b>
                  <span>
                    {item.quantity} total · {item.reserved} reserved ·{" "}
                    {item.available} available
                  </span>
                  <small>
                    Cost KSh {item.cost_value} · Retail KSh {item.retail_value}
                  </small>
                </article>
              ))
            ) : (
              <Empty>No stock is currently stored here.</Empty>
            )}
            <div className="shelfActions">
              <button>Add / Assign Item</button>
              <button>Receive Stock Here</button>
              <button>Transfer Stock</button>
              <button>Stocktake</button>
              <button onClick={() => window.print()}>Print Label</button>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
