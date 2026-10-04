import { useEffect, useMemo, useState } from "react";
import { createStack } from "./api";
import { api } from "../../core/api/client";
import { StackPreview } from "./StackPreview";
import { FormError } from "../../components/forms/FormNotice";
// Adds a rack to an existing area. Areas themselves are created only from Shop areas.
export function StackBuilder({ zones, initialZone, onCreated, onCancel }) {
  const [step, setStep] = useState(1);
  const [zone, setZone] = useState(initialZone || zones[0]?.id || 0);
  const [name, setName] = useState("");
  // Boxes hold exactly what was typed (an empty box stays empty); numbers are read only when checking and saving.
  const [width, setWidth] = useState("6");
  const [height, setHeight] = useState("7");
  const [depth, setDepth] = useState("1.5");
  const [x, setX] = useState("0");
  const [y, setY] = useState("0");
  const [rotation, setRotation] = useState("0");
  const [count, setCount] = useState("4");
  const [compartments, setCompartments] = useState(["2", "2", "3", "3"]);
  const [error, setError] = useState("");
  const [categories, setCategories] = useState([]);
  const [categoryIds, setCategoryIds] = useState([]);
  useEffect(() => { void api("/api/v1/catalog/categories/").then(setCategories).catch((err) => setError(err.message)); }, []);
  const levelCount = /^\d+$/.test(count.trim()) ? Math.min(Number(count), 20) : 0;
  const levels = useMemo(
    () =>
      Array.from({ length: levelCount }, (_, index) => ({
        compartments: Number(compartments[index] ?? 1),
      })),
    [levelCount, compartments],
  );
  const number = (value) => (String(value).trim() === "" ? NaN : Number(value));
  const problem = () => {
    if (step === 2) {
      for (const [label, value] of [["Width", width], ["Height", height], ["Depth", depth]])
        if (!(number(value) > 0)) return `Enter the ${label.toLowerCase()} in feet (more than 0).`;
      for (const [label, value] of [["X position", x], ["Y position", y]])
        if (!(number(value) >= 0)) return `Enter the ${label} (0 or more).`;
      if (!Number.isFinite(number(rotation))) return "Enter the orientation in degrees (0 if the rack faces straight).";
    }
    if (step === 3) {
      if (!/^\d+$/.test(count.trim()) || Number(count) < 1 || Number(count) > 20) return "Enter how many levels the rack has (1 to 20).";
      const missing = levels.findIndex((_, index) => !/^\d+$/.test(String(compartments[index] ?? "1").trim()) || Number(compartments[index] ?? 1) < 1);
      if (missing >= 0) return `Enter how many compartments level ${missing + 1} has (1 or more).`;
    }
    return "";
  };
  const next = () => {
    const reason = problem();
    if (reason) { setError(reason); return; }
    setError("");
    setStep(step + 1);
  };
  const save = async () => {
    try {
      await createStack({
        zone,
        display_name: name,
        width: Number(width),
        height: Number(height),
        depth: Number(depth),
        x: Number(x),
        y: Number(y),
        rotation: Number(rotation),
        levels,
        category_ids: categoryIds,
        primary_category_id: categoryIds[0],
      });
      onCreated(zone);
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <section className="wizard">
      <h1>Add a rack</h1>
      <div className="wizardSteps">
        {["Location", "Dimensions", "Levels", "Preview"].map((label, index) => (
          <span className={step === index + 1 ? "active" : ""} key={label}>
            {index + 1}. {label}
          </span>
        ))}
      </div>
      {step === 1 && (
        <div className="formCard">
          <h2>Where does this rack stand?</h2>
          <label>
            Shop area
            <select value={zone} onChange={(e) => setZone(+e.target.value)}>
              {zones.map((z) => (
                <option value={z.id} key={z.id}>
                  {z.name}
                </option>
              ))}
            </select>
          </label>
          <p className="muted">Area not listed? Click Cancel, then use “Add another area” under Shop areas. Once it is added, select its tab and click “Add rack to” that area.</p>
          <label>
            Rack name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Phone Accessories Rack"
              required
            />
          </label>
          <label>
            Primary merchandise category (optional)
            <select value={categoryIds[0] || ""} onChange={(event) => setCategoryIds(event.target.value ? [Number(event.target.value), ...categoryIds.slice(1)] : [])}>
              <option value="">Assign later in rack settings</option>
              {categories.filter((category) => category.active).map((category) => <option value={category.id} key={category.id}>{category.name}</option>)}
            </select>
          </label>
          <p className="muted">Configure the physical rack first. Assign merchandise categories now or later from the rack editor before receiving stock.</p>
          <label>
            Additional allowed categories
            <select multiple value={categoryIds.slice(1).map(String)} onChange={(event) => setCategoryIds([categoryIds[0], ...Array.from(event.target.selectedOptions, (option) => Number(option.value))])}>
              {categories.filter((category) => category.active && category.id !== categoryIds[0]).map((category) => <option value={category.id} key={category.id}>{category.name}</option>)}
            </select>
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
                onChange={(e) => setWidth(e.target.value)}
              />
            </label>
            <label>
              Height
              <input
                type="number"
                min="1"
                value={height}
                onChange={(e) => setHeight(e.target.value)}
              />
            </label>
            <label>
              Depth
              <input
                type="number"
                min="1"
                value={depth}
                onChange={(e) => setDepth(e.target.value)}
              />
            </label>
            <label>
              X position
              <input
                type="number"
                min="0"
                value={x}
                onChange={(e) => setX(e.target.value)}
              />
            </label>
            <label>
              Y position
              <input
                type="number"
                min="0"
                value={y}
                onChange={(e) => setY(e.target.value)}
              />
            </label>
            <label>
              Orientation °
              <input
                type="number"
                value={rotation}
                onChange={(e) => setRotation(e.target.value)}
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
              onChange={(e) => setCount(e.target.value)}
            />
          </label>
          {levels.map((level, index) => (
            <label key={index}>
              Level {index + 1} compartments
              <input
                type="number"
                min="1"
                value={compartments[index] ?? "1"}
                onChange={(e) =>
                  setCompartments((old) => {
                    const updated = [...old];
                    while (updated.length < index) updated.push("1");
                    updated[index] = e.target.value;
                    return updated;
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
            width={Number(width)}
            height={Number(height)}
            depth={Number(depth)}
            levels={levels}
          />
        </>
      )}
      <div className="wizardActions">
        <button
          type="button"
          className="secondary"
          onClick={step === 1 ? onCancel : () => { setError(""); setStep(step - 1); }}
        >
          {step === 1 ? "Cancel" : "Back"}
        </button>
        {step < 4 ? (
          <button
            disabled={step === 1 && (!name || !zone)}
            onClick={next}
          >
            Continue
          </button>
        ) : (
          <button onClick={() => void save()}>Create rack</button>
        )}
      </div>
      <FormError title={step < 4 ? "Before you continue" : "Could not create the rack."} message={error} />
    </section>
  );
}
