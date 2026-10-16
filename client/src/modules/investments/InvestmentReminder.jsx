import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";

// On the dashboard: a nudge when an investment's monthly rate (and statement balance) has not been recorded this month.
export function InvestmentReminder() {
  const { user } = useAuth();
  const allowed = Boolean(user?.permissions?.includes("accounting.view_investment") && user?.organization?.enabled_modules?.includes("investments"));
  const [reminder, setReminder] = useState(null);
  useEffect(() => {
    if (!allowed) return undefined;
    let live = true;
    api("/api/v1/accounting/investments/reminder/").then((data) => { if (live) setReminder(data); }).catch(() => {});
    return () => { live = false; };
  }, [allowed]);
  if (!reminder?.due?.length) return null;
  const names = reminder.due.map((i) => i.name).join(" and ");
  return (
    <section className="investReminder" role="status" aria-label="Investment check due">
      <div>
        <b>Monthly investment check due for {reminder.month}</b>
        <p>Record the rate {names} {reminder.due.length > 1 ? "pay" : "pays"} now, and the balance on the statement, so interest is recorded.</p>
      </div>
      <a className="button" href="/admin/investments">Go to investments</a>
    </section>
  );
}
