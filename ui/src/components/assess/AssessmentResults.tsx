import * as React from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from "recharts";
import { createColumnHelper, createExpandedRowModel, createSortedRowModel, rowExpandingFeature, rowSortingFeature, sortFns, tableFeatures, useTable } from "@tanstack/react-table";
import { AlertOctagon, AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, CheckCircle2, ChevronDown, ChevronRight, Download, FileText, Layers, Rocket, ShieldAlert, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Pill, Stat } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/providers/AuthProvider";
import { useCssVar } from "@/providers/ThemeProvider";
import { useTargets } from "@/hooks/useTargets";
import { cn, downloadText } from "@/lib/utils";
import { formatDateTime, pluralize, titleCase } from "@/lib/format";
import type { AssessmentResource, AssessmentResult } from "@/types";
import { RISK_LEVELS, assessmentToCsv, assessmentToMarkdown, exportFilename, type RiskLevel } from "./assessExport";

const RISK_RANK: Record<RiskLevel, number> = { safe: 0, caution: 1, elevated: 2, critical: 3 };
const RISK_TONE: Record<RiskLevel, "success" | "warning" | "danger"> = { safe: "success", caution: "warning", elevated: "danger", critical: "danger" };
const RISK_ICON = { safe: CheckCircle2, caution: AlertTriangle, elevated: ShieldAlert, critical: AlertOctagon } as const;

const features = tableFeatures({
  rowSortingFeature,
  rowExpandingFeature,
  sortedRowModel: createSortedRowModel(),
  expandedRowModel: createExpandedRowModel(),
  sortFns,
});
const helper = createColumnHelper<typeof features, AssessmentResource>();

const columns = helper.columns([
  helper.display({
    id: "expand",
    header: () => <span className="sr-only">Details</span>,
    cell: ({ row }) => (
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          row.toggleExpanded();
        }}
        aria-expanded={row.getIsExpanded()}
        aria-label={row.getIsExpanded() ? "Hide details" : "Show details"}
        className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        data-testid="assess-expand"
      >
        {row.getIsExpanded() ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
      </button>
    ),
  }),
  helper.accessor("resource_name", {
    header: "Resource",
    cell: ({ row }) => (
      <div className="min-w-0">
        <div className="font-medium">{row.original.resource_name}</div>
        <div className="truncate font-mono text-[11px] text-muted-foreground">{row.original.resource_id}</div>
      </div>
    ),
  }),
  helper.accessor("resource_type", {
    header: "Type",
    cell: ({ getValue }) => <span className="text-xs text-muted-foreground">{getValue().replace(/_/g, " ")}</span>,
  }),
  helper.accessor((row) => RISK_RANK[row.risk_level] ?? 0, {
    id: "risk",
    header: "Risk",
    cell: ({ row }) => <StatusBadge status={row.original.risk_level} />,
  }),
  helper.accessor("risk_score", {
    header: "Score",
    cell: ({ getValue }) => <span className="tabular">{getValue()}</span>,
  }),
  helper.accessor("safe_to_migrate", {
    header: "Safe",
    cell: ({ getValue }) =>
      getValue() ? (
        <span className="inline-flex items-center gap-1 text-xs text-success" data-testid="assess-safe">
          <CheckCircle2 className="size-4" aria-hidden /> yes
        </span>
      ) : (
        <span className="inline-flex items-center gap-1 text-xs text-destructive" data-testid="assess-safe">
          <XCircle className="size-4" aria-hidden /> no
        </span>
      ),
  }),
  helper.accessor("reasons", {
    header: "Reasons",
    enableSorting: false,
    cell: ({ getValue }) => {
      const reasons = getValue();
      return reasons.length === 0 ? (
        <span className="text-xs text-muted-foreground">No findings</span>
      ) : (
        <ul className="list-disc space-y-0.5 pl-4 text-[13px]" data-testid="assess-reasons">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      );
    },
  }),
]);

/** Count how often each reason occurs across the inventory; the most common findings first. */
export function topFindings(resources: AssessmentResource[], limit = 5): { reason: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const resource of resources) for (const reason of resource.reasons) counts.set(reason, (counts.get(reason) ?? 0) + 1);
  return [...counts.entries()]
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count || a.reason.localeCompare(b.reason))
    .slice(0, limit);
}

