import * as React from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Download, ScrollText, ShieldCheck, X } from "lucide-react";
import { api } from "@/api";
import { useAsync, useDebounced } from "@/hooks/useAsync";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, CodeBlock, EmptyState, Skeleton } from "@/components/ui/misc";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/providers/AuthProvider";
import { cn } from "@/lib/utils";
import { formatDateTime, relativeTime } from "@/lib/format";
import type { AuditEntry } from "@/types";
import { FeatureUnavailable, loadOrUnavailable } from "./unavailable";

export const PAGE_SIZE = 50;
export type Outcome = "any" | "success" | "failure" | "denied";

export interface AuditFilters {
  action: string;
  actor: string;
  outcome: Outcome;
  since: string;
}

export const EMPTY_FILTERS: AuditFilters = { action: "", actor: "", outcome: "any", since: "" };

/** Query parameters for `api.audit`: empty filters are omitted, `since` is the date as typed (ISO prefix). */
export function buildAuditQuery(filters: AuditFilters, page: number): Parameters<typeof api.audit>[0] {
  return {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    action: filters.action.trim() || undefined,
    actor: filters.actor.trim() || undefined,
    outcome: filters.outcome === "any" ? undefined : filters.outcome,
    since: filters.since || undefined,
  };
}

const OUTCOME_VARIANT: Record<string, "success" | "danger" | "warning" | "muted"> = { success: "success", failure: "danger", denied: "warning" };

function shortHash(hash: string): string {
  return hash.length > 14 ? `${hash.slice(0, 8)}…${hash.slice(-4)}` : hash;
}

