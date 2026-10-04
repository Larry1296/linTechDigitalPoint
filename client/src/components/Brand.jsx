import { useId } from "react";
import { usePlatform } from "../modules/platform/PlatformContext";
import "./brand.css";
import { LogoImage } from "./LogoImage";

// The platform's own mark: rising ledger bars under a growth arc, on a blue-to-teal tile.
// It never shows any subscriber's branding, because every business on the platform is a tenant.
export function PlatformMark({ size = 36 }) {
  // Several marks can share a page, so each needs its own gradient ids.
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  return <svg className="platformMark" width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id={`${id}-tile`} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#3b82f6" />
        <stop offset="0.55" stopColor="#1d4ed8" />
        <stop offset="1" stopColor="#0e7490" />
      </linearGradient>
      <linearGradient id={`${id}-arc`} x1="0" y1="1" x2="1" y2="0">
        <stop offset="0" stopColor="#93c5fd" />
        <stop offset="1" stopColor="#4ade80" />
      </linearGradient>
    </defs>
    <rect width="48" height="48" rx="14" fill={`url(#${id}-tile)`} />
    <path d="M0 14C0 6.3 6.3 0 14 0h20c7.7 0 14 6.3 14 14v2C34 9 16 9 0 20z" fill="#fff" opacity="0.12" />
    <rect className="platformMarkBar" x="11" y="27" width="6" height="10" rx="3" fill="#fff" opacity="0.7" />
    <rect className="platformMarkBar" x="21" y="21" width="6" height="16" rx="3" fill="#fff" opacity="0.85" />
    <rect className="platformMarkBar" x="31" y="15" width="6" height="22" rx="3" fill="#fff" />
    <path d="M9 22C16 20 25 15 33 9" fill="none" stroke={`url(#${id}-arc)`} strokeWidth="2.5" strokeLinecap="round" />
    <circle cx="35.5" cy="7.5" r="3" fill="#4ade80" stroke="#fff" strokeWidth="1.5" />
  </svg>;
}

// Splits the platform name for its wordmark: the last word is set apart as an accent, and a
// joined-up name such as "DukaFlow" is split at its last capital so it stays one word.
export function wordmarkParts(name = "") {
  const words = name.trim().split(/\s+/);
  if (words.length > 1) return { lead: words.slice(0, -1).join(" "), accent: words.at(-1), joined: false };
  const match = words[0].match(/^(.*[a-z0-9])([A-Z][a-z0-9]*)$/);
  return match ? { lead: match[1], accent: match[2], joined: true } : { lead: words[0], accent: "", joined: false };
}

export function PlatformLogo({ compact = false }) {
  const platform = usePlatform();
  const { lead, accent, joined } = wordmarkParts(platform.name);
  return <span className={`platformLogo${compact ? " compact" : ""}`}>
    <PlatformMark size={compact ? 32 : 40} />
    <span className={`platformLogoName${joined ? " joined" : ""}`}><span className="platformLogoLead">{lead}</span>{accent && <>{joined ? "" : " "}<span className="platformLogoAccent">{accent}</span></>}</span>
  </span>;
}

export function businessInitials(name = "") {
  let words = name.split(/[^A-Za-z0-9]+/).filter(Boolean);
  // A joined-up name such as "LinTechDigitalPoint" is split at its capitals.
  if (words.length === 1) words = words[0].replace(/([a-z])([A-Z])/g, "$1 $2").split(" ");
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || "?").slice(0, 2)).toUpperCase();
}

// A subscriber's own identity inside its workspace: its logo if uploaded, otherwise its initials and name.
export function BusinessBrand({ organization, compact = false }) {
  if (!organization) return <PlatformLogo compact={compact} />;
  // The navigation bar is dark in both themes, so it shows the version made for dark backgrounds.
  const logo = organization.logo_dark_url || organization.logo_url;
  if (logo) return <LogoImage className={`businessLogo${compact ? " compact" : ""}`} slot={compact ? "header" : "footer"} src={logo} alt={organization.name} />;
  return <span className={`businessBrand${compact ? " compact" : ""}`}>
    <span className="businessInitials" aria-hidden="true">{businessInitials(organization.name)}</span>
    <span className="businessName">{organization.name}</span>
  </span>;
}
