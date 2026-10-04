import { LogOut } from "lucide-react";
import { useState } from "react";
import { useAuth } from "../../core/auth/AuthContext";
import { displayRole } from "../../core/auth/displayRole";
import { useSignOut } from "../../core/auth/useSignOut";

export function SidebarAccount({ children }) {
  const { user } = useAuth();
  const signOut = useSignOut();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!user) return null;

  async function handleSignOut() {
    setBusy(true);
    setError("");
    try {
      await signOut();
    } catch {
      setError("Could not sign out. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sidebarAccount" aria-label="Signed-in account">
      <div className="sidebarAccountRow">
      <div className="sidebarIdentity">
        <strong>{user.username}</strong>
        <span>{displayRole(user)}</span>
      </div>
      <button className="logoutButton" type="button" disabled={busy} onClick={handleSignOut}>
        <LogOut size={18} aria-hidden="true" />
        {busy ? "Signing out…" : "Logout"}
      </button>
      </div>
      {children}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
