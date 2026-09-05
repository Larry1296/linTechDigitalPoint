import type { ShelfStack } from "../../types";

type PreviewLevel = { compartments: number };
export function StackPreview({
  name,
  code = "Permanent code generated on save",
  width,
  height,
  depth,
  levels,
  onShelf,
  stack,
  onEdit,
}: {
  name: string;
  code?: string;
  width: number;
  height: number;
  depth: number;
  levels: PreviewLevel[];
  onShelf?: (id: number) => void;
  stack?: ShelfStack;
  onEdit?: (stack: ShelfStack) => void;
}) {
  const rows = stack
    ? [...stack.levels]
        .sort((a, b) => b.level_number - a.level_number)
        .map((level) => ({
          number: level.level_number,
          shelves: level.shelves,
          compartments: level.shelves.length,
        }))
    : [...levels].reverse().map((level, index) => ({
        number: levels.length - index,
        shelves: [],
        compartments: level.compartments,
      }));
  return (
    <article className="stackPreview">
      <header>
        <div>
          <strong>{name || "New shelf stack"}</strong>
          <small>{stack?.code || code}</small>
        </div>
        <small>
          {width} × {height} × {depth} ft
        </small>
        {stack && onEdit && (
          <button className="secondary rackEdit" onClick={() => onEdit(stack)}>
            Move / Edit Rack
          </button>
        )}
      </header>
      <div className="rackFrame">
        {rows.map((level) => (
          <section className="rackLevelGroup" key={level.number}>
            <small className="rackLevelLabel">Level {level.number}</small>
            <div className="rackLevel">
              {level.shelves.length
                ? level.shelves.map((shelf) => (
                    <button
                      type="button"
                      key={shelf.id}
                      title={`${shelf.code} — ${shelf.display_name}`}
                      aria-label={`Level ${level.number}, ${shelf.physical_label || `Shelf ${shelf.position_in_level}`}, ${shelf.total_quantity} units`}
                      onClick={() => onShelf?.(shelf.id)}
                    >
                      <b>
                        {shelf.physical_label ||
                          `Shelf ${shelf.position_in_level}`}
                      </b>
                      <small>{shelf.total_quantity} units</small>
                    </button>
                  ))
                : Array.from({ length: level.compartments }, (_, index) => (
                    <div key={index}>
                      <b>Shelf {index + 1}</b>
                    </div>
                  ))}
            </div>
          </section>
        ))}
      </div>
    </article>
  );
}
