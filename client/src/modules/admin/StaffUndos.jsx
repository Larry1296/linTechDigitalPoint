import { useCallback, useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { useLiveRefresh } from "../../core/data/liveRefresh";

// For the owner: what the people working in the business undid or corrected in the last 30 days (a cancelled M-Pesa
// transaction, a sale taken back, a shift that closed with a different count...), each with who, when and why.
export function StaffUndos() {
  const [rows, setRows] = useState([]);
  const load = useCallback(() => api("/api/v1/inventory/dashboard/staff-undos/").then(setRows).catch(() => {}), []);
  useEffect(() => { void load(); }, [load]);
  useLiveRefresh(load, { pollMs: 60000 });
  if (!rows.length) return null;
  return <section className="staffUndos" aria-labelledby="staff-undos-title">
    <h2 id="staff-undos-title">Undone or corrected by your staff</h2>
    <p className="muted">The last 30 days, newest first, each with the reason they gave.</p>
    <div className="tableWrap"><table>
      <thead><tr><th>When</th><th>Who</th><th>What</th><th>Which</th><th>Reason they gave</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.id}>
        <td>{new Date(row.at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
        <td>{row.who}</td>
        <td>{row.what}</td>
        <td>{row.detail}</td>
        <td><b>{row.reason || "No reason given"}</b></td>
      </tr>)}</tbody>
    </table></div>
  </section>;
}