export function AssessmentResults({ result, cloud }: { result: AssessmentResult; cloud: string }) {
  const { can } = useAuth();
  const { labelOf } = useTargets();
  const [filter, setFilter] = React.useState<RiskLevel | "all">("all");
  const success = useCssVar("--success");
  const warning = useCssVar("--warning");
  const destructive = useCssVar("--destructive");
  const border = useCssVar("--border");
  const muted = useCssVar("--muted-foreground");

  const rows = React.useMemo(() => (filter === "all" ? result.resources : result.resources.filter((item) => item.risk_level === filter)), [result, filter]);

  const table = useTable({
    features,
    columns,
    data: rows,
    getRowId: (row) => `${row.resource_type}:${row.resource_id}`,
    getRowCanExpand: () => true,
    initialState: { sorting: [{ id: "risk", desc: true }] },
  });

  const colours: Record<RiskLevel, { fill: string; opacity: number }> = {
    safe: { fill: success, opacity: 1 },
    caution: { fill: warning, opacity: 1 },
    elevated: { fill: destructive, opacity: 0.55 },
    critical: { fill: destructive, opacity: 1 },
  };
  const chart = RISK_LEVELS.map((level) => ({ level, label: titleCase(level), count: result.summary[level] ?? 0 }));
  const findings = topFindings(result.resources);
  const unsafe = result.resources.filter((item) => !item.safe_to_migrate).length;

  return (
    <div className="space-y-4" data-testid="assessment">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Readiness for {labelOf(cloud)}</h2>
          <p className="text-sm text-muted-foreground">
            {result.source_vcenter || "unknown source"} · {pluralize(result.summary.total_resources, "resource")} · generated {formatDateTime(result.generated_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => downloadText(exportFilename(result, "csv"), assessmentToCsv(result), "text/csv")} data-testid="export-csv">
            <Download /> CSV
          </Button>
          <Button variant="outline" size="sm" onClick={() => downloadText(exportFilename(result, "md"), assessmentToMarkdown(result), "text/markdown")} data-testid="export-md">
            <FileText /> Markdown
          </Button>
          {can("operator") ? (
            <Button size="sm" asChild>
              <Link to={`/runs/new?cloud=${encodeURIComponent(cloud)}`} data-testid="start-migration">
                <Rocket /> Start a migration run
              </Link>
            </Button>
          ) : null}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Stat label="Resources" value={result.summary.total_resources} hint={unsafe > 0 ? `${unsafe} not safe to migrate` : "all safe to migrate"} icon={Layers} testId="assess-stat-total" />
        {RISK_LEVELS.map((level) => (
          <Stat key={level} label={titleCase(level)} value={result.summary[level] ?? 0} tone={(result.summary[level] ?? 0) > 0 ? RISK_TONE[level] : "default"} icon={RISK_ICON[level]} testId={`assess-stat-${level}`} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Card>
          <CardHeader>
            <CardTitle>By risk level</CardTitle>
            <CardDescription>Resources per level; the table below lists each one.</CardDescription>
          </CardHeader>
          <CardContent className="h-44 pt-0">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart} layout="vertical" margin={{ top: 4, right: 32, left: 0, bottom: 0 }} barCategoryGap={6}>
                <CartesianGrid stroke={border} horizontal={false} strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: muted }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="label" width={64} tick={{ fontSize: 12, fill: muted }} axisLine={false} tickLine={false} />
                <ChartTooltip
                  cursor={{ fill: "var(--accent)", fillOpacity: 0.5 }}
                  contentStyle={{ background: "var(--popover)", border: `1px solid ${border}`, borderRadius: 8, fontSize: 12, color: "var(--foreground)" }}
                  labelStyle={{ color: "var(--muted-foreground)" }}
                  formatter={(value) => [value, "resources"]}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={22} isAnimationActive={false}>
                  {chart.map((entry) => (
                    <Cell key={entry.level} fill={colours[entry.level].fill} fillOpacity={colours[entry.level].opacity} />
                  ))}
                  <LabelList dataKey="count" position="right" style={{ fill: muted, fontSize: 11 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Top findings</CardTitle>
            <CardDescription>The reasons that appear most often across the inventory.</CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            {findings.length === 0 ? (
              <div className="py-4 text-sm text-muted-foreground">No findings: everything scored as safe.</div>
            ) : (
              <ul className="divide-y divide-border" data-testid="assess-findings">
                {findings.map((item) => (
                  <li key={item.reason} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <span className="min-w-0 truncate">{item.reason}</span>
                    <Pill>{pluralize(item.count, "resource")}</Pill>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>Resources</CardTitle>
            <CardDescription>Click a row for recommendations and missing data.</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by risk level">
            <FilterChip active={filter === "all"} onClick={() => setFilter("all")} testId="assess-filter-all">
              All <span className="tabular opacity-70">{result.summary.total_resources}</span>
            </FilterChip>
            {RISK_LEVELS.map((level) => (
              <FilterChip key={level} active={filter === level} onClick={() => setFilter(level)} testId={`assess-filter-${level}`}>
                {titleCase(level)} <span className="tabular opacity-70">{result.summary[level] ?? 0}</span>
              </FilterChip>
            ))}
          </div>
        </CardHeader>
        <CardContent className="px-0 pt-0">
          <Table data-testid="assessment-table">
            <TableHeader>
              {table.getHeaderGroups().map((group) => (
                <TableRow key={group.id}>
                  {group.headers.map((header, index) => {
                    const sorted = header.column.getIsSorted();
                    const sortable = header.column.getCanSort();
                    return (
                      <TableHead key={header.id} className={cn(index === 0 && "w-10 pl-4", index === group.headers.length - 1 && "pr-5")}>
                        {header.isPlaceholder ? null : sortable ? (
                          <button type="button" onClick={header.column.getToggleSortingHandler()} className="inline-flex items-center gap-1 uppercase hover:text-foreground" data-testid={`assess-sort-${header.column.id}`}>
                            <table.FlexRender header={header} />
                            {sorted === "asc" ? <ArrowUp className="size-3" /> : sorted === "desc" ? <ArrowDown className="size-3" /> : <ArrowUpDown className="size-3 opacity-50" />}
                          </button>
                        ) : (
                          <table.FlexRender header={header} />
                        )}
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={columns.length} className="py-8 text-center text-sm text-muted-foreground">
                    No resources at this level.
                  </TableCell>
                </TableRow>
              ) : (
                table.getRowModel().rows.map((row) => (
                  <React.Fragment key={row.id}>
                    <TableRow clickable onClick={() => row.toggleExpanded()} data-testid="assessment-row" data-risk={row.original.risk_level} data-state={row.getIsExpanded() ? "open" : "closed"}>
                      {row.getAllCells().map((cell, index) => (
                        <TableCell key={cell.id} className={cn("align-top", index === 0 && "pl-4", index === row.getAllCells().length - 1 && "pr-5")}>
                          <table.FlexRender cell={cell} />
                        </TableCell>
                      ))}
                    </TableRow>
                    {row.getIsExpanded() ? (
                      <TableRow className="bg-muted/30 hover:bg-muted/30" data-testid="assessment-details">
                        <TableCell colSpan={columns.length} className="px-5 py-4">
                          <div className="grid gap-4 sm:grid-cols-2">
                            <div>
                              <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Recommendations</div>
                              {row.original.recommendations.length === 0 ? (
                                <div className="text-sm text-muted-foreground">None.</div>
                              ) : (
                                <ul className="list-disc space-y-1 pl-4 text-sm">
                                  {row.original.recommendations.map((item) => (
                                    <li key={item}>{item}</li>
                                  ))}
                                </ul>
                              )}
                            </div>
                            <div>
                              <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Missing data</div>
                              {row.original.missing_data.length === 0 ? (
                                <div className="text-sm text-muted-foreground">Nothing missing from the discovery.</div>
                              ) : (
                                <div className="flex flex-wrap gap-1.5">
                                  {row.original.missing_data.map((item) => (
                                    <Badge key={item} variant="outline" className="font-mono text-[11px]">
                                      {item}
                                    </Badge>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </React.Fragment>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function FilterChip({ active, onClick, children, testId }: { active: boolean; onClick: () => void; children: React.ReactNode; testId: string }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active} className="focus-visible:outline-none" data-testid={testId}>
      <Badge variant={active ? "default" : "outline"} className="cursor-pointer gap-1.5">
        {children}
      </Badge>
    </button>
  );
}
