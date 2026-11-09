import { Badge } from "@/components/ui/badge";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const VARIANTS: Record<string, "success" | "warning" | "danger" | "info" | "muted" | "secondary" | "default"> = {
  succeeded: "success",
  ok: "success",
  pass: "success",
  migratable: "success",
  ready: "success",
  safe: "success",
  paused: "warning",
  needs_review: "warning",
  warn: "warning",
  caution: "warning",
  advisory: "warning",
  queued: "warning",
  failed: "danger",
  error: "danger",
  blocked: "danger",
  fail: "danger",
  critical: "danger",
  elevated: "danger",
  running: "info",
  created: "muted",
  cancelled: "muted",
  unverified: "muted",
  not_applicable: "muted",
};

export function StatusBadge({ status, className, pulse }: { status: string; className?: string; pulse?: boolean }) {
  const variant = VARIANTS[status] ?? "secondary";
  const live = status === "running" || pulse;
  return (
    <Badge variant={variant} className={cn("capitalize", className)} data-testid="status-badge" dot={!live}>
      {live ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
      {status.replace(/_/g, " ")}
    </Badge>
  );
}
