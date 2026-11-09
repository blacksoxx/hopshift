import * as React from "react";
import { Alert } from "@/components/ui/misc";
import { formatDateTime, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ConnectionTest } from "@/types";

function renderValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => (typeof item === "object" && item !== null ? JSON.stringify(item) : String(item))).join(", ");
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return String(value);
}

/** The identity a test returned, as a definition list. */
export function IdentityList({ identity, className }: { identity: Record<string, unknown>; className?: string }) {
  const entries = Object.entries(identity).filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (entries.length === 0) return <p className={cn("text-sm text-muted-foreground", className)}>The provider returned no identity details.</p>;
  return (
    <dl className={cn("grid grid-cols-[minmax(110px,max-content)_1fr] gap-x-4 gap-y-1.5 text-sm", className)} data-testid="identity-list">
      {entries.map(([key, value]) => (
        <React.Fragment key={key}>
          <dt className="text-muted-foreground">{titleCase(key)}</dt>
          <dd className="min-w-0 break-all font-mono text-[12.5px] text-foreground">{renderValue(value)}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

/** Outcome of a verification: the identity on success, the masked failure message otherwise. */
export function TestResult({ result, className, testId = "test-result" }: { result: ConnectionTest; className?: string; testId?: string }) {
  if (result.ok) {
    return (
      <Alert variant="success" title="Verified" className={className} testId={testId}>
        <div>
          Checked {formatDateTime(result.checked_at)}
          {result.message ? ` · ${result.message}` : ""}
        </div>
        <IdentityList identity={result.identity} className="mt-2" />
      </Alert>
    );
  }
  return (
    <Alert variant="error" title="Verification failed" className={className} testId={testId}>
      <p className="break-words">{result.message || "The provider rejected the credentials."}</p>
      <div className="mt-1">Checked {formatDateTime(result.checked_at)}. Secret values are masked in this message.</div>
    </Alert>
  );
}
