import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { http, onUnauthorized, setToken, getToken } from "@/api/client";
import type { CurrentUser } from "@/api/types";

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  can: (...codes: string[]) => boolean;
  hasRole: (...roles: string[]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await http.get<CurrentUser>("/auth/me"));
    } catch {
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    return onUnauthorized(() => {
      setToken(null);
      setUser(null);
    });
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await http.post<{ access_token: string }>("/auth/login", { username, password });
    setToken(res.access_token);
    const me = await http.get<CurrentUser>("/auth/me");
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(async () => {
    try {
      await http.post("/auth/logout");
    } catch {
      /* ignore */
    }
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login,
      logout,
      refresh,
      can: (...codes) => !!user && codes.some((c) => user.permissions.includes(c)),
      hasRole: (...roles) => !!user && roles.some((r) => user.roles.includes(r)),
    }),
    [user, loading, login, logout, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("AuthProvider missing");
  return ctx;
}
