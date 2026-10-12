import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";

// On the dashboard: a nudge when last month's Safaricom commission has not been recorded.
export function CommissionReminder() {
  const { user } = useAuth();
  const allowed = Boolean(user?.permissions?.includes("mpesa.view_mpesacommissionentry"));
  const [due, setDue] = useState(null);
  useEffect(() => {
    if (!allowed) return undefined;
    let live = true;
    api("/api/v1/mpesa/commission/due/").then((data) => { if (live) setDue(data.due_label || null); }).catch(() => {});
    return () => { live = false; };
  }, [allowed]);
  if (!due) return null;
  return (
    <section className="investReminder" role="status" aria-label="Commission due">
      <div>
        <b>{due}'s Safaricom commission is not recorded</b>
        <p>Record it when it is paid, so the M-Pesa agency's profit for {due} is right.</p>
      </div>
      <a className="button" href="/admin/mpesa/commission">Record commission</a>
    </section>
  );
}
