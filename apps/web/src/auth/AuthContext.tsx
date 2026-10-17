// Who is logged in, shared with every page.

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { api, getToken, login as apiLogin, logout as apiLogout } from "../api/client";
import type { Role, User } from "../api/types";

interface AuthState {
  user: User | null;
  checking: boolean; // true while a saved token is being checked
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(() => getToken() !== null);

  // A token saved earlier in this tab: ask the API who it belongs to.
  useEffect(() => {
    if (!getToken()) return;
    api
      .me()
      .then(({ data }) => setUser(data))
      .catch(() => setUser(null)) // expired or revoked: the login page will show
      .finally(() => setChecking(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setUser(await apiLogin(email, password));
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // The token is already forgotten here; if the API could not be told
      // (e.g. it is down), the user is still logged out in this browser.
    } finally {
      setUser(null);
    }
  }, []);

  return <AuthContext value={{ user, checking, login, logout }}>{children}</AuthContext>;
}

export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth must be used inside <AuthProvider>");
  return state;
}

/** Shows its children only to a logged-in user; others go to the login page. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, checking } = useAuth();
  const location = useLocation();
  if (checking) return <p role="status">Checking your session…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}

const RANK: Record<Role, number> = { analyst: 0, manager: 1, admin: 2 };

/** Same rule as the API: each role can do everything the roles below it can. */
export function atLeast(role: Role, minimum: Role): boolean {
  return RANK[role] >= RANK[minimum];
}

/** Shows its children only to users with at least `role`; others see a short explanation. */
export function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { user } = useAuth();
  if (!user || !atLeast(user.role, role)) {
    return <p role="alert">This page is for {role === "admin" ? "administrators" : `${role}s and above`}.</p>;
  }
  return children;
}
