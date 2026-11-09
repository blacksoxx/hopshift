/* Shared harness for component tests: providers, router, jsdom gaps and an auth stub. */
import * as React from "react";
import { configure, render, type RenderOptions } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/providers/ThemeProvider";
import type { AuthStatus, AuthUser, Role } from "@/types";

// Radix dialogs and menus driven by userEvent are slow when nine files run in parallel; give
// assertions and tests more headroom than the 1 s / 5 s defaults.
configure({ asyncUtilTimeout: 4000 });
vi.setConfig({ testTimeout: 20_000 });

// ── jsdom gaps used by Radix (pointer capture, scrollIntoView) and recharts (ResizeObserver) ──
if (typeof window !== "undefined") {
  if (!("ResizeObserver" in window)) {
    class ResizeObserverStub {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    (window as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver = ResizeObserverStub;
  }
  const proto = Element.prototype as Element & { hasPointerCapture?: unknown; setPointerCapture?: unknown; releasePointerCapture?: unknown; scrollIntoView?: unknown };
  if (!proto.hasPointerCapture) proto.hasPointerCapture = () => false;
  if (!proto.setPointerCapture) proto.setPointerCapture = () => {};
  if (!proto.releasePointerCapture) proto.releasePointerCapture = () => {};
  if (!proto.scrollIntoView) proto.scrollIntoView = () => {};
  if (typeof Blob !== "undefined" && !Blob.prototype.text) {
    Blob.prototype.text = function text(this: Blob) {
      return new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result ?? ""));
        reader.onerror = () => reject(reader.error);
        reader.readAsText(this);
      });
    };
  }
}

// ── auth stub: tests set the user, components read it through the mocked useAuth ──
const ROLE_ORDER: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

export const ADMIN: AuthUser = { id: "u-admin", username: "ada", name: "Ada Lovelace", role: "admin", auth_kind: "local", mfa_enabled: false, last_login_at: "2026-11-09T09:00:00Z" };

export const authState: { user: AuthUser | null; status: AuthStatus; refresh: ReturnType<typeof vi.fn> } = {
  user: ADMIN,
  status: { setup_required: false, auth_mode: "required", oidc_enabled: false, mfa_policy: "optional", user: ADMIN },
  refresh: vi.fn(async () => {}),
};

export function setAuthUser(patch: Partial<AuthUser> | null): void {
  authState.user = patch === null ? null : { ...ADMIN, ...patch };
  authState.status = { ...authState.status, user: authState.user };
}

export function resetAuth(): void {
  setAuthUser({});
  authState.status = { setup_required: false, auth_mode: "required", oidc_enabled: false, mfa_policy: "optional", user: authState.user };
  authState.refresh = vi.fn(async () => {});
}

function hasRole(user: AuthUser | null | undefined, minimum: Role): boolean {
  return !!user && ROLE_ORDER[user.role] >= ROLE_ORDER[minimum];
}

/** Drop-in replacement for `@/providers/AuthProvider`: `vi.mock("@/providers/AuthProvider", async () => (await import("@/test-utils")).authModule)`. */
export const authModule = {
  hasRole,
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({
    loading: false,
    status: authState.status,
    user: authState.user,
    error: null,
    refresh: authState.refresh,
    login: vi.fn(),
    logout: vi.fn(),
    can: (minimum: Role) => hasRole(authState.user, minimum),
  }),
};

export function renderWithProviders(ui: React.ReactElement, { route = "/", ...options }: RenderOptions & { route?: string } = {}) {
  return render(
    <ThemeProvider>
      <TooltipProvider delayDuration={0}>
        <ToastProvider>
          <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
        </ToastProvider>
      </TooltipProvider>
    </ThemeProvider>,
    options,
  );
}
