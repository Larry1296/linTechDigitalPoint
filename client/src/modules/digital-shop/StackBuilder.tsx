import { useMemo, useState } from "react";
import type { Zone } from "../../types";
import { createStack, createZone } from "./api";
import { StackPreview } from "./StackPreview";

export function StackBuilder({
  zones,
  onCreated,
  onCancel,
}: {
  zones: Zone[];
  onCreated: (zoneId: number) => void;
  onCancel: () => void;
}) {
  const [step, setStep] = useState(1);
  const [zone, setZone] = useState(zones[0]?.id || 0);
  const [newArea, setNewArea] = useState(zones.length === 0);
  const [areaName, setAreaName] = useState("");
  const [areaWidth, setAreaWidth] = useState(20);
  const [areaHeight, setAreaHeight] = useState(10);
  const [name, setName] = useState("");
  const [width, setWidth] = useState(6);
  const [height, setHeight] = useState(7);
  const [depth, setDepth] = useState(1.5);
  const [x, setX] = useState(0);
  const [y, setY] = useState(0);
  const [rotation, setRotation] = useState(0);
  const [count, setCount] = useState(4);
  const [compartments, setCompartments] = useState([2, 2, 3, 3]);
  const [error, setError] = useState("");
  const levels = useMemo(
    () =>
      Array.from({ length: count }, (_, index) => ({
        compartments: compartments[index] || 1,
      })),
    [count, compartments],
  );
  const save = async () => {
    try {
      const selectedZone = newArea
        ? await createZone({
            name: areaName,
            width: areaWidth,
            height: areaHeight,
          })
        : undefined;
      await createStack({
        zone: selectedZone?.id || zone,
        display_name: name,
        width,
        height,
        depth,
        x,
        y,
        rotation,
        levels,
      });
      onCreated(selectedZone?.id || zone);
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <section className="wizard">
      <div className="wizardSteps">
        {["Location", "Dimensions", "Levels", "Preview"].map((label, index) => (
          <span className={step === index + 1 ? "active" : ""} key={label}>
            {index + 1}. {label}
          </span>
        ))}
      </div>
      {error && <p className="formError">{error}</p>}
      {step === 1 && (
        <div className="formCard">
          <h2>Where does this stack stand?</h2>
          <label>
            Shop area
            <select
              value={newArea ? "new" : zone}
              onChange={(e) => {
                setNewArea(e.target.value === "new");
                if (e.target.value !== "new") setZone(+e.target.value);
              }}
            >
              {zones.map((z) => (
                <option value={z.id} key={z.id}>
                  {z.name}
                </option>
              ))}
              <option value="new">+ Define another area</option>
            </select>
          </label>
          {newArea && (
            <>
              <label>
                Area name
                <input
                  value={areaName}
                  onChange={(e) => setAreaName(e.target.value)}
                  placeholder="Front window, Centre aisle, Upstairs…"
                  required
                />
              </label>
              <div className="formGrid">
                <label>
                  Area width (ft)
                  <input
                    type="number"
                    min="1"
                    value={areaWidth}
                    onChange={(e) => setAreaWidth(+e.target.value)}
                  />
                </label>
                <label>
                  Area height (ft)
                  <input
                    type="number"
                    min="1"
                    value={areaHeight}
                    onChange={(e) => setAreaHeight(+e.target.value)}
                  />
                </label>
              </div>
              <p className="muted">
                Use any name and real dimensions that match this shop. Areas are
                never limited to walls or counters.
              </p>
            </>
          )}
          <label>
            Stack name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Phone Accessories Rack"
              required
            />
          </label>
        </div>
      )}
      {step === 2 && (
        <div className="formCard">
          <h2>Real physical dimensions (ft)</h2>
          <div className="formGrid">
            <label>
              Width
              <input
                type="number"
                min="1"
                value={width}
                onChange={(e) => setWidth(+e.target.value)}
              />
            </label>
            <label>
              Height
              <input
                type="number"
                min="1"
                value={height}
                onChange={(e) => setHeight(+e.target.value)}
              />
            </label>
            <label>
              Depth
              <input
                type="number"
                min="1"
                value={depth}
                onChange={(e) => setDepth(+e.target.value)}
              />
            </label>
            <label>
              X position
              <input
                type="number"
                min="0"
                value={x}
                onChange={(e) => setX(+e.target.value)}
              />
            </label>
            <label>
              Y position
              <input
                type="number"
                min="0"
                value={y}
                onChange={(e) => setY(+e.target.value)}
              />
            </label>
            <label>
              Orientation °
              <input
                type="number"
                value={rotation}
                onChange={(e) => setRotation(+e.target.value)}
              />
            </label>
          </div>
        </div>
      )}
      {step === 3 && (
        <div className="formCard">
          <h2>Levels and compartments</h2>
          <label>
            Number of levels
            <input
              type="number"
              min="1"
              max="20"
              value={count}
              onChange={(e) => setCount(+e.target.value)}
            />
          </label>
          {levels.map((level, index) => (
            <label key={index}>
              Level {index + 1} compartments
              <input
                type="number"
                min="1"
                value={level.compartments}
                onChange={(e) =>
                  setCompartments((old) => {
                    const next = [...old];
                    next[index] = +e.target.value;
                    return next;
                  })
                }
              />
            </label>
          ))}
        </div>
      )}
      {step === 4 && (
        <>
          <h2>Confirm the physical structure</h2>
          <StackPreview
            name={name}
            width={width}
            height={height}
            depth={depth}
            levels={levels}
          />
        </>
      )}
      <div className="wizardActions">
        <button
          type="button"
          className="secondary"
          onClick={step === 1 ? onCancel : () => setStep(step - 1)}
        >
          {step === 1 ? "Cancel" : "Back"}
        </button>
        {step < 4 ? (
          <button
            disabled={step === 1 && (!name || (newArea ? !areaName : !zone))}
            onClick={() => setStep(step + 1)}
          >
            Continue
          </button>
        ) : (
          <button onClick={() => void save()}>Create Shelf Stack</button>
        )}
      </div>
    </section>
  );
}
