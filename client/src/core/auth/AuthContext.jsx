import { setBusinessPresentation } from "../organization/presentation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, ApiError, resetCsrfToken, setActiveOrganization, setActiveBranch, setWorkspaceLocked, clearAccessToken, refreshAccess, accessNeedsRefresh } from "../api/client";
import { useLocation, useNavigate } from "react-router-dom";
import { SessionLockOverlay } from "./SessionLockOverlay";
import { forgetPasswordLength, rememberPasswordLength } from "./passwordLength";

const AuthContext = createContext(null);
const SESSION_EVENT_KEY = "workspace-session-event";
function broadcast(action) {
  try { localStorage.setItem(SESSION_EVENT_KEY, JSON.stringify({ action, at: Date.now(), nonce: Math.random() })); } catch { /* Storage may be disabled. */ }
}

export function AuthProvider({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [authState, setAuthState] = useState("signed_out");
  const locked = ["locking", "locked", "unlocking"].includes(authState);
  const [pinLength, setPinLength] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lockError, setLockError] = useState("");
  const userRef = useRef(null);
  const access = useRef({ deadline: null, locked: false, serverTime: 0 });
  const lockGeneration = useRef(0);
  const lastRefreshAttempt = useRef(0);

  const lock = useCallback(() => {
    if (access.current.locked) return;
    lockGeneration.current += 1;
    access.current.locked = true;
    setWorkspaceLocked(true);
    setAuthState("locking");
    setSessionExpired(true);
    broadcast('lock');
    void api('/api/v1/auth/lock/', { method:'POST' }).then(data => setPinLength(data?.session?.pin_length ?? null)).catch(() => {})
      .finally(() => { if (access.current.locked) setAuthState('locked'); });
  }, []);
  const updateAccess = useCallback((state, allowUnlock = false) => {
    if (!state) return;
    if (access.current.locked && !state.locked && !allowUnlock) return;
    if (state.server_time < access.current.serverTime) return;
    access.current.serverTime = state.server_time;
    access.current.deadline = Date.now() + (state.expires_at - state.server_time) * 1000;
    if (state.locked || access.current.deadline <= Date.now()) { setPinLength(state.pin_length ?? null); lock(); return; }
    access.current.locked = false;
    setAuthState("authenticated");
    setSessionExpired(false);
    setLockError("");
    setWorkspaceLocked(false);
  }, [lock]);
  const applyIdentity = useCallback((data, allowUnlock = false) => {
    if (!data.authenticated) return;
    const previous = userRef.current;
    if (data.session?.locked) {
      const identity = previous?.id === data.id ? previous : data;
      userRef.current = identity;
      setUser(identity);
      updateAccess(data.session);
      return;
    }
    if (previous?.id && (previous.id !== data.id || (previous.organization && previous.organization.id !== data.organization?.id))) {
      lock();
      window.location.assign("/admin/dashboard");
      return;
    }
    userRef.current = data;
    setUser(data);
    setBusinessPresentation(data.organization);
    setActiveOrganization(data.organization?.id);
    setActiveBranch(data.branch?.id);
    updateAccess(data.session, allowUnlock);
    // Older responses/tests without session metadata can still sign in.
    if (!data.session) {
      access.current.locked = false;
      setAuthState("authenticated");
      setSessionExpired(false);
      setWorkspaceLocked(false);
    }
  }, [updateAccess, lock]);
  const clearIdentity = useCallback(() => {
    clearAccessToken();
    forgetPasswordLength();
    setActiveBranch(null);
    window.dispatchEvent(new Event("session-signed-out"));
    access.current = { deadline: null, locked: false, serverTime: 0 };
    userRef.current = null;
    setUser(null);
    setAuthState("signed_out");
    setPinLength(null);
    setLockError("");
    resetCsrfToken();
    setBusinessPresentation(null);
    setActiveOrganization(null);
    setWorkspaceLocked(false);
  }, []);
  const refresh = useCallback(async (allowUnlock = false) => {
    const generation = lockGeneration.current;
    try {
      let data = await api("/api/v1/auth/me/");
      if (data.authenticated && data.session && !data.session.locked) data = await api("/api/v1/auth/refresh/", { method: "POST" });
      if (generation !== lockGeneration.current) return;
      if (data.authenticated) applyIdentity(data, allowUnlock);
      else if (userRef.current) lock();
      else clearIdentity();
    } finally { setLoading(false); }
  }, [applyIdentity, clearIdentity, lock]);
  useEffect(() => { void refresh(); }, [refresh]);
  // A password login or registration is a new, verified session: any idle-lock state
  // left in this tab by an earlier session must not hide it behind the lock screen.
  const signedIn = useCallback(async () => {
    lockGeneration.current += 1;
    access.current = { deadline: null, locked: false, serverTime: 0 };
    userRef.current = null;
    setWorkspaceLocked(false);
    await refresh(true);
  }, [refresh]);

  // Business set-up is signed-in work too: a lock covers it without losing the steps done.
  const inWorkspace = location.pathname.startsWith("/admin") || location.pathname === "/onboarding";
  useEffect(() => {
    const expired = () => {
      // In the workspace an ended session locks the screen: the page stays as it is and the password signs in again.
      if (userRef.current && inWorkspace) { lock(); return; }
      clearIdentity();
      setSessionExpired(true);
      setAuthState("expired");
      const next = location.pathname + location.search + location.hash;
      navigate(`/login?reason=session-expired&next=${encodeURIComponent(next)}`, { replace: true });
    };
    const sessionLocked = event => { updateAccess(event.detail); lock(); };
    window.addEventListener("session-expired", expired);
    window.addEventListener("session-locked", sessionLocked);
    return () => {
      window.removeEventListener("session-expired", expired);
      window.removeEventListener("session-locked", sessionLocked);
    };
  }, [location, navigate, lock, updateAccess, clearIdentity, inWorkspace]);

  useEffect(() => {
    if (!user?.id || !inWorkspace) return;
    // The workspace never locks for being idle: whether the page is in view or not, its access token is renewed
    // before it runs out, so the session stays open for its 12 hours and a customer's question is answered at once.
    // It locks only when the person locks it, or when those 12 hours end (then the password starts it afresh).
    const tick = () => {
      if (access.current.locked || access.current.deadline == null) return;
      if (access.current.deadline <= Date.now()) lock();
      else if (accessNeedsRefresh() && Date.now() - lastRefreshAttempt.current >= 15000) {
        lastRefreshAttempt.current = Date.now();
        void refreshAccess().catch(() => {});
      }
    };
    const sync = async (allowUnlock = false) => {
      tick();
      try {
        const data = await api("/api/v1/auth/session/");
        if (!data.authenticated) { lock(); return; }
        if (data.id !== userRef.current?.id) { window.location.assign("/login"); return; }
        if (data.session?.locked) updateAccess(data.session);
        else if (access.current.locked && allowUnlock) { setWorkspaceLocked(false); await refresh(true); }
        else updateAccess(data.session);
      } catch { /* Local deadline still locks offline or sleeping tabs. */ }
    };
    const visibility = () => { if (!document.hidden) void sync(); };
    const storage = event => {
      if (event.key !== SESSION_EVENT_KEY) return;
      try {
        if (JSON.parse(event.newValue)?.action === "logout") { clearIdentity(); navigate("/login", { replace: true }); }
        else if (JSON.parse(event.newValue)?.action === "lock") lock();
        else void sync(JSON.parse(event.newValue)?.action === "unlocked");
      } catch { /* Ignore unrelated storage data. */ }
    };
    const timer = window.setInterval(tick, 1000);
    window.addEventListener("focus", visibility);
    window.addEventListener("online", visibility);
    window.addEventListener("storage", storage);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", visibility);
      window.removeEventListener("online", visibility);
      window.removeEventListener("storage", storage);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [user?.id, inWorkspace, lock, updateAccess, refresh, clearIdentity, navigate]);

  // A lock the person made opens with their PIN. A wrong one says how many tries are left; after the last, the server
  // stops offering the PIN (pin_length becomes null) and the lock screen asks for the password.
  const unlockWithPin = async (pin) => {
    if (busy) return false;
    setBusy(true); setAuthState("unlocking"); setLockError("");
    try {
      const data = await api("/api/v1/auth/unlock/", { method: "POST", body: JSON.stringify({ pin }) });
      resetCsrfToken();
      applyIdentity(data, true);
      broadcast("unlocked");
      return true;
    } catch (error) {
      if (error.status === 401) { clearIdentity(); setAuthState('expired'); navigate('/login?reason=session-expired', { replace:true }); }
      else {
        setAuthState('locked');
        if (error.data?.session) setPinLength(error.data.session.pin_length ?? null);
        setLockError(error.message);
      }
      return false;
    } finally { setBusy(false); }
  };
  // quiet: an automatic try (see SessionLockOverlay); a wrong password then shows no error and returns false.
  const unlock = async (password, { quiet = false } = {}) => {
    if (busy) return false;
    setBusy(true); setAuthState("unlocking"); if (!quiet) setLockError("");
    try {
      const previous = userRef.current;
      let data;
      try {
        data = await api("/api/v1/auth/unlock/", { method: "POST", body: JSON.stringify({ password, credential: previous?.username }) });
      } catch (error) {
        // The session itself ended (its time ran out while the computer slept, or it was signed out elsewhere):
        // the same password signs in again here, so the page and anything typed on it stay.
        if (error.status !== 401 || !previous?.username) throw error;
        try {
          data = await api("/api/v1/auth/login/", { method: "POST", body: JSON.stringify({ credential: previous.username, password }) });
        } catch (failed) {
          if (failed.status === 400) throw new ApiError(400, "Incorrect password. Please try again.");
          throw failed;
        }
      }
      resetCsrfToken();
      if (previous?.id && (previous.id !== data.id || (previous.organization && previous.organization.id !== data.organization?.id))) {
        window.location.assign("/admin/dashboard");
        return;
      }
      rememberPasswordLength(password);
      applyIdentity(data, true);
      broadcast("unlocked");
      return true;
    } catch (error) {
      if (error.status === 401) { clearIdentity(); setAuthState('expired'); navigate('/login?reason=session-expired', { replace:true }); }
      else { setAuthState('locked'); if (!quiet || error.status !== 400) setLockError(error.message); }
      return false;
    }
    finally { setBusy(false); }
  };
  const logout = async () => {
    await api("/api/v1/auth/logout/", { method: "POST" });
    clearIdentity();
    broadcast("logout");
    navigate("/", { replace: true });
  };
  // The lock only ever applies to the authenticated workspace (/admin and business set-up): a valid
  // device session picked up while browsing the public site must never hide or
  // overlay-lock public pages like the homepage, /login, or /register.
  const lockedHere = locked && inWorkspace;
  const overlay = Boolean(user) && lockedHere;
  return <AuthContext.Provider value={{ user, loading, sessionExpired, locked, authState, lock, refresh, signedIn, logout }}>
    <div className="sessionWorkspace" style={lockedHere ? { visibility: "hidden" } : undefined} inert={overlay ? true : undefined} aria-hidden={overlay ? true : undefined}>{children}</div>
    {overlay && <SessionLockOverlay username={user.username} pinLength={pinLength} busy={busy} error={lockError}
      onUnlock={unlock} onPin={unlockWithPin} onLogout={() => logout().catch(error => setLockError(error.message))} />}
  </AuthContext.Provider>;
}
export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider missing");
  return value;
}
