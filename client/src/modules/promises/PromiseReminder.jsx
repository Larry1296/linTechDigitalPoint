import { useCallback, useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { dueIn, telLink, when } from "./promiseTime";

const SHOWN = 4;

// On the dashboard, in red: promises to customers whose time is within a day or already gone, and not yet marked met
// or not met. Checked every minute, so one turns up by itself as its time comes.
export function PromiseReminder() {
  const { user } = useAuth();
  const allowed = Boolean(user?.permissions?.includes("core.view_customerpromise"));
  const [due, setDue] = useState([]);
  const load = useCallback(async () => {
    if (!allowed) return;
    try { setDue((await api("/api/v1/promises/due/")).due || []); } catch { /* the reminder waits for the next check */ }
  }, [allowed]);
  useEffect(() => { void load(); }, [load]);
  useLiveRefresh(load, { pollMs: 60000 });
  if (!allowed || !due.length) return null;
  const late = due.filter((p) => p.state === "late").length;
  const title = late
    ? `${late} customer ${late === 1 ? "promise is" : "promises are"} late${due.length > late ? `, ${due.length - late} due soon` : ""}`
    : `${due.length} customer ${due.length === 1 ? "promise is" : "promises are"} due soon`;
  return (
    <section className="promiseReminder" role="alert" aria-label="Customer promises due">
      <div className="promiseReminderHead">
        <b>{title}</b>
        <a className="button" href="/admin/promises">Open promises</a>
      </div>
      <ul>
        {due.slice(0, SHOWN).map((p) => <li key={p.id} className={p.state}>
          <span><strong>{p.wanted}</strong> · {p.customer_name ? `${p.customer_name}, ` : ""}<a href={telLink(p.phone)}>{p.phone}</a></span>
          <small>You promised: {p.promised} · by {when(p.due_at)} · <b>{dueIn(p.due_at)}</b></small>
        </li>)}
      </ul>
      {due.length > SHOWN && <p>And {due.length - SHOWN} more on the promises page.</p>}
    </section>
  );
}
