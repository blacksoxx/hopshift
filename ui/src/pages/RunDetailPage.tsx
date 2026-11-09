import * as React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { FileCode, LayoutDashboard, Rocket, ScrollText, ShieldCheck, TableProperties } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, Kbd, Skeleton } from "@/components/ui/misc";
import { useAuth } from "@/providers/AuthProvider";
import { RunBanners, RunHeader } from "@/components/run/RunHeader";
import { Timeline } from "@/components/run/Timeline";
import { OverviewTab } from "@/components/run/OverviewTab";
import { CimTab } from "@/components/run/CimTab";
import { ArtifactsTab } from "@/components/run/ArtifactsTab";
import { DeployTab } from "@/components/run/DeployTab";
import { ComplianceTab } from "@/components/run/ComplianceTab";
import { LogTab } from "@/components/run/LogTab";
import { useRunData } from "@/components/run/useRunData";
import type { Connection } from "@/types";

type TabName = "overview" | "cim" | "artifacts" | "deploy" | "compliance" | "log";

const TAB_META: Record<TabName, { label: string; icon: React.ComponentType<{ className?: string }> }> = {
  overview: { label: "Overview", icon: LayoutDashboard },
  cim: { label: "CIM", icon: TableProperties },
  artifacts: { label: "Artifacts", icon: FileCode },
  deploy: { label: "Deploy", icon: Rocket },
  compliance: { label: "Compliance", icon: ShieldCheck },
  log: { label: "Log", icon: ScrollText },
};

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable || target.closest("[role=dialog]") !== null;
}

export function RunDetailPage() {
  const { runId = "", tab: tabParam } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const canOperate = can("operator");
  const data = useRunData(runId);
  const { run, events, state, meta, executing, refresh } = data;

  const connectionsEnabled = meta?.features.connections !== false;
  const connections = useAsync<Connection[]>(() => (meta && meta.features.connections ? api.listConnections().catch(() => []) : Promise.resolve([])), [meta?.features.connections, meta !== null]);

  const tabs = React.useMemo<TabName[]>(() => ["overview", "cim", "artifacts", ...(meta?.features.deployments ? (["deploy"] as TabName[]) : []), "compliance", "log"], [meta?.features.deployments]);
  const tab: TabName = tabs.includes(tabParam as TabName) ? (tabParam as TabName) : "overview";

  const goTo = React.useCallback(
    (next: string) => {
      navigate(next === "overview" ? `/runs/${runId}` : `/runs/${runId}/${next}`, { replace: true });
    },
    [navigate, runId],
  );

  React.useEffect(() => {
    if (tabParam && !tabs.includes(tabParam as TabName) && meta) goTo("overview");
  }, [tabParam, tabs, meta, goTo]);

  React.useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return;
      if (event.key === "r") {
        event.preventDefault();
        void refresh();
        return;
      }
      const index = Number(event.key);
      if (Number.isInteger(index) && index >= 1 && index <= tabs.length) {
        event.preventDefault();
        goTo(tabs[index - 1]);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tabs, goTo, refresh]);

  if (!run) {
    if (data.error) {
      return (
        <Alert variant="error" title="Could not load this run" action={<Button size="sm" variant="outline" onClick={() => void refresh()}>Retry</Button>} testId="run-error">
          {data.error}
        </Alert>
      );
    }
    return (
      <div className="space-y-5" data-testid="run-loading">
        <Skeleton className="h-4 w-16" />
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-2">
            <Skeleton className="h-7 w-64" />
            <Skeleton className="h-4 w-96" />
          </div>
          <Skeleton className="h-9 w-40" />
        </div>
        <Skeleton className="h-24" />
        <Skeleton className="h-9 w-96" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[88px]" />
          ))}
        </div>
      </div>
    );
  }

  const paused = run.status === "paused" && !executing;
  const cimEditable = paused && run.pause_point === "review_cim" && canOperate;
  const cimReason = !canOperate ? "Viewers can inspect the CIM; the operator role is required to edit it." : paused ? `The run is paused at ${run.pause_point ?? run.paused_before}; the CIM can only be edited at review_cim.` : "The CIM is read-only. It can be edited while the run is paused at review_cim.";
  const nodes = meta?.nodes ?? [];

  return (
    <div>
      <RunHeader run={run} meta={meta} connections={connections.data ?? []} canOperate={canOperate} executing={executing} onChange={data.setRun} onRefresh={refresh} />
      {data.error ? (
        <Alert variant="warning" className="mb-4" action={<Button size="sm" variant="outline" onClick={() => void refresh()}>Retry</Button>}>
          {data.error}
        </Alert>
      ) : null}
      <RunBanners run={run} executing={executing} />

      <div className="surface mb-5 overflow-x-auto px-4 py-4 sm:px-6">
        {nodes.length > 0 ? <Timeline nodes={nodes} events={events} run={run} /> : <Skeleton className="h-14" />}
      </div>

      <Tabs value={tab} onValueChange={goTo}>
        <TabsList className="-mx-1 overflow-x-auto px-1" aria-label="Run sections">
          {tabs.map((name, index) => {
            const { label, icon: Icon } = TAB_META[name];
            return (
              <TabsTrigger key={name} value={name} data-testid={`tab-${name}`} className="shrink-0">
                <Icon className="size-4" />
                {label}
                <Kbd className="ml-0.5 hidden h-4 min-w-4 px-1 opacity-0 transition-opacity group-hover/tab:opacity-100 md:inline-flex">{index + 1}</Kbd>
              </TabsTrigger>
            );
          })}
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab run={run} state={state} events={events} />
        </TabsContent>
        <TabsContent value="cim">
          <CimTab runId={run.run_id} cim={state?.values.sized_cim ?? state?.values.cim ?? null} editable={cimEditable} readOnlyReason={cimReason} onSaved={refresh} />
        </TabsContent>
        <TabsContent value="artifacts">
          <ArtifactsTab run={run} />
        </TabsContent>
        {meta?.features.deployments ? (
          <TabsContent value="deploy">
            <DeployTab run={run} connections={connections.data ?? []} connectionsEnabled={connectionsEnabled} canOperate={canOperate} />
          </TabsContent>
        ) : null}
        <TabsContent value="compliance">
          <ComplianceTab runId={run.run_id} />
        </TabsContent>
        <TabsContent value="log">
          <LogTab events={events} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
