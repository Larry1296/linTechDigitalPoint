import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { KyamaSummaryCard } from "./KyamaPages";
import "./kyama.css";

// On the owner's dashboard: each kyama at a glance, or the offer to set one up. Its money is never part of the shop's figures.
export function KyamaDashboardCard() {
  const { user } = useAuth();
  const allowed = Boolean(user?.permissions?.includes("kyama.view_kyama"));
  const [state, setState] = useState(null);
  const [kyamas, setKyamas] = useState([]);
  const load = async () => {
    if (!allowed) return;
    try {
      const next = await api("/api/v1/kyama/setup/");
      setState(next);
      setKyamas(next.enabled && next.kyamas ? (await api("/api/v1/kyama/")).kyamas : []);
    } catch {
      setState(null);  // the rest of the dashboard still works; the Kyama page shows the problem
    }
  };
  useEffect(() => { void load(); }, [allowed]);
  useLiveRefresh(load);
  if (!allowed || !state) return null;
  if (kyamas.length) return <section className="kyamaDashboard" aria-labelledby="kyama-dashboard-title">
    <h2 id="kyama-dashboard-title">Kyama</h2>
    <p className="muted">The kyama's money belongs to its members. It is not included in any of the shop's figures above or below.</p>
    <ul className="kyamaCards">{kyamas.map((kyama) => <li key={kyama.id}><KyamaSummaryCard kyama={kyama} /></li>)}</ul>
  </section>;
  if (!state.can_turn_on && !state.enabled) return null;
  return <section className="kyamaDashboard kyamaOffer" aria-labelledby="kyama-offer-title">
    <div>
      <span className="proTag">Pro</span>
      <h2 id="kyama-offer-title">Are you the treasurer of a kyama?</h2>
      <p>Keep your chama's records here: members with their ID and phone numbers, who has paid and who has not, fines for paying late, excuses, and whose turn it is to receive the money. It stays separate from the shop's money.</p>
    </div>
    {state.plan_allows ? <Link className="button" to="/admin/kyama/setup">Set up a kyama</Link> : <Link className="button" to="/admin/subscription">Upgrade to Pro to use it</Link>}
  </section>;
}
