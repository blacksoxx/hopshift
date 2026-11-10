import { Link, useNavigate } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from "recharts";
import { ArrowRight, BarChart3, Cable, CheckCircle2, Clock, ListChecks, PauseCircle, Plus, ShieldCheck } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { useTargets } from "@/hooks/useTargets";
import { TargetBadge } from "@/components/TargetBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader, Skeleton, Stat } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/providers/AuthProvider";
import { useCssVar } from "@/providers/ThemeProvider";
import { relativeTime, shortId } from "@/lib/format";
import type { PostureCheck } from "@/types";

export function DashboardPage() {
  const navigate = useNavigate();
  const { can, user } = useAuth();
  const dashboard = useAsync(() => api.dashboard(), [], { pollMs: (data) => (data && (data.by_status.running ?? 0) > 0 ? 4000 : 20000) });
  const posture = useAsync(() => api.posture(), []);
  const connections = useAsync(() => api.listConnections().catch(() => []), []);
  const { labelOf } = useTargets();
  const primary = useCssVar("--primary");
  const destructive = useCssVar("--destructive");
  const border = useCssVar("--border");
  const muted = useCssVar("--muted-foreground");

  const data = dashboard.data;
  const paused = data?.by_status.paused ?? 0;
  const running = data?.by_status.running ?? 0;
  const checks = posture.data?.checks ?? [];
  const failing = checks.filter((check) => check.status === "fail").length;
  const warning = checks.filter((check) => check.status === "warn").length;

  return (
    <div>
      <PageHeader
        title={`Welcome${user?.name ? `, ${user.name.split(" ")[0]}` : ""}`}
        description="Migrations at a glance: what is running, what needs your approval and how the platform is doing."
        actions={
          <>
            <Button variant="outline" asChild>
              <Link to="/assess">
                <BarChart3 /> Assess an inventory
              </Link>
            </Button>
            {can("operator") ? (
              <Button asChild>
                <Link to="/runs/new" data-testid="dashboard-new-run">
                  <Plus /> New run
                </Link>
              </Button>
            ) : null}
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {dashboard.loading && !data ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[88px]" />)
        ) : (
          <>
            <Stat label="Runs" value={data?.total ?? 0} hint={`${data?.by_status.succeeded ?? 0} succeeded`} icon={ListChecks} testId="stat-runs" />
            <Stat label="Awaiting approval" value={paused} hint={paused > 0 ? "paused for review" : "nothing waiting"} icon={PauseCircle} tone={paused > 0 ? "warning" : "default"} testId="stat-paused" />
            <Stat label="Success rate" value={data?.success_rate == null ? "–" : `${data.success_rate}%`} hint={running > 0 ? `${running} running now` : "of finished runs"} icon={CheckCircle2} tone={data?.success_rate != null && data.success_rate < 70 ? "warning" : "success"} />
            <Stat
              label="Security posture"
              value={posture.loading ? "…" : failing > 0 ? `${failing} failing` : warning > 0 ? `${warning} warnings` : "Healthy"}
              hint={<Link to="/settings/posture" className="hover:underline">review controls</Link>}
              icon={ShieldCheck}
              tone={failing > 0 ? "danger" : warning > 0 ? "warning" : "success"}
            />
          </>
        )}
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader className="flex-row items-start justify-between">
            <div>
              <CardTitle>Activity</CardTitle>
              <CardDescription>Runs created per day, last 30 days.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="h-56 pt-0">
            {data && data.total > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.series} margin={{ top: 8, right: 4, left: -22, bottom: 0 }}>
                  <defs>
                    <linearGradient id="ok" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={primary} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={primary} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={border} vertical={false} strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={(value: string) => value.slice(5)} tick={{ fontSize: 11, fill: muted }} axisLine={false} tickLine={false} minTickGap={24} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: muted }} axisLine={false} tickLine={false} />
                  <ChartTooltip
                    cursor={{ stroke: border }}
                    contentStyle={{ background: "var(--popover)", border: `1px solid ${border}`, borderRadius: 8, fontSize: 12, color: "var(--foreground)" }}
                    labelStyle={{ color: "var(--muted-foreground)" }}
                  />
                  <Area type="monotone" dataKey="succeeded" name="Succeeded" stroke={primary} fill="url(#ok)" strokeWidth={2} />
                  <Area type="monotone" dataKey="failed" name="Failed" stroke={destructive} fill="transparent" strokeWidth={1.5} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState className="h-full border-0" title="No runs yet" description="Create a run from a discovery JSON to see activity here." />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Needs attention</CardTitle>
            <CardDescription>Paused runs waiting for a human decision.</CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            {data && data.attention.length > 0 ? (
              <ul className="divide-y divide-border">
                {data.attention.map((run) => (
                  <li key={run.run_id}>
                    <Link to={`/runs/${run.run_id}`} className="group flex items-center gap-3 py-2.5" data-testid="attention-run">
                      <PauseCircle className="size-4 shrink-0 text-warning" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{run.name || run.input_filename}</div>
                        <div className="text-xs text-muted-foreground">
                          {labelOf(run.cloud)} · {run.pause_point?.replace("_", " ")} · {relativeTime(run.updated_at)}
                        </div>
                      </div>
                      <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="py-6 text-center text-sm text-muted-foreground">Nothing is waiting on you.</div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Recent runs</CardTitle>
              <CardDescription>Latest activity across all targets.</CardDescription>
            </div>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/runs">
                View all <ArrowRight />
              </Link>
            </Button>
          </CardHeader>
          <CardContent className="px-0 pt-0">
            {data && data.recent.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-5">Run</TableHead>
                    <TableHead>Target</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="pr-5 text-right">Updated</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.recent.map((run) => (
                    <TableRow key={run.run_id} clickable onClick={() => navigate(`/runs/${run.run_id}`)}>
                      <TableCell className="pl-5">
                        <div className="font-medium">{run.name || run.input_filename}</div>
                        <div className="font-mono text-[11px] text-muted-foreground">{shortId(run.run_id)}</div>
                      </TableCell>
                      <TableCell>
                        <TargetBadge name={run.cloud} icon={false} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={run.status} />
                      </TableCell>
                      <TableCell className="pr-5 text-right text-xs text-muted-foreground">{relativeTime(run.updated_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="px-5 pb-5">
                <EmptyState icon={Clock} title="No runs yet" action={can("operator") ? <Button size="sm" onClick={() => navigate("/runs/new")}>Create the first run</Button> : undefined} />
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Connections</CardTitle>
              <CardDescription>Target accounts available for plan and apply.</CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              {connections.data && connections.data.length > 0 ? (
                <ul className="space-y-2">
                  {connections.data.slice(0, 4).map((connection) => (
                    <li key={connection.id} className="flex items-center justify-between gap-3 text-sm">
                      <Link to={`/connections/${connection.id}`} className="flex min-w-0 items-center gap-2 hover:underline">
                        <Cable className="size-3.5 text-muted-foreground" />
                        <span className="truncate">{connection.name}</span>
                        <span className="truncate text-xs text-muted-foreground">{connection.provider_label ?? connection.provider}</span>
                      </Link>
                      <StatusBadge status={connection.status} />
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-sm text-muted-foreground">
                  No connections yet.{" "}
                  {can("admin") ? (
                    <Link to="/connections" className="text-primary hover:underline">
                      Add one
                    </Link>
                  ) : null}
                </div>
              )}
            </CardContent>
          </Card>
          <PostureCard checks={checks} loading={posture.loading} />
        </div>
      </div>
    </div>
  );
}

function PostureCard({ checks, loading }: { checks: PostureCheck[]; loading: boolean }) {
  const important = [...checks].sort((a, b) => rank(b.status) - rank(a.status)).slice(0, 4);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Security posture</CardTitle>
        <CardDescription>Live checks mapped to SOC 2, HIPAA and CIS.</CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        {loading ? (
          <Skeleton className="h-20" />
        ) : important.length === 0 ? (
          <div className="text-sm text-muted-foreground">No checks available.</div>
        ) : (
          <ul className="space-y-2">
            {important.map((check) => (
              <li key={check.id} className="flex items-start gap-2 text-sm">
                <StatusBadge status={check.status} className="mt-0.5 w-14 justify-center" />
                <div className="min-w-0">
                  <div className="truncate font-medium">{check.title}</div>
                  <div className="truncate text-xs text-muted-foreground">{check.detail}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
        <Button variant="ghost" size="sm" className="mt-3 -ml-2" asChild>
          <Link to="/settings/posture">
            All checks <ArrowRight />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function rank(status: PostureCheck["status"]): number {
  return status === "fail" ? 2 : status === "warn" ? 1 : 0;
}
