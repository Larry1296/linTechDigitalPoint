import { businessCurrency } from "../../core/organization/presentation";

// Kenyan notes counted one by one; coins are entered as a single amount.
export const NOTES = [1000, 500, 200, 100, 50];
export const emptyCount = () => ({ ...Object.fromEntries(NOTES.map((note) => [note, ""])), coins: "" });

export function countTotal(count) {
  const notes = NOTES.reduce((sum, note) => sum + note * (Number.parseInt(count[note], 10) || 0), 0);
  return Math.round((notes + (Number(count.coins) || 0)) * 100) / 100;
}

// What the server stores: whole note counts and the coins amount.
export const countPayload = (count) => ({
  ...Object.fromEntries(NOTES.map((note) => [note, Number.parseInt(count[note], 10) || 0])),
  coins: String(Number(count.coins) || 0),
});

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;

// Count the drawer: how many of each note, plus the coins total. The cash figure is the sum, never typed.
export function CashCounter({ count, onChange, legend = "Count the cash" }) {
  const set = (key, value) => onChange({ ...count, [key]: value });
  return (
    <fieldset className="cashCounter">
      <legend>{legend}</legend>
      {NOTES.map((note) => (
        <label key={note} className="cashCounterRow">
          <span>{note.toLocaleString()} notes</span>
          <input type="number" inputMode="numeric" min="0" step="1" placeholder="0" aria-label={`Number of ${note} notes`}
            value={count[note]} onChange={(event) => set(note, event.target.value)} />
          <output aria-label={`${note} notes total`}>{money(note * (Number.parseInt(count[note], 10) || 0))}</output>
        </label>
      ))}
      <label className="cashCounterRow">
        <span>Coins (total)</span>
        <input type="number" inputMode="decimal" min="0" step="0.01" placeholder="0" aria-label="Coins total"
          value={count.coins} onChange={(event) => set("coins", event.target.value)} />
        <output aria-label="Coins amount">{money(count.coins)}</output>
      </label>
      <p className="cashCounterTotal">Physical cash <strong aria-label="Physical cash total">{money(countTotal(count))}</strong></p>
    </fieldset>
  );
}