export function AuditLog() {
  const { can } = useAuth();
  const [filters, setFilters] = React.useState<AuditFilters>(EMPTY_FILTERS);
  const [page, setPage] = React.useState(0);
  const [expanded, setExpanded] = React.useState<Set<number>>(new Set());
  const [verify, setVerify] = React.useState<{ ok: boolean; entries: number; broken_at: number | null; message: string } | null>(null);
  const [verifying, setVerifying] = React.useState(false);
  const [verifyError, setVerifyError] = React.useState<string | null>(null);
  const debouncedFilters = useDebounced(filters, 250);
  const admin = can("admin");

  const query = React.useMemo(() => buildAuditQuery(debouncedFilters, page), [debouncedFilters, page]);
  const audit = useAsync(() => loadOrUnavailable(() => api.audit(query)), [query], { enabled: admin });

  function updateFilters(patch: Partial<AuditFilters>) {
    setFilters((current) => ({ ...current, ...patch }));
    setPage(0);
  }

  async function runVerify() {
    setVerifying(true);
    setVerifyError(null);
    try {
      setVerify(await api.auditVerify());
    } catch (exc) {
      setVerifyError((exc as Error).message || "Verification failed.");
    } finally {
      setVerifying(false);
    }
  }

  if (!admin) {
    return <EmptyState icon={ScrollText} title="Administrators review the audit log" description="Your role does not include access to the audit trail. Ask an administrator if you need an export." testId="audit-forbidden" />;
  }

  const loaded = audit.data;
  if (loaded?.kind === "unavailable") return <FeatureUnavailable what="Audit records" testId="audit-unavailable" />;

  const entries = loaded?.kind === "ok" ? loaded.data.entries : [];
  const total = loaded?.kind === "ok" ? loaded.data.total : 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtersActive = filters.action || filters.actor || filters.outcome !== "any" || filters.since;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Input value={filters.action} onChange={(event) => updateFilters({ action: event.target.value })} placeholder="Action, e.g. run.approved" className="w-full font-mono text-[13px] sm:w-56" data-testid="audit-filter-action" aria-label="Filter by action" />
        <Input value={filters.actor} onChange={(event) => updateFilters({ actor: event.target.value })} placeholder="Actor" className="w-full sm:w-40" data-testid="audit-filter-actor" aria-label="Filter by actor" />
        <SimpleSelect
          value={filters.outcome}
          onValueChange={(value) => updateFilters({ outcome: value as Outcome })}
          className="w-36"
          options={[
            { value: "any", label: "Any outcome" },
            { value: "success", label: "Success" },
            { value: "failure", label: "Failure" },
            { value: "denied", label: "Denied" },
          ]}
          testId="audit-filter-outcome"
        />
        <Input type="date" value={filters.since} onChange={(event) => updateFilters({ since: event.target.value })} className="w-40" data-testid="audit-filter-since" aria-label="Since date" />
        {filtersActive ? (
          <Button variant="ghost" size="sm" onClick={() => updateFilters(EMPTY_FILTERS)}>
            <X /> Clear
          </Button>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void runVerify()} loading={verifying} data-testid="audit-verify">
            <ShieldCheck /> Verify chain
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={api.auditExportUrl()} download="audit-log.ndjson" data-testid="audit-export">
              <Download /> Export ndjson
            </a>
          </Button>
        </div>
      </div>

      {verifyError ? (
        <Alert variant="error" title="Could not verify the chain">
          {verifyError}
        </Alert>
      ) : verify ? (
        <Alert variant={verify.ok ? "success" : "error"} title={verify.ok ? "Audit chain intact" : "Audit chain broken"} testId="audit-verify-result" action={<Button variant="ghost" size="icon-sm" onClick={() => setVerify(null)} aria-label="Dismiss"><X /></Button>}>
          {verify.entries} {verify.entries === 1 ? "entry" : "entries"} checked. {verify.message}
          {verify.broken_at !== null ? ` First altered or missing entry: #${verify.broken_at}.` : ""}
        </Alert>
      ) : null}

      <div className="surface overflow-hidden">
        {audit.loading && !loaded ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-9" />
            ))}
          </div>
        ) : audit.error ? (
          <EmptyState title="Could not load the audit log" description={audit.error} action={<Button variant="outline" onClick={() => void audit.reload()}>Retry</Button>} />
        ) : entries.length === 0 ? (
          <EmptyState icon={ScrollText} title={filtersActive ? "No entries match these filters" : "No audit entries yet"} description={filtersActive ? "Try a broader action or a wider date range." : "Every sign-in, run action and settings change is recorded here."} testId="audit-empty" />
        ) : (
          <Table data-testid="audit-table">
            <TableHeader>
              <TableRow>
                <TableHead className="w-8 pl-3" />
                <TableHead>Time</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Action</TableHead>
                <TableHead className="hidden md:table-cell">Target</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead className="hidden pr-4 lg:table-cell">IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry) => (
                <AuditRow key={entry.id} entry={entry} open={expanded.has(entry.id)} onToggle={() => setExpanded((current) => { const next = new Set(current); if (next.has(entry.id)) next.delete(entry.id); else next.add(entry.id); return next; })} />
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {total > 0 ? (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span data-testid="audit-range">
            Showing {page * PAGE_SIZE + 1}–{Math.min(total, (page + 1) * PAGE_SIZE)} of {total}
          </span>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="sm" onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={page === 0} data-testid="audit-prev">
              <ChevronLeft /> Previous
            </Button>
            <span className="px-2 tabular">
              {page + 1} / {pages}
            </span>
            <Button variant="outline" size="sm" onClick={() => setPage((current) => Math.min(pages - 1, current + 1))} disabled={page >= pages - 1} data-testid="audit-next">
              Next <ChevronRight />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function AuditRow({ entry, open, onToggle }: { entry: AuditEntry; open: boolean; onToggle: () => void }) {
  const hasDetails = entry.details && Object.keys(entry.details).length > 0;
  return (
    <>
      <TableRow clickable onClick={onToggle} data-testid="audit-row" data-state={open ? "open" : "closed"} aria-expanded={open}>
        <TableCell className="pl-3 text-muted-foreground">
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
        </TableCell>
        <TableCell className="whitespace-nowrap text-xs text-muted-foreground" title={entry.ts}>
          <div className="text-foreground">{formatDateTime(entry.ts)}</div>
          <div>{relativeTime(entry.ts)}</div>
        </TableCell>
        <TableCell>
          <div className="text-sm">{entry.actor}</div>
          <div className="text-xs text-muted-foreground">{entry.actor_kind}</div>
        </TableCell>
        <TableCell className="font-mono text-[12.5px]">{entry.action}</TableCell>
        <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
          {entry.target_type ? (
            <>
              <span>{entry.target_type}</span>
              {entry.target_id ? <span className="block max-w-[200px] truncate font-mono" title={entry.target_id}>{entry.target_id}</span> : null}
            </>
          ) : (
            "–"
          )}
        </TableCell>
        <TableCell>
          <Badge variant={OUTCOME_VARIANT[entry.outcome] ?? "muted"} dot>
            {entry.outcome}
          </Badge>
        </TableCell>
        <TableCell className="hidden pr-4 font-mono text-xs text-muted-foreground lg:table-cell">{entry.ip ?? "–"}</TableCell>
      </TableRow>
      {open ? (
        <TableRow className="bg-muted/30 hover:bg-muted/30" data-testid="audit-details">
          <TableCell colSpan={7} className="px-5 py-4">
            <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
              <div className="min-w-0">
                <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Details</div>
                {hasDetails ? <CodeBlock className="max-h-64">{JSON.stringify(entry.details, null, 2)}</CodeBlock> : <div className="text-sm text-muted-foreground">No additional details.</div>}
                {entry.user_agent ? <div className="mt-2 truncate text-xs text-muted-foreground" title={entry.user_agent}>User agent: {entry.user_agent}</div> : null}
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 self-start text-xs lg:min-w-[260px]">
                <dt className="text-muted-foreground">entry</dt>
                <dd className="font-mono tabular">#{entry.id}</dd>
                <dt className="text-muted-foreground">hash</dt>
                <dd className="font-mono" title={entry.hash}>
                  {shortHash(entry.hash)}
                </dd>
                <dt className="text-muted-foreground">prev</dt>
                <dd className="font-mono" title={entry.prev_hash}>
                  {shortHash(entry.prev_hash)}
                </dd>
              </dl>
            </div>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}
