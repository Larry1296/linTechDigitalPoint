import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Identity } from "../../types";
type AuthValue = {
  user: Identity | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};
const AuthContext = createContext<AuthValue | null>(null);
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Identity | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = async () => {
    try {
      const data = await api<Identity>("/api/v1/auth/me/");
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
