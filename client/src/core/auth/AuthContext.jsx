import { createContext, useContext, useEffect, useState } from "react";
import { api, resetCsrfToken } from "../api/client";
import { useLocation, useNavigate } from "react-router-dom";
const AuthContext = createContext(null);
export function AuthProvider({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);
  useEffect(() => {
    const expired = () => {
      setSessionExpired(true);
      setUser(null);
      const next = location.pathname + location.search + location.hash;
      navigate(
        `/login?reason=session-expired&next=${encodeURIComponent(next)}`,
        { replace: true },
      );
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, [location, navigate]);
  const refresh = async () => {
    try {
      const data = await api("/api/v1/auth/me/");
      setUser(data.authenticated ? data : null);
      if (data.authenticated) setSessionExpired(false);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void refresh();
  }, []);
  const logout = async () => {
    await api("/api/v1/auth/logout/", { method: "POST" });
    resetCsrfToken();
    setUser(null);
  };
  return (
    <AuthContext.Provider
      value={{ user, loading, sessionExpired, refresh, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}
export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider missing");
  return value;
}
