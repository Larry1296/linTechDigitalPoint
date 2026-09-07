import { createContext, useContext, useEffect, useState } from "react";
import { api, resetCsrfToken } from "../api/client";
const AuthContext = createContext(null);
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const refresh = async () => {
    try {
      const data = await api("/api/v1/auth/me/");
      setUser(data.authenticated ? data : null);
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
    <AuthContext.Provider value={{ user, loading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider missing");
  return value;
}
