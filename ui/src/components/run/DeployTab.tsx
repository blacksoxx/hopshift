import * as React from "react";
import { Link } from "react-router-dom";
import { ArrowDownToLine, Bomb, Braces, Cable, Database, Hammer, Play, Save, StopCircle } from "lucide-react";
import { ApiError, api, subscribeDeploymentLog } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { useTargets } from "@/hooks/useTargets";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { SimpleSelect } from "@/components/ui/select";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Alert, Pill, Skeleton, Spinner, Stat } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime, formatDuration, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CodeView } from "./CodeView";
import type { Connection, Deployment, DeploymentAction, RunRecord, TerraformVariable } from "@/types";

const ACTIVE = new Set(["queued", "running"]);

export interface DeployTabProps {
  run: RunRecord;
  connections: Connection[];
  /** Whether the connections service is available (a connection is then mandatory). */
  connectionsEnabled: boolean;
  canOperate: boolean;
}

// ── variables ─────────────────────────────────────────────────────────────────

type VariableKind = "bool" | "number" | "json" | "string";

export function variableKind(variable: TerraformVariable): VariableKind {
  const base = (variable.type || "any").split("(")[0].trim();
  if (base === "bool") return "bool";
  if (base === "number") return "number";
  if (["list", "map", "set", "object", "tuple"].includes(base)) return "json";
  return "string";
}

function initialDraft(variables: TerraformVariable[]): Record<string, string | boolean> {
  const draft: Record<string, string | boolean> = {};
  for (const variable of variables) {
    const kind = variableKind(variable);
    const value = variable.sensitive ? undefined : (variable.set ? variable.value : undefined) ?? variable.default ?? undefined;
    if (kind === "bool") draft[variable.name] = value === true;
    else if (kind === "json") draft[variable.name] = value === undefined || value === null ? "" : JSON.stringify(value, null, 2);
    else draft[variable.name] = value === undefined || value === null ? "" : String(value);
  }
  return draft;
}

/** Turn the form draft into the `values` object for PUT; only changed fields are sent, blanks unset. */
export function variablePayload(variables: TerraformVariable[], draft: Record<string, string | boolean>, original: Record<string, string | boolean>): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const variable of variables) {
    const kind = variableKind(variable);
    const current = draft[variable.name];
    if (current === original[variable.name]) continue;
    if (kind === "bool") {
      values[variable.name] = current === true;
      continue;
    }
    const text = typeof current === "string" ? current.trim() : "";
    if (text === "") {
      if (variable.sensitive) continue; // leaving a secret blank keeps the stored value
      if (variable.set) values[variable.name] = null;
      continue;
    }
    if (kind === "number") {
      const parsed = Number(text);
      if (!Number.isFinite(parsed)) throw new Error(`${variable.name} must be a number.`);
      values[variable.name] = parsed;
    } else if (kind === "json") {
      try {
        values[variable.name] = JSON.parse(text);
      } catch {
        throw new Error(`${variable.name} must be valid JSON (${variable.type}).`);
      }
    } else {
      values[variable.name] = text;
    }
  }
  return values;
}

