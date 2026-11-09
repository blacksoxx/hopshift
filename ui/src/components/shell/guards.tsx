import * as React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import { LogoMark } from "@/components/Logo";
import { Alert, EmptyState, Spinner } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/providers/AuthProvider";
import type { Role } from "@/types";

export function Splash({ message }: { message?: string }) {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 bg-background">
      <LogoMark className="size-10" />
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner /> {message ?? "Loading…"}
      </div>
    </div>
  );
}

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { loading, status, user, error, refresh } = useAuth();
  const location = useLocation();
  if (loading) return <Splash />;
  if (error && !status) {
    return (
      <div className="flex h-screen items-center justify-center p-6">
        <div className="w-full max-w-md space-y-3">
          <Alert variant="error" title="The API is not reachable">
            {error}
          </Alert>
          <Button variant="outline" onClick={() => void refresh()}>
            Retry
          </Button>
        </div>
      </div>
    );
  }
  if (status?.setup_required) return <Navigate to="/setup" replace />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  if (user.mfa_enrollment_required && !location.pathname.startsWith("/settings/profile")) return <Navigate to="/settings/profile?enroll=1" replace />;
  return <>{children}</>;
}

export function RequireRole({ role, children }: { role: Role; children: React.ReactNode }) {
  const { can } = useAuth();
  if (!can(role)) {
    return <EmptyState icon={ShieldAlert} title="You do not have access to this page" description={`This area requires the ${role} role. Ask an administrator to change your role.`} testId="forbidden" />;
  }
  return <>{children}</>;
}

/** Public pages redirect away when the visitor is already signed in. */
export function PublicOnly({ children }: { children: React.ReactNode }) {
  const { loading, status, user } = useAuth();
  const location = useLocation();
  if (loading) return <Splash />;
  if (status?.setup_required && location.pathname !== "/setup") return <Navigate to="/setup" replace />;
  if (!status?.setup_required && location.pathname === "/setup") return <Navigate to="/" replace />;
  if (user) {
    const next = new URLSearchParams(location.search).get("next");
    return <Navigate to={next && next.startsWith("/") ? next : "/"} replace />;
  }
  return <>{children}</>;
}
