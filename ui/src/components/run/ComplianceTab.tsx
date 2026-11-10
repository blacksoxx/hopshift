import * as React from "react";
import { ChevronDown, ChevronRight, Download, Search, ShieldCheck } from "lucide-react";
import { ApiError, api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { TargetBadge } from "@/components/TargetBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { SimpleSelect } from "@/components/ui/select";
import { Alert, EmptyState, Skeleton, Stat } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime } from "@/lib/format";
import { cn, downloadText } from "@/lib/utils";
import type { ComplianceControl, ComplianceReport } from "@/types";

const FRAMEWORK_LABEL: Record<string, string> = { cis: "CIS", soc2: "SOC 2", hipaa: "HIPAA" };
const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "fail", label: "Failed" },
  { value: "pass", label: "Passed" },
  { value: "advisory", label: "Advisory" },
  { value: "not_applicable", label: "Not applicable" },
];
const STATUS_RANK: Record<ComplianceControl["status"], number> = { fail: 0, advisory: 1, pass: 2, not_applicable: 3 };

export function filterControls(controls: ComplianceControl[], status: string, query: string): ComplianceControl[] {
  const needle = query.trim().toLowerCase();
  return controls
    .filter((control) => status === "all" || control.status === status)
    .filter((control) => !needle || `${control.id} ${control.title} ${control.description ?? ""} ${control.resources.join(" ")}`.toLowerCase().includes(needle))
    .sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || a.id.localeCompare(b.id));
}

function frameworkLabel(key: string): string {
  return FRAMEWORK_LABEL[key.toLowerCase()] ?? key.toUpperCase();
}

