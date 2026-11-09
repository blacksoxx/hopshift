import * as React from "react";
import { ApiError, api, onUnauthorized } from "@/api";
import type { AuthStatus, AuthUser, Role } from "@/types";

const ROLE_ORDER: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

export function hasRole(user: AuthUser | null | undefined, minimum: Role): boolean {
  if (!user) return false;
  return (ROLE_ORDER[user.role] ?? -1) >= ROLE_ORDER[minimum];
}

interface AuthContextValue {
  loading: boolean;
  status: AuthStatus | null;
  user: AuthUser | null;
  error: string | null;
  refresh: () => Promise<void>;
  login: (username: string, password: string, totp?: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  can: (minimum: Role) => boolean;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

const DISABLED_USER: AuthUser = { id: "anonymous", username: "anonymous", name: "Local user", role: "admin", auth_kind: "disabled", mfa_enabled: false };

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = React.useState(true);
  const [status, setStatus] = React.useState<AuthStatus | null>(null);
  const [user, setUser] = React.useState<AuthUser | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    try {
      let next: AuthStatus;
      try {
        next = await api.authStatus();
      } catch (exc) {
        // Servers without the security module answer 404 here; /meta still says whether auth is on.
        if (!(exc instanceof ApiError) || exc.status !== 404) throw exc;
        const meta = await api.meta();
        if (meta.auth_mode !== "disabled") throw exc;
        next = { setup_required: false, auth_mode: "disabled", oidc_enabled: false, mfa_policy: "optional", user: null };
      }
      setStatus(next);
      if (next.auth_mode === "disabled") setUser(DISABLED_USER);
      else setUser(next.user ?? null);
      setError(null);
    } catch (exc) {
      setError((exc as Error).message || "The API is not reachable.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  React.useEffect(
    () =>
      onUnauthorized(() => {
        setUser((current) => (current && current.auth_kind !== "disabled" ? null : current));
      }),
    [],
  );

  const login = React.useCallback(
    async (username: string, password: string, totp?: string) => {
      const next = await api.login(username, password, totp);
      setUser(next);
      setStatus((current) => (current ? { ...current, user: next, setup_required: false } : current));
      return next;
    },
    [],
  );

  const logout = React.useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      setStatus((current) => (current ? { ...current, user: null } : current));
    }
  }, []);

  const can = React.useCallback((minimum: Role) => hasRole(user, minimum), [user]);

  return <AuthContext.Provider value={{ loading, status, user, error, refresh, login, logout, can }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = React.useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
