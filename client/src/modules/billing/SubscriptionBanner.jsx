import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Clock, Crown } from "lucide-react";
import { useAuth } from "../../core/auth/AuthContext";
import "./billing.css";

const dateText = (value) => (value ? new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");
const daysText = (days) => (days === 1 ? "1 day" : `${days} days`);
const endText = (value) => new Date(value).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
const two = (value) => String(value).padStart(2, "0");

// The time left until the subscription ends, counting down every second, e.g. "23 days 04h 12m 09s".
export function countdownText(milliseconds) {
  const total = Math.max(0, Math.floor(milliseconds / 1000));
  const days = Math.floor(total / 86400);
  const clock = `${two(Math.floor((total % 86400) / 3600))}h ${two(Math.floor((total % 3600) / 60))}m ${two(total % 60)}s`;
  return days ? `${daysText(days)} ${clock}` : clock;
}

export function Countdown({ until, onEnd }) {
  const [now, setNow] = useState(() => Date.now());
  const end = new Date(until).getTime();
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const over = now >= end;
  useEffect(() => { if (over) onEnd?.(); }, [over, onEnd]);
  // role="timer" is not announced every second, so screen readers are not flooded.
  return <strong className="subscriptionCountdown" role="timer">{countdownText(end - now)}</strong>;
}

// The plan, its state and the days remaining, as shown on the Subscription page.
export function SubscriptionStatus({ subscription }) {
  if (!subscription) return null;
  if (subscription.complimentary) return <div className="subscriptionStatus good"><Crown size={20} aria-hidden="true" /><div><strong>{subscription.plan_name || "Pro"} · free platform plan</strong><span>Every feature, no expiry.</span></div></div>;
  const tone = subscription.ended ? "ended" : subscription.expiring_soon ? "warn" : "good";
  const label = subscription.ended ? "Ended" : subscription.status === "TRIAL" ? "Free month" : "Active";
  return <div className={`subscriptionStatus ${tone}`}>
    {subscription.ended ? <AlertTriangle size={20} aria-hidden="true" /> : <Clock size={20} aria-hidden="true" />}
    <div>
      <strong>{subscription.plan_name || "No plan"} · {label}</strong>
      <span>{subscription.ended ? `Ended ${dateText(subscription.ends_at)}. Most features are paused until you renew; your records are safe.`
        : `${daysText(subscription.days_left)} left · until ${dateText(subscription.ends_at)}`}</span>
    </div>
    {!subscription.ended && subscription.days_left != null && <span className="subscriptionCount" aria-label={`${daysText(subscription.days_left)} left`}>{subscription.days_left}<small>days</small></span>}
  </div>;
}

// A one-line reminder at the top of every workspace page with the time left ticking down: free month, renewal due,
// ended, or an invitation to Pro.
export function SubscriptionBanner({ organization, canManage }) {
  const { refresh } = useAuth() || {};
  const subscription = organization?.subscription;
  if (!subscription || subscription.complimentary || subscription.status === "UNCONFIGURED") return null;
  const action = canManage ? <Link to="/admin/subscription">{subscription.ended ? "Renew now" : subscription.plan === "BASIC" ? "Upgrade to Pro" : "Renew"}</Link> : null;
  if (subscription.ended) return <div className="subscriptionBanner ended" role="alert"><AlertTriangle size={18} aria-hidden="true" />
    <span>Your subscription has ended. Sales still work, but accounting, stock receiving and other tools are paused until you renew.{!canManage && " Ask the business owner to renew."}</span>{action}</div>;
  if (!subscription.ends_at) return null;
  const trial = subscription.status === "TRIAL";
  const lead = <>{trial ? `Free month on ${subscription.plan_name}:` : `${subscription.plan_name}:`} <Countdown until={subscription.ends_at} onEnd={refresh} /> left
    <small className="subscriptionEnds"> (ends {endText(subscription.ends_at)})</small>.</>;
  if (subscription.expiring_soon) return <div className="subscriptionBanner warn" role="status"><Clock size={18} aria-hidden="true" />
    <span>{lead} Renew before it ends to keep every tool working.</span>{action}</div>;
  if (subscription.plan === "BASIC") return <div className="subscriptionBanner info" role="status"><Crown size={18} aria-hidden="true" />
    <span>{lead} Upgrade to Pro to unlock reports, shelves, staff accounts and branches.</span>{action}</div>;
  return <div className="subscriptionBanner info" role="status"><Clock size={18} aria-hidden="true" /><span>{lead}</span>{action}</div>;
}
