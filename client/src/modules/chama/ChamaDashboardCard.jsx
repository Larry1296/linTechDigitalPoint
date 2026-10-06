import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { ChamaSummaryCard } from "./ChamaPages";
import "./chama.css";

// On the owner's dashboard: each chama at a glance, or the offer to set one up. Its money is never part of the shop's figures.
export function ChamaDashboardCard() {
  const { user } = useAuth();
  const allowed = Boolean(user?.permissions?.includes("chama.view_chama"));
  const [state, setState] = useState(null);
  const [chamas, setChamas] = useState([]);
  const load = async () => {
    if (!allowed) return;
    try {
      const next = await api("/api/v1/chama/setup/");
      setState(next);
      setChamas(next.enabled && next.chamas ? (await api("/api/v1/chama/")).chamas : []);
    } catch {
      setState(null);  // the rest of the dashboard still works; the Chama page shows the problem
    }
  };
  useEffect(() => { void load(); }, [allowed]);
  useLiveRefresh(load);
  if (!allowed || !state) return null;
  if (chamas.length) return <section className="chamaDashboard" aria-labelledby="chama-dashboard-title">
    <h2 id="chama-dashboard-title">Chama</h2>
    <p className="muted">The chama's money belongs to its members. It is not included in any of the shop's figures above or below.</p>
    <ul className="chamaCards">{chamas.map((chama) => <li key={chama.id}><ChamaSummaryCard chama={chama} /></li>)}</ul>
  </section>;
  if (!state.can_turn_on && !state.enabled) return null;
  return <section className="chamaDashboard chamaOffer" aria-labelledby="chama-offer-title">
    <div>
      <span className="proTag">Pro</span>
      <h2 id="chama-offer-title">Are you the treasurer of a chama?</h2>
      <p>Keep your chama's records here: members with their ID and phone numbers, who has paid and who has not, fines for paying late, excuses, and whose turn it is to receive the money. It stays separate from the shop's money.</p>
    </div>
    {state.plan_allows ? <Link className="button" to="/admin/chama/setup">Set up a chama</Link> : <Link className="button" to="/admin/subscription">Upgrade to Pro to use it</Link>}
  </section>;
}
