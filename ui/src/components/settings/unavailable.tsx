import { ShieldOff } from "lucide-react";
import { ApiError } from "@/api";
import { EmptyState } from "@/components/ui/misc";

/**
 * True when the security module is not reachable on this server: the endpoints are missing
 * (404) or authentication runs in `disabled` mode (the API answers 400 with that message).
 */
export function isUnavailable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (error.status === 404 || error.status === 501) return true;
  return error.status === 400 && /authentication is disabled/i.test(error.message);
}

export function errorMessage(error: unknown): string {
  return (error as Error | undefined)?.message || "Request failed";
}

/** Result wrapper for loaders that may land on a server without the security module. */
export type Loaded<T> = { kind: "ok"; data: T } | { kind: "unavailable" };

export async function loadOrUnavailable<T>(loader: () => Promise<T>): Promise<Loaded<T>> {
  try {
    return { kind: "ok", data: await loader() };
  } catch (error) {
    if (isUnavailable(error)) return { kind: "unavailable" };
    throw error;
  }
}

export function FeatureUnavailable({ what, testId }: { what: string; testId?: string }) {
  return (
    <EmptyState
      icon={ShieldOff}
      title={`${what} are not available on this server`}
      description="The security module is not active here: authentication runs in disabled mode or the endpoints are missing. Set security.auth.mode to required in config.yaml to manage accounts, tokens and the audit log."
      testId={testId}
    />
  );
}
