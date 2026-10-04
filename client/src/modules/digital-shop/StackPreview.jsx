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
}) {
  // Levels count up from the floor: Level 1 is the lowest, just above the floor, so it is drawn at the bottom.
  const rows = stack
    ? [...stack.levels]
        .sort((a, b) => b.level_number - a.level_number)
        .map((level) => ({
          number: level.level_number,
          shelves: level.shelves,
          compartments: level.shelves.length,
        }))
    : [...levels].map((level, index) => ({
        number: index + 1,
        shelves: [],
        compartments: level.compartments,
      })).reverse();
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
            Edit rack
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
      <div className="rackFloor" aria-hidden="true">Floor</div>
    </article>
  );
}