export function ComplianceTab({ runId }: { runId: string }) {
  const report = useAsync<ComplianceReport | null>(
    () =>
      api.compliance(runId).catch((exc: unknown) => {
        if (exc instanceof ApiError && exc.status === 404) return null;
        throw exc;
      }),
    [runId],
  );
  const [status, setStatus] = React.useState("all");
  const [query, setQuery] = React.useState("");
  const [open, setOpen] = React.useState<Set<string>>(new Set());

  const data = report.data;
  const controls = React.useMemo(() => filterControls(data?.controls ?? [], status, query), [data, status, query]);

  if (report.loading && data === null && !report.error) {
    return (
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[88px]" />
          ))}
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (report.error) {
    return <Alert variant="error" title="Could not load the compliance report" action={<Button size="sm" variant="outline" onClick={() => void report.reload()}>Retry</Button>}>{report.error}</Alert>;
  }
  if (!data) {
    return <EmptyState icon={ShieldCheck} title="No compliance report yet" description="Controls are evaluated against the generated Terraform when the pipeline reaches the validator." testId="compliance-empty" />;
  }

  function toggle(id: string) {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const frameworks = Object.entries(data.frameworks ?? {});

  return (
    <div className="space-y-4" data-testid="compliance-report">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Passed" value={data.summary.passed} tone="success" hint={`of ${data.summary.controls} controls`} testId="compliance-passed" />
        <Stat label="Failed" value={data.summary.failed} tone={data.summary.failed > 0 ? "danger" : "default"} hint={data.summary.failed > 0 ? "enforced controls not met" : "no enforced control failed"} testId="compliance-failed" />
        <Stat label="Advisory" value={data.summary.advisory} tone={data.summary.advisory > 0 ? "warning" : "default"} hint="recommended, not enforced" testId="compliance-advisory" />
        <Stat label="Not applicable" value={data.summary.not_applicable} hint="nothing to evaluate" testId="compliance-na" />
      </div>

      <div className="surface overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            Evaluated {formatDateTime(data.generated_at)} for <TargetBadge name={data.cloud} icon={false} className="text-foreground" />
          </div>
          {frameworks.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5" data-testid="compliance-frameworks">
              {frameworks.map(([key, counts]) => (
                <Badge key={key} variant="outline" className="gap-1.5">
                  <span className="font-semibold">{frameworkLabel(key)}</span>
                  {Object.entries(counts).map(([name, count]) => (
                    <span key={name} className={cn("font-normal", name === "fail" || name === "failed" ? "text-destructive" : name === "pass" || name === "passed" ? "text-success" : "text-muted-foreground")}>
                      {count} {name.replace(/_/g, " ")}
                    </span>
                  ))}
                </Badge>
              ))}
            </div>
          ) : null}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <div className="relative w-56">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search controls…" className="h-8 pl-8 text-xs" data-testid="compliance-search" />
            </div>
            <SimpleSelect value={status} onValueChange={setStatus} options={STATUS_OPTIONS} className="h-8 w-40 text-xs" testId="compliance-status-filter" />
            <Button variant="outline" size="sm" onClick={() => downloadText(`${runId}-compliance.json`, JSON.stringify(data, null, 2), "application/json")} data-testid="compliance-download">
              <Download /> JSON
            </Button>
          </div>
        </div>
        {controls.length === 0 ? (
          <div className="px-4 py-10 text-center text-sm text-muted-foreground">No controls match.</div>
        ) : (
          <Table data-testid="compliance-table">
            <TableHeader>
              <TableRow>
                <TableHead className="w-8 pl-4" />
                <TableHead>Status</TableHead>
                <TableHead>Control</TableHead>
                <TableHead className="hidden md:table-cell">Level</TableHead>
                <TableHead className="hidden lg:table-cell">Frameworks</TableHead>
                <TableHead className="pr-4 text-right">Resources</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {controls.map((control) => {
                const expanded = open.has(control.id);
                const refs = Object.entries(control.frameworks ?? {}).filter(([, ids]) => ids && ids.length > 0);
                return (
                  <React.Fragment key={control.id}>
                    <TableRow clickable onClick={() => toggle(control.id)} data-testid="compliance-row" data-status={control.status} data-expanded={expanded ? "true" : "false"}>
                      <TableCell className="pl-4 text-muted-foreground">{expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</TableCell>
                      <TableCell>
                        <StatusBadge status={control.status} />
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{control.title}</div>
                        <div className="font-mono text-[11px] text-muted-foreground">{control.id}</div>
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        <Badge variant={control.level === "enforce" ? "default" : "outline"}>{control.level}</Badge>
                      </TableCell>
                      <TableCell className="hidden lg:table-cell">
                        <div className="flex flex-wrap gap-1">
                          {refs.map(([framework, ids]) => (
                            <Badge key={framework} variant="secondary" className="text-[10.5px]" title={ids?.join(", ")}>
                              {frameworkLabel(framework)} · {ids?.length}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="pr-4 text-right tabular">{control.resources.length}</TableCell>
                    </TableRow>
                    {expanded ? (
                      <TableRow className="bg-muted/30 hover:bg-muted/30" data-testid="compliance-detail">
                        <TableCell colSpan={6} className="px-6 py-4">
                          <div className="grid gap-4 text-sm lg:grid-cols-3">
                            <div className="space-y-2">
                              {control.description ? <p className="text-muted-foreground">{control.description}</p> : null}
                              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Messages</div>
                              {control.messages.length === 0 ? (
                                <p className="text-xs text-muted-foreground">No messages.</p>
                              ) : (
                                <ul className="list-disc space-y-1 pl-4 text-[13px]">
                                  {control.messages.map((message, index) => (
                                    <li key={index}>{message}</li>
                                  ))}
                                </ul>
                              )}
                            </div>
                            <div className="space-y-2">
                              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Affected resources</div>
                              {control.resources.length === 0 ? (
                                <p className="text-xs text-muted-foreground">None.</p>
                              ) : (
                                <ul className="space-y-1 font-mono text-xs">
                                  {control.resources.map((resource) => (
                                    <li key={resource} className="truncate" title={resource}>
                                      {resource}
                                    </li>
                                  ))}
                                </ul>
                              )}
                              {refs.length > 0 ? (
                                <div className="pt-2">
                                  <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">References</div>
                                  <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                                    {refs.map(([framework, ids]) => (
                                      <li key={framework}>
                                        <span className="font-medium text-foreground">{frameworkLabel(framework)}</span>: {ids?.join(", ")}
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              ) : null}
                            </div>
                            <div className="space-y-2">
                              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Remediation</div>
                              <p className="whitespace-pre-wrap text-[13px]">{control.remediation || <span className="text-muted-foreground">No remediation provided.</span>}</p>
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </React.Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