function VariablesCard({ runId, canOperate, enabled }: { runId: string; canOperate: boolean; enabled: boolean }) {
  const { toast } = useToast();
  const variables = useAsync(() => api.deployVariables(runId), [runId], { enabled });
  const [draft, setDraft] = React.useState<Record<string, string | boolean>>({});
  const [original, setOriginal] = React.useState<Record<string, string | boolean>>({});
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (!variables.data) return;
    const next = initialDraft(variables.data);
    setDraft(next);
    setOriginal(next);
  }, [variables.data]);

  const dirty = Object.keys(draft).some((key) => draft[key] !== original[key]);

  async function save() {
    if (!variables.data) return;
    setError(null);
    let values: Record<string, unknown>;
    try {
      values = variablePayload(variables.data, draft, original);
    } catch (exc) {
      setError((exc as Error).message);
      return;
    }
    if (Object.keys(values).length === 0) return;
    setSaving(true);
    try {
      const updated = await api.setDeployVariables(runId, values);
      variables.setData(updated);
      toast({ title: "Variables saved", description: `${Object.keys(values).length} value${Object.keys(values).length === 1 ? "" : "s"} written to terraform.tfvars.json.`, variant: "success" });
    } catch (exc) {
      setError((exc as Error).message);
      toast({ title: "Could not save variables", description: (exc as Error).message, variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card data-testid="deploy-variables">
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>Variables</CardTitle>
          <CardDescription>Inputs declared by the generated root module. A plan embeds the values it was made with.</CardDescription>
        </div>
        {canOperate && enabled ? (
          <Button size="sm" onClick={() => void save()} loading={saving} disabled={!dirty} data-testid="deploy-variables-save">
            <Save /> Save
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="pt-0">
        {!enabled ? (
          <div className="text-sm text-muted-foreground">Available once the run has succeeded.</div>
        ) : variables.loading && !variables.data ? (
          <div className="space-y-2">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </div>
        ) : variables.error ? (
          <Alert variant="warning">{variables.error}</Alert>
        ) : (variables.data ?? []).length === 0 ? (
          <div className="text-sm text-muted-foreground">The root module declares no variables.</div>
        ) : (
          <div className="space-y-4">
            {error ? <Alert variant="error">{error}</Alert> : null}
            <div className="grid gap-4 md:grid-cols-2">
              {(variables.data ?? []).map((variable) => (
                <VariableField key={variable.name} variable={variable} value={draft[variable.name] ?? ""} disabled={!canOperate} onChange={(value) => setDraft((current) => ({ ...current, [variable.name]: value }))} />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function VariableField({ variable, value, disabled, onChange }: { variable: TerraformVariable; value: string | boolean; disabled: boolean; onChange: (value: string | boolean) => void }) {
  const kind = variableKind(variable);
  const id = `var-${variable.name}`;
  const label = (
    <div className="flex flex-wrap items-center gap-1.5">
      <Label htmlFor={id} className="font-mono text-xs">
        {variable.name}
      </Label>
      <span className="text-[10.5px] text-muted-foreground">{variable.type}</span>
      {variable.required ? <Badge variant="warning" className="h-4 px-1 text-[10px]">required</Badge> : null}
      {variable.sensitive ? <Badge variant="muted" className="h-4 px-1 text-[10px]">sensitive</Badge> : null}
      {variable.set ? <Badge variant="success" className="h-4 px-1 text-[10px]" data-testid={`var-set-${variable.name}`}>set</Badge> : null}
    </div>
  );
  return (
    <div className={cn("space-y-1.5", kind === "json" && "md:col-span-2")} data-testid={`var-${variable.name}`}>
      {label}
      {kind === "bool" ? (
        <div className="flex h-9 items-center gap-2">
          <Switch id={id} checked={value === true} onCheckedChange={onChange} disabled={disabled} />
          <span className="text-xs text-muted-foreground">{value === true ? "true" : "false"}</span>
        </div>
      ) : kind === "json" ? (
        <Textarea id={id} value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value)} placeholder={variable.default !== null && variable.default !== undefined ? JSON.stringify(variable.default) : "{}"} className="min-h-[72px] font-mono text-xs" disabled={disabled} spellCheck={false} />
      ) : (
        <Input
          id={id}
          type={variable.sensitive ? "password" : kind === "number" ? "number" : "text"}
          autoComplete={variable.sensitive ? "new-password" : undefined}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value)}
          placeholder={variable.sensitive ? (variable.set ? "•••••• (stored; leave blank to keep)" : "not set") : variable.default !== null && variable.default !== undefined ? String(variable.default) : variable.required ? "required" : ""}
          className={cn("h-8 text-sm", kind !== "number" && "font-mono text-xs")}
          disabled={disabled}
        />
      )}
      {variable.description ? <p className="text-xs text-muted-foreground">{variable.description}</p> : null}
    </div>
  );
}

// ── log stream ────────────────────────────────────────────────────────────────

function DeploymentLog({ runId, deployment, onFinished }: { runId: string; deployment: Deployment; onFinished: () => void }) {
  const [lines, setLines] = React.useState<string[]>([]);
  const [status, setStatus] = React.useState<"loading" | "live" | "polling" | "done">("loading");
  const [autoScroll, setAutoScroll] = React.useState(true);
  const container = React.useRef<HTMLDivElement>(null);
  const finishedRef = React.useRef(onFinished);
  finishedRef.current = onFinished;
  const active = ACTIVE.has(deployment.status);
  const id = deployment.id;

  React.useEffect(() => {
    let cancelled = false;
    let unsubscribe: (() => void) | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    let cursor = 0;
    setLines([]);
    setStatus("loading");

    const finish = () => {
      if (cancelled) return;
      setStatus("done");
      finishedRef.current();
    };
    const poll = () => {
      setStatus("polling");
      timer = setInterval(() => {
        api.deploymentLog(runId, id, cursor)
          .then((chunk) => {
            if (cancelled) return;
            if (chunk.lines.length > 0) setLines((current) => [...current, ...chunk.lines]);
            cursor = chunk.next;
            if (chunk.done) {
              if (timer) clearInterval(timer);
              finish();
            }
          })
          .catch(() => undefined);
      }, 1500);
    };
    const stream = () => {
      setStatus("live");
      unsubscribe = subscribeDeploymentLog(
        runId,
        id,
        cursor,
        (line) => {
          cursor += 1;
          setLines((current) => [...current, line]);
        },
        (result) => {
          if (cancelled) return;
          if (result === "disconnected") poll();
          else finish();
        },
      );
    };

    api.deploymentLog(runId, id, 0)
      .then((chunk) => {
        if (cancelled) return;
        setLines(chunk.lines);
        cursor = chunk.next;
        if (chunk.done || !active) setStatus("done");
        else stream();
      })
      .catch(() => {
        if (!cancelled) setStatus("done");
      });

    return () => {
      cancelled = true;
      unsubscribe?.();
      if (timer) clearInterval(timer);
    };
  }, [runId, id, active]);

  React.useEffect(() => {
    if (!autoScroll || !container.current) return;
    container.current.scrollTop = container.current.scrollHeight;
  }, [lines.length, autoScroll]);

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-muted/40">
      <div className="flex items-center gap-3 border-b border-border px-3 py-1.5 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">terraform.log</span>
        <span>
          {lines.length} line{lines.length === 1 ? "" : "s"}
        </span>
        {status === "live" ? (
          <span className="inline-flex items-center gap-1 text-info">
            <Spinner className="size-3 text-info" /> streaming
          </span>
        ) : status === "polling" ? (
          <span className="inline-flex items-center gap-1 text-warning">
            <Spinner className="size-3 text-warning" /> polling
          </span>
        ) : status === "loading" ? (
          <Spinner className="size-3" />
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <Switch id={`log-scroll-${id}`} checked={autoScroll} onCheckedChange={setAutoScroll} className="scale-90" />
          <Label htmlFor={`log-scroll-${id}`} className="flex cursor-pointer items-center gap-1 text-xs font-normal text-muted-foreground">
            <ArrowDownToLine className="size-3.5" /> Auto-scroll
          </Label>
        </div>
      </div>
      <div ref={container} className="max-h-[420px] min-h-[160px] overflow-auto p-3 font-mono text-[12px] leading-relaxed" data-testid="deployment-log">
        {lines.length === 0 ? (
          <div className="text-muted-foreground">{status === "done" ? "No output." : "Waiting for output…"}</div>
        ) : (
          <pre className="whitespace-pre-wrap break-words">{lines.join("\n")}</pre>
        )}
      </div>
    </div>
  );
}

// ── deployment detail ─────────────────────────────────────────────────────────

const ACTION_VARIANT: Record<string, "success" | "warning" | "danger" | "info" | "muted" | "secondary"> = {
  create: "success",
  update: "warning",
  delete: "danger",
  replace: "danger",
  read: "info",
  "no-op": "muted",
};

function actionLabel(actions: string[]): string {
  if (actions.includes("delete") && actions.includes("create")) return "replace";
  return actions.join(", ") || "no-op";
}

function DeploymentDetail({ runId, deployment, canOperate, onChanged }: { runId: string; deployment: Deployment; canOperate: boolean; onChanged: () => void }) {
  const { toast } = useToast();
  const [cancelling, setCancelling] = React.useState(false);
  const [planOpen, setPlanOpen] = React.useState(false);
  const plan = useAsync(() => api.deploymentPlan(runId, deployment.id), [runId, deployment.id], { enabled: planOpen });
  const summary = deployment.summary;
  const active = ACTIVE.has(deployment.status);

  async function cancel() {
    setCancelling(true);
    try {
      await api.cancelDeployment(runId, deployment.id);
      toast({ title: "Cancelling deployment", description: "Terraform receives SIGTERM, then SIGKILL after 10 s.", variant: "warning" });
      onChanged();
    } catch (exc) {
      toast({ title: "Could not cancel", description: (exc as Error).message, variant: "error" });
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="space-y-4" data-testid="deployment-detail">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium capitalize">{deployment.action}</span>
        <StatusBadge status={deployment.status} />
        <Pill>{deployment.id.slice(0, 12)}</Pill>
        {deployment.connection_name ? (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Cable className="size-3.5" /> {deployment.connection_name}
          </span>
        ) : null}
        {deployment.exit_code !== null ? <span className="text-xs text-muted-foreground">exit {deployment.exit_code}</span> : null}
        <div className="ml-auto flex items-center gap-2">
          {deployment.action === "plan" && deployment.status === "succeeded" ? (
            <Button variant="outline" size="sm" onClick={() => setPlanOpen(true)} data-testid="deployment-view-plan">
              <Braces /> Plan JSON
            </Button>
          ) : null}
          {canOperate && active ? (
            <Button variant="outline" size="sm" onClick={() => void cancel()} loading={cancelling} data-testid="deployment-cancel">
              <StopCircle /> Cancel
            </Button>
          ) : null}
        </div>
      </div>

      {deployment.error ? (
        <Alert variant="error" title={deployment.status === "cancelled" ? "Cancelled" : "Terraform failed"} testId="deployment-error">
          <pre className="font-mono text-xs">{deployment.error}</pre>
        </Alert>
      ) : null}

      {summary ? (
        <div className="grid gap-3 sm:grid-cols-4">
          <Stat label="Add" value={summary.add} tone={summary.add > 0 ? "success" : "default"} />
          <Stat label="Change" value={summary.change} tone={summary.change > 0 ? "warning" : "default"} />
          <Stat label="Destroy" value={summary.destroy} tone={summary.destroy > 0 ? "danger" : "default"} />
          <Stat label="Replace" value={summary.replace ?? 0} tone={(summary.replace ?? 0) > 0 ? "danger" : "default"} />
        </div>
      ) : null}

      {summary && summary.resources.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-border">
          <Table data-testid="deployment-resources">
            <TableHeader>
              <TableRow>
                <TableHead className="pl-3">Address</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="pr-3">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.resources.map((resource) => (
                <TableRow key={resource.address}>
                  <TableCell className="pl-3 font-mono text-xs">{resource.address}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{resource.type}</TableCell>
                  <TableCell className="pr-3">
                    <Badge variant={ACTION_VARIANT[actionLabel(resource.actions)] ?? "secondary"} className="font-mono text-[10.5px]">
                      {actionLabel(resource.actions)}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}

      <DeploymentLog runId={runId} deployment={deployment} onFinished={onChanged} />

      <Dialog open={planOpen} onOpenChange={setPlanOpen}>
        <DialogContent size="xl" className="max-h-[85vh] overflow-hidden p-0">
          <DialogHeader className="px-6 pt-6">
            <DialogTitle>Plan output</DialogTitle>
            <DialogDescription>
              terraform show -json for deployment <span className="font-mono">{deployment.id.slice(0, 12)}</span>. Sensitive values are blanked.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 max-h-[65vh] overflow-auto border-t border-border bg-muted/30">
            {plan.loading && !plan.data ? (
              <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
                <Spinner /> Loading plan…
              </div>
            ) : plan.error ? (
              <div className="p-4">
                <Alert variant="error">{plan.error}</Alert>
              </div>
            ) : (
              <CodeView code={JSON.stringify(plan.data ?? {}, null, 2)} lang="json" testId="deployment-plan-json" />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ── tab ───────────────────────────────────────────────────────────────────────

export function DeployTab({ run, connections, connectionsEnabled, canOperate }: DeployTabProps) {
  const { toast } = useToast();
  const runId = run.run_id;
  const succeeded = run.status === "succeeded";
  const { labelOf, providerOf } = useTargets();
  const targetLabel = labelOf(run.cloud);
  const provider = providerOf(run.cloud);
  const sameTarget = React.useMemo(() => connections.filter((connection) => connection.provider === provider), [connections, provider]);
  const [connectionId, setConnectionId] = React.useState<string>(() => (run.connection_id && sameTarget.some((item) => item.id === run.connection_id) ? run.connection_id : (sameTarget[0]?.id ?? "")));
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [dialog, setDialog] = React.useState<Exclude<DeploymentAction, "plan"> | null>(null);
  const [confirmation, setConfirmation] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [gateError, setGateError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!connectionId && sameTarget.length > 0) setConnectionId(run.connection_id && sameTarget.some((item) => item.id === run.connection_id) ? run.connection_id : sameTarget[0].id);
  }, [sameTarget, connectionId, run.connection_id]);

  const deployments = useAsync(() => api.listDeployments(runId), [runId], { pollMs: (data) => (data?.some((item) => ACTIVE.has(item.status)) ? 2500 : null) });
  const list = React.useMemo(() => deployments.data ?? [], [deployments.data]);
  const activeDeployment = list.find((item) => ACTIVE.has(item.status)) ?? null;
  const latestPlan = list.find((item) => item.action === "plan" && item.status === "succeeded") ?? null;
  const selected = list.find((item) => item.id === selectedId) ?? list[0] ?? null;
  const finishedCount = list.filter((item) => !ACTIVE.has(item.status)).length;
  const state = useAsync(() => api.deployState(runId), [runId, finishedCount], { enabled: succeeded });

  const needsConnection = connectionsEnabled && !connectionId;
  const canAct = canOperate && succeeded && !activeDeployment && !needsConnection;

  async function submit(action: DeploymentAction) {
    setSubmitting(true);
    setGateError(null);
    try {
      const created = await api.createDeployment(runId, {
        action,
        connection_id: connectionsEnabled ? connectionId : null,
        plan_id: action === "apply" ? latestPlan?.id : undefined,
        confirmation: action === "plan" ? undefined : confirmation,
      });
      setDialog(null);
      setConfirmation("");
      setSelectedId(created.id);
      toast({ title: `terraform ${action} queued`, description: created.connection_name ? `Using ${created.connection_name}.` : undefined, variant: "success" });
      await deployments.reload();
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 403) {
        setGateError(exc.message);
        setDialog(null);
      } else {
        toast({ title: `Could not start ${action}`, description: (exc as Error).message, variant: "error" });
      }
    } finally {
      setSubmitting(false);
    }
  }

  const confirmed = confirmation.trim() === runId;

  return (
    <div className="space-y-4" data-testid="deploy">
      {!succeeded ? (
        <Alert variant="info" testId="deploy-unavailable">
          Deployments become available once the run has succeeded and written its Terraform root module.
        </Alert>
      ) : null}
      {gateError ? (
        <Alert variant="error" title="Not allowed" testId="deploy-gate-error">
          {gateError}. An admin can change <span className="font-mono">deploy.allow_apply</span> / <span className="font-mono">deploy.allow_destroy</span> in Settings.
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Target</CardTitle>
          <CardDescription>Plan against a {targetLabel} connection, review the plan, then apply with a typed confirmation.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 pt-0">
          {connectionsEnabled ? (
            <div className="grid gap-2 md:max-w-md">
              <Label htmlFor="deploy-connection">Connection</Label>
              {sameTarget.length === 0 ? (
                <Alert variant="warning" testId="deploy-no-connection">
                  No {targetLabel} connection yet.{" "}
                  <Link to="/connections" className="font-medium text-primary hover:underline">
                    Add one in Connections
                  </Link>{" "}
                  to plan or apply.
                </Alert>
              ) : (
                <SimpleSelect id="deploy-connection" value={connectionId} onValueChange={setConnectionId} options={sameTarget.map((item) => ({ value: item.id, label: `${item.name} · ${item.auth_method}${item.status === "ok" ? "" : ` (${item.status})`}` }))} disabled={!canOperate} testId="deploy-connection" />
              )}
            </div>
          ) : (
            <div className="text-xs text-muted-foreground">The connections service is not installed; Terraform inherits the server's environment.</div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => void submit("plan")} disabled={!canAct} loading={submitting && dialog === null} data-testid="deploy-plan">
              <Play /> Plan
            </Button>
            <Button
              variant="outline"
              disabled={!canAct || !latestPlan}
              onClick={() => {
                setConfirmation("");
                setDialog("apply");
              }}
              data-testid="deploy-apply"
            >
              <Hammer /> Apply…
            </Button>
            <Button
              variant="outline"
              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
              disabled={!canAct}
              onClick={() => {
                setConfirmation("");
                setDialog("destroy");
              }}
              data-testid="deploy-destroy"
            >
              <Bomb /> Destroy…
            </Button>
            <span className="text-xs text-muted-foreground">
              {!canOperate ? "Operator role required." : activeDeployment ? `A ${activeDeployment.action} is ${activeDeployment.status}.` : latestPlan ? `Apply uses plan ${latestPlan.id.slice(0, 8)} (${relativeTime(latestPlan.finished_at)}).` : succeeded ? "Run a plan first to enable apply." : null}
            </span>
          </div>
        </CardContent>
      </Card>

      <VariablesCard runId={runId} canOperate={canOperate} enabled={succeeded} />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader>
            <CardTitle>Deployments</CardTitle>
            <CardDescription>Every plan, apply and destroy requested for this run, newest first.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 px-0 pt-0">
            {deployments.loading && !deployments.data ? (
              <div className="space-y-2 px-5">
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
              </div>
            ) : deployments.error ? (
              <div className="px-5">
                <Alert variant="error" action={<Button size="sm" variant="outline" onClick={() => void deployments.reload()}>Retry</Button>}>{deployments.error}</Alert>
              </div>
            ) : list.length === 0 ? (
              <div className="px-5 text-sm text-muted-foreground">Nothing deployed yet.</div>
            ) : (
              <Table data-testid="deployments-table">
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-5">Action</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="hidden md:table-cell">Requested by</TableHead>
                    <TableHead className="hidden md:table-cell">Started</TableHead>
                    <TableHead className="hidden lg:table-cell">Finished</TableHead>
                    <TableHead className="pr-5 text-right">Duration</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {list.map((item) => (
                    <TableRow key={item.id} clickable onClick={() => setSelectedId(item.id)} data-state={selected?.id === item.id ? "selected" : undefined} data-testid="deployment-row" data-action={item.action} data-status={item.status}>
                      <TableCell className="pl-5 font-medium capitalize">{item.action}</TableCell>
                      <TableCell>
                        <StatusBadge status={item.status} />
                      </TableCell>
                      <TableCell className="hidden text-xs text-muted-foreground md:table-cell">{item.requested_by ?? "–"}</TableCell>
                      <TableCell className="hidden text-xs text-muted-foreground md:table-cell" title={formatDateTime(item.started_at ?? item.created_at)}>
                        {relativeTime(item.started_at ?? item.created_at)}
                      </TableCell>
                      <TableCell className="hidden text-xs text-muted-foreground lg:table-cell" title={formatDateTime(item.finished_at)}>
                        {item.finished_at ? relativeTime(item.finished_at) : "–"}
                      </TableCell>
                      <TableCell className="pr-5 text-right text-xs tabular text-muted-foreground">{formatDuration(item.started_at, item.finished_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {selected ? (
              <div className="border-t border-border px-5 pt-4">
                <DeploymentDetail runId={runId} deployment={selected} canOperate={canOperate} onChanged={() => void deployments.reload()} />
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card className="self-start">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="size-4 text-muted-foreground" /> State
            </CardTitle>
            <CardDescription>Terraform state for this run.</CardDescription>
          </CardHeader>
          <CardContent className="pt-0" data-testid="deploy-state">
            {!succeeded ? (
              <div className="text-sm text-muted-foreground">Available once the run has succeeded.</div>
            ) : state.loading && !state.data ? (
              <Skeleton className="h-16" />
            ) : state.error ? (
              <Alert variant="warning">{state.error}</Alert>
            ) : state.data?.remote ? (
              <div className="text-sm text-muted-foreground">
                Remote state on <span className="font-mono">{state.data.backend}</span>; inspect it with <span className="font-mono">terraform state list</span>.
              </div>
            ) : !state.data?.exists ? (
              <div className="text-sm text-muted-foreground">No state yet. It is written by the first apply.</div>
            ) : (
              <div className="space-y-3 text-sm">
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span>
                    serial <span className="font-mono text-foreground">{state.data.serial ?? "–"}</span>
                  </span>
                  <span>
                    terraform <span className="font-mono text-foreground">{state.data.terraform_version ?? "–"}</span>
                  </span>
                </div>
                <div className="font-medium">
                  {state.data.resources?.length ?? 0} resource{(state.data.resources?.length ?? 0) === 1 ? "" : "s"}
                </div>
                {(state.data.resources ?? []).length > 0 ? (
                  <ul className="max-h-72 space-y-1 overflow-auto font-mono text-xs">
                    {(state.data.resources ?? []).map((resource) => (
                      <li key={resource.address} className="truncate" title={resource.address}>
                        {resource.address}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog
        open={dialog !== null}
        onOpenChange={(open) => {
          if (!open) setDialog(null);
        }}
      >
        <DialogContent size="md">
          <DialogHeader>
            <DialogTitle>{dialog === "destroy" ? "Destroy the deployed infrastructure?" : "Apply this plan?"}</DialogTitle>
            <DialogDescription>
              {dialog === "destroy"
                ? `terraform destroy removes every resource in this run's state${connectionsEnabled ? ` using ${sameTarget.find((item) => item.id === connectionId)?.name ?? "the selected connection"}` : ""}. This cannot be undone.`
                : `terraform apply executes the saved plan${latestPlan ? ` ${latestPlan.id.slice(0, 8)}` : ""} without re-planning. Variables changed since then have no effect.`}
            </DialogDescription>
          </DialogHeader>
          {dialog === "apply" && latestPlan?.summary ? (
            <div className="mt-4 grid grid-cols-4 gap-2" data-testid="deploy-confirm-summary">
              {(["add", "change", "destroy", "replace"] as const).map((key) => (
                <div key={key} className="rounded-lg border border-border px-3 py-2 text-center">
                  <div className={cn("text-xl font-semibold tabular", key === "add" ? "text-success" : key === "change" ? "text-warning" : "text-destructive")}>{latestPlan.summary?.[key] ?? 0}</div>
                  <div className="text-[11px] text-muted-foreground">{key}</div>
                </div>
              ))}
            </div>
          ) : null}
          <div className="mt-4 space-y-1.5">
            <Label htmlFor="deploy-confirmation">
              Type the run id <span className="font-mono text-xs text-muted-foreground">{runId}</span> to confirm
            </Label>
            <Input id="deploy-confirmation" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={runId} autoComplete="off" spellCheck={false} className="font-mono text-xs" data-testid="deploy-confirm-input" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={!confirmed} loading={submitting} onClick={() => dialog && void submit(dialog)} data-testid="deploy-confirm">
              {dialog === "destroy" ? <Bomb /> : <Hammer />} {dialog === "destroy" ? "Destroy" : "Apply"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
