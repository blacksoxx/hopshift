import * as React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { motion } from "motion/react";
import { ArrowLeft, ArrowRight, Cable, Check, CircleHelp, FileJson, Rocket, Upload, X } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { useMeta } from "@/hooks/useMeta";
import { useTargets } from "@/hooks/useTargets";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { SimpleSelect } from "@/components/ui/select";
import { ToggleRow, Checkbox } from "@/components/ui/switch";
import { Alert, PageHeader, Skeleton } from "@/components/ui/misc";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Hint } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import { StatusBadge } from "@/components/StatusBadge";
import { TIER_COPY, TierBadge } from "@/components/TargetBadge";
import { cn } from "@/lib/utils";
import { formatBytes, pluralize } from "@/lib/format";
import type { Connection, RunOptions, SourceSpec, SupportTier } from "@/types";

const STEPS = ["Discovery", "Target", "Connection", "Review"] as const;

/** Keys a discovery export may use for its list of workloads; the first one present wins. */
const UNIT_KEYS = ["virtual_machines", "vms", "compute_units", "instances", "workloads"];

export interface DiscoverySummary {
  /** `metadata.schema_name`, which selects the source; null when the file declares none. */
  schema: string | null;
  units: number;
  clusters: number;
  /** Where the inventory was collected from (a vCenter, a host, an API endpoint), when the file says. */
  origin: string | null;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** Source-agnostic counts: enough to sanity-check the upload; the source translator does the real work. */
export function summarizeDiscovery(payload: unknown): DiscoverySummary {
  const data = asRecord(payload);
  const metadata = asRecord(data.metadata);
  const unitKey = UNIT_KEYS.find((key) => Array.isArray(data[key]));
  const units = (unitKey ? (data[unitKey] as unknown[]) : []).map(asRecord);
  const clusters = new Set<string>();
  const origins = new Set<string>();
  for (const unit of units) {
    const cluster = text(unit.cluster) ?? text(unit.cluster_ref);
    if (cluster) clusters.add(cluster);
    const origin = text(unit.source_vcenter) ?? text(unit.source);
    if (origin) origins.add(origin);
  }
  const queried = Array.isArray(metadata.vcenters_queried) ? (metadata.vcenters_queried as unknown[]).map(String).filter(Boolean) : [];
  const first = queried[0] ?? [...origins][0] ?? text(metadata.source_vcenter) ?? text(metadata.source) ?? text(metadata.hostname);
  const extra = Math.max(queried.length, origins.size) - 1;
  return {
    schema: text(metadata.schema_name),
    units: units.length,
    clusters: clusters.size,
    origin: first ? (extra > 0 ? `${first} +${extra}` : first) : null,
  };
}

interface LoadedFile {
  name: string;
  size: number;
  payload: unknown;
  summary: DiscoverySummary;
}

function describeSources(sources: SourceSpec[]): string {
  if (sources.length === 0) return "No sources are registered on this server.";
  return `Registered sources: ${sources.map((item) => `${item.label} (${item.schema_names.join(", ")})`).join("; ")}.`;
}

export function NewRunPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { toast } = useToast();
  const { meta, loading: metaLoading, error: metaError } = useMeta();
  const { targets, sources, labelOf, specOf, providerOf, sourceForSchema } = useTargets();
  const connections = useAsync(() => api.listConnections().catch(() => [] as Connection[]), []);

  const [step, setStep] = React.useState(0);
  const [file, setFile] = React.useState<LoadedFile | null>(null);
  const [fileError, setFileError] = React.useState<string | null>(null);
  const [name, setName] = React.useState("");
  const [tags, setTags] = React.useState<string[]>([]);
  const [tagInput, setTagInput] = React.useState("");
  const [connectionId, setConnectionId] = React.useState<string>(params.get("connection") ?? "");
  const [startNow, setStartNow] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [options, setOptions] = React.useState<RunOptions>({
    cloud: (params.get("cloud") ?? "").trim().toLowerCase(),
    environment: "dev",
    owner: "",
    mode: null,
    llm_provider: null,
    llm_model: null,
    skip_validation: false,
    skip_opa: false,
    no_mcp: true,
    dry_run: false,
    llm_review_notes: false,
    pause_points: null,
  });
  const [pausePoints, setPausePoints] = React.useState<string[] | null>(null);
  const fileInput = React.useRef<HTMLInputElement>(null);

  // Default to the first registered target unless the URL named a known one.
  React.useEffect(() => {
    if (targets.length === 0) return;
    setOptions((current) => (targets.some((item) => item.name === current.cloud) ? current : { ...current, cloud: targets[0].name }));
  }, [targets]);

  const defaultPauses = meta?.default_pause_points ?? ["review_cim", "approve_output"];
  const effectivePauses = pausePoints ?? defaultPauses;
  const update = <K extends keyof RunOptions>(key: K, value: RunOptions[K]) => setOptions((current) => ({ ...current, [key]: value }));

  const target = specOf(options.cloud);
  const targetLabel = labelOf(options.cloud);
  const source = file ? sourceForSchema(file.summary.schema) : undefined;
  const registryReady = !metaLoading && !metaError;

  async function readFile(selected: File) {
    setFileError(null);
    try {
      const parsed = JSON.parse(await selected.text()) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error(`${selected.name} is not a JSON object.`);
      setFile({ name: selected.name, size: selected.size, payload: parsed, summary: summarizeDiscovery(parsed) });
      if (!name) setName(selected.name.replace(/\.json$/i, ""));
    } catch (exc) {
      setFile(null);
      setFileError((exc as Error).message);
    }
  }

  function addTag(raw: string) {
    const tag = raw.trim().toLowerCase().replace(/\s+/g, "-");
    if (tag && !tags.includes(tag)) setTags([...tags, tag]);
    setTagInput("");
  }

  const connectionProvider = target ? target.connection_provider : providerOf(options.cloud);
  const matchingConnections = connectionProvider ? (connections.data ?? []).filter((item) => item.provider === connectionProvider) : [];

  const stepValid = [
    file !== null && source !== undefined,
    options.cloud.length > 0 && options.environment.trim().length > 0 && options.owner.trim().length > 0 && (options.mode === null || options.mode === "deterministic" || !!options.llm_provider),
    true,
    true,
  ][step];

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const record = await api.createRun({
        discovery: file.payload,
        options: { ...options, pause_points: pausePoints, mode: options.mode || null },
        input_filename: file.name,
        start: startNow,
        name: name.trim() || null,
        tags,
        connection_id: connectionId || null,
      });
      toast({ title: startNow ? "Run started" : "Run created", description: record.name || record.run_id, variant: "success" });
      navigate(`/runs/${record.run_id}`);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="New migration run" description="Four short steps: upload discovery, choose the target, pick a connection, review and start." />

      <ol className="mb-6 flex items-center gap-2 text-sm" aria-label="Steps">
        {STEPS.map((label, index) => (
          <li key={label} className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => index < step && setStep(index)}
              className={cn("flex items-center gap-2 rounded-full px-2.5 py-1 transition-colors", index === step ? "bg-primary/10 text-primary" : index < step ? "text-foreground hover:bg-accent" : "text-muted-foreground")}
              disabled={index > step}
              data-testid={`step-${index}`}
            >
              <span className={cn("flex size-5 items-center justify-center rounded-full border text-[11px] font-semibold", index < step ? "border-primary bg-primary text-primary-foreground" : index === step ? "border-primary" : "border-border")}>
                {index < step ? <Check className="size-3" /> : index + 1}
              </span>
              {label}
            </button>
            {index < STEPS.length - 1 ? <span className="h-px w-6 bg-border" /> : null}
          </li>
        ))}
      </ol>

      <motion.div key={step} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.16 }}>
          {step === 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Discovery JSON</CardTitle>
                <CardDescription>The export a source collector produced. Its metadata.schema_name picks the source that translates it; nothing leaves this server.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.preventDefault();
                    const dropped = event.dataTransfer.files?.[0];
                    if (dropped) void readFile(dropped);
                  }}
                  onClick={() => fileInput.current?.click()}
                  className={cn("flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors hover:border-primary/60 hover:bg-accent/40", file ? "border-success/50 bg-success/5" : "border-border")}
                  data-testid="dropzone"
                >
                  <input ref={fileInput} type="file" accept="application/json,.json" className="hidden" onChange={(event) => event.target.files?.[0] && void readFile(event.target.files[0])} data-testid="discovery-file" />
                  {file ? (
                    <>
                      <FileJson className="size-8 text-success" />
                      <div className="text-sm font-medium">{file.name}</div>
                      <div className="text-xs text-muted-foreground">{formatBytes(file.size)} · click to replace</div>
                    </>
                  ) : (
                    <>
                      <Upload className="size-8 text-muted-foreground" />
                      <div className="text-sm font-medium">Drop the discovery JSON here, or click to browse</div>
                      <div className="text-xs text-muted-foreground">Only .json files are accepted</div>
                    </>
                  )}
                </div>
                {fileError ? <Alert variant="error">{fileError}</Alert> : null}
                {file ? (
                  <>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="discovery-summary">
                      {[
                        ["Source", source?.label ?? "unknown"],
                        ["Compute units", file.summary.units],
                        ["Clusters", file.summary.clusters],
                        ["Discovered from", file.summary.origin ?? "—"],
                      ].map(([label, value]) => (
                        <div key={String(label)} className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
                          <div className="truncate text-sm font-semibold" title={String(value)}>{String(value)}</div>
                        </div>
                      ))}
                    </div>
                    <SourceStatus file={file} source={source} sources={sources} loading={metaLoading} error={metaError} />
                  </>
                ) : null}
              </CardContent>
            </Card>
          ) : null}

          {step === 1 ? (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1.5">
                      <CardTitle>Target</CardTitle>
                      <CardDescription>The platform the Terraform root module is rendered for. Targets come from the registry: built in or installed as plugins.</CardDescription>
                    </div>
                    <TierLegend />
                  </div>
                </CardHeader>
                <CardContent>
                  {metaError ? (
                    <Alert variant="error" title="Could not load the target registry" testId="targets-error">
                      {metaError}
                    </Alert>
                  ) : !registryReady ? (
                    <div className="grid gap-2 sm:grid-cols-2" data-testid="targets-loading">
                      {Array.from({ length: 4 }).map((_, index) => (
                        <Skeleton key={index} className="h-[72px]" />
                      ))}
                    </div>
                  ) : targets.length === 0 ? (
                    <Alert variant="warning" testId="targets-empty">
                      No targets are registered on this server. Install a target plugin or check the server log.
                    </Alert>
                  ) : (
                    <div className="grid gap-2 sm:grid-cols-2" data-testid="target-cards">
                      {targets.map((item) => {
                        const selected = options.cloud === item.name;
                        return (
                          <button
                            key={item.name}
                            type="button"
                            onClick={() => { update("cloud", item.name); setConnectionId(""); }}
                            className={cn("flex items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent/50", selected ? "border-primary bg-primary/5 ring-1 ring-primary/40" : "border-border")}
                            aria-pressed={selected}
                            data-testid={`cloud-${item.name}`}
                            data-tier={item.tier}
                          >
                            <span className={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border", selected ? "border-primary bg-primary" : "border-border")}>
                              {selected ? <Check className="size-3 text-primary-foreground" /> : null}
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                <span className="text-sm font-medium">{item.label}</span>
                                <TierBadge tier={item.tier} focusable={false} />
                              </span>
                              <span className="mt-0.5 block text-xs text-muted-foreground">{item.blurb}</span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Identity and tags</CardTitle>
                  <CardDescription>Environment and Owner become tags on every generated resource.</CardDescription>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-2">
                  <Field label="Run name" htmlFor="run-name" hint="Optional, shown in lists.">
                    <Input id="run-name" value={name} onChange={(event) => setName(event.target.value)} data-testid="run-name" />
                  </Field>
                  <Field label="Tags" htmlFor="run-tags" hint="Press Enter to add.">
                    <div className="flex flex-wrap items-center gap-1 rounded-md border border-input bg-card px-2 py-1">
                      {tags.map((tag) => (
                        <Badge key={tag} variant="secondary" className="gap-1">
                          {tag}
                          <button type="button" onClick={() => setTags(tags.filter((item) => item !== tag))} aria-label={`Remove ${tag}`}>
                            <X className="size-3" />
                          </button>
                        </Badge>
                      ))}
                      <input id="run-tags" value={tagInput} onChange={(event) => setTagInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === ",") { event.preventDefault(); addTag(tagInput); } }} onBlur={() => tagInput && addTag(tagInput)} className="h-6 min-w-[80px] flex-1 bg-transparent text-sm outline-none" data-testid="run-tags" />
                    </div>
                  </Field>
                  <Field label="Environment" htmlFor="environment">
                    <Input id="environment" value={options.environment} onChange={(event) => update("environment", event.target.value)} required data-testid="environment" />
                  </Field>
                  <Field label="Owner" htmlFor="owner">
                    <Input id="owner" value={options.owner} onChange={(event) => update("owner", event.target.value)} placeholder="team or person" required data-testid="owner" />
                  </Field>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Generation and checks</CardTitle>
                  <CardDescription>Deterministic generation needs no model. Validation runs terraform, tflint and the OPA security and compliance policies.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Generation mode" htmlFor="mode">
                      <SimpleSelect id="mode" value={options.mode ?? "default"} onValueChange={(value) => update("mode", value === "default" ? null : value)} options={[{ value: "default", label: "Platform default" }, ...(meta?.modes ?? ["deterministic", "llm", "hybrid"]).map((item) => ({ value: item, label: item }))]} />
                    </Field>
                    {options.mode && options.mode !== "deterministic" ? (
                      <Field label="LLM provider" htmlFor="llm-provider">
                        <SimpleSelect id="llm-provider" value={options.llm_provider ?? ""} onValueChange={(value) => update("llm_provider", value)} placeholder="Choose a provider" options={["anthropic", "openai", "google"].map((item) => ({ value: item, label: item }))} />
                      </Field>
                    ) : null}
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <ToggleRow label="Validate with terraform and tflint" hint={target && !target.tflint ? "Recommended. tflint has no ruleset for this target; terraform validate still runs." : "Recommended. Needs the binaries and provider downloads."} checked={!options.skip_validation} onCheckedChange={(value) => update("skip_validation", !value)} testId="toggle-validation" />
                    <ToggleRow label="Security and compliance policies" hint="OPA policies: CIS, SOC 2 and HIPAA controls." checked={!options.skip_opa} onCheckedChange={(value) => update("skip_opa", !value)} testId="toggle-opa" />
                    <ToggleRow label="AI review notes" hint="Model-written summary. Uses the configured LLM." checked={options.llm_review_notes} onCheckedChange={(value) => update("llm_review_notes", value)} testId="toggle-ai-notes" />
                    <ToggleRow label="Terraform registry docs (MCP)" hint="Only useful for llm or hybrid generation." checked={!options.no_mcp} onCheckedChange={(value) => update("no_mcp", !value)} testId="toggle-mcp" />
                    <ToggleRow label="Dry run" hint="Generate and validate without writing files." checked={options.dry_run} onCheckedChange={(value) => update("dry_run", value)} testId="toggle-dry-run" />
                  </div>
                  <div>
                    <div className="mb-1.5 text-sm font-medium">Pause for review</div>
                    <div className="flex flex-wrap gap-4">
                      {Object.entries(meta?.pause_points ?? { review_cim: "hcl_generator", approve_output: "reporter" }).map(([point, before]) => (
                        <div key={point} className="flex items-center gap-2 text-sm">
                          <Checkbox id={`pause-${point}`} checked={effectivePauses.includes(point)} onCheckedChange={(checked) => setPausePoints(checked ? [...effectivePauses, point] : effectivePauses.filter((item) => item !== point))} data-testid={`pause-${point}`} />
                          <label htmlFor={`pause-${point}`} className="cursor-pointer">
                            {point.replace("_", " ")} <span className="text-xs text-muted-foreground">before {before}</span>
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          ) : null}

          {step === 2 ? (
            <Card>
              <CardHeader>
                <CardTitle>Connection</CardTitle>
                <CardDescription>
                  {connectionProvider
                    ? `Optional now; required later to plan and apply. Only connections for ${targetLabel} are listed.`
                    : `${targetLabel} has no connection provider: runs generate and validate only.`}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <button type="button" onClick={() => setConnectionId("")} className={cn("flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent/50", connectionId === "" ? "border-primary bg-primary/5" : "border-border")} data-testid="connection-none">
                  <span className={cn("flex size-4 items-center justify-center rounded-full border", connectionId === "" ? "border-primary bg-primary" : "border-border")}>{connectionId === "" ? <Check className="size-3 text-primary-foreground" /> : null}</span>
                  <span>
                    <span className="block text-sm font-medium">No connection yet</span>
                    <span className="block text-xs text-muted-foreground">Generate and validate only. Attach a connection from the run page when you are ready to deploy.</span>
                  </span>
                </button>
                {matchingConnections.map((connection) => (
                  <button key={connection.id} type="button" onClick={() => setConnectionId(connection.id)} className={cn("flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent/50", connectionId === connection.id ? "border-primary bg-primary/5" : "border-border")} data-testid={`connection-${connection.id}`}>
                    <span className={cn("flex size-4 items-center justify-center rounded-full border", connectionId === connection.id ? "border-primary bg-primary" : "border-border")}>{connectionId === connection.id ? <Check className="size-3 text-primary-foreground" /> : null}</span>
                    <Cable className="size-4 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{connection.name}</span>
                      <span className="block text-xs text-muted-foreground">{connection.method_label ?? connection.auth_method.replace(/_/g, " ")}</span>
                    </span>
                    <StatusBadge status={connection.status} />
                  </button>
                ))}
                {connectionProvider && matchingConnections.length === 0 ? <div className="pt-1 text-xs text-muted-foreground">No {targetLabel} connections exist. An administrator can add one under Connections.</div> : null}
              </CardContent>
            </Card>
          ) : null}

          {step === 3 && file ? (
            <Card>
              <CardHeader>
                <CardTitle>Review</CardTitle>
                <CardDescription>Everything below is recorded with the run and in the audit log.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {error ? <Alert variant="error">{error}</Alert> : null}
                <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 text-sm" data-testid="review-summary">
                  {[
                    ["Source", `${source?.label ?? "unknown source"} · ${file.name} · ${pluralize(file.summary.units, "compute unit")}${file.summary.origin ? ` · ${file.summary.origin}` : ""}`],
                    ["Target", `${targetLabel} · ${options.environment} · ${options.owner}`],
                    ["Name", name || "—"],
                    ["Tags", tags.join(", ") || "—"],
                    ["Generation", `${options.mode ?? "platform default"}${options.llm_provider ? ` via ${options.llm_provider}` : ""}`],
                    ["Checks", [!options.skip_validation && "terraform/tflint", !options.skip_opa && "OPA policies", options.llm_review_notes && "AI notes", options.dry_run && "dry run"].filter(Boolean).join(", ") || "none"],
                    ["Pauses", effectivePauses.length ? effectivePauses.map((item) => item.replace("_", " ")).join(", ") : "none (runs straight through)"],
                    ["Connection", matchingConnections.find((item) => item.id === connectionId)?.name ?? "none"],
                  ].map(([label, value]) => (
                    <React.Fragment key={label}>
                      <dt className="text-muted-foreground">{label}</dt>
                      <dd className="font-medium">{value}</dd>
                    </React.Fragment>
                  ))}
                </dl>
                <ToggleRow label="Start immediately" hint="Otherwise the run is created and can be started from its page." checked={startNow} onCheckedChange={setStartNow} testId="toggle-start-now" />
              </CardContent>
            </Card>
          ) : null}
      </motion.div>

      <div className="mt-5 flex items-center justify-between">
        <Button variant="ghost" onClick={() => (step === 0 ? navigate("/runs") : setStep(step - 1))}>
          <ArrowLeft /> {step === 0 ? "Cancel" : "Back"}
        </Button>
        {step < STEPS.length - 1 ? (
          <Button onClick={() => setStep(step + 1)} disabled={!stepValid} data-testid="wizard-next">
            Continue <ArrowRight />
          </Button>
        ) : (
          <Button onClick={() => void submit()} loading={busy} disabled={!file} data-testid="start-run">
            <Rocket /> {startNow ? "Start run" : "Create run"}
          </Button>
        )}
      </div>
    </div>
  );
}

/** Which registered source claims the uploaded file, or why none does. */
function SourceStatus({ file, source, sources, loading, error }: { file: LoadedFile; source: SourceSpec | undefined; sources: SourceSpec[]; loading: boolean; error: string | null }) {
  if (source) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-success/40 bg-success/5 px-3 py-2 text-sm" data-testid="source-detected" data-source={source.name}>
        <Check className="size-4 text-success" aria-hidden />
        <span>
          <span className="font-medium">{source.label}</span> accepts this file
          <span className="text-muted-foreground"> · schema {file.summary.schema}</span>
        </span>
        <TierBadge tier={source.tier} />
        {file.summary.units === 0 ? <span className="basis-full text-xs text-warning">No compute units were found under {UNIT_KEYS.join(", ")}; the run may produce nothing.</span> : null}
      </div>
    );
  }
  if (error) {
    return (
      <Alert variant="error" title="Could not load the source registry" testId="source-registry-error">
        {error}
      </Alert>
    );
  }
  if (loading) {
    return (
      <div className="text-xs text-muted-foreground" data-testid="source-checking">
        Checking which source accepts schema {file.summary.schema ?? "(none)"}…
      </div>
    );
  }
  if (!file.summary.schema) {
    return (
      <Alert variant="error" title="The file declares no metadata.schema_name" testId="source-unknown">
        A source is selected by the schema name its collector writes into metadata.schema_name. {describeSources(sources)}
      </Alert>
    );
  }
  return (
    <Alert variant="error" title={`No registered source accepts schema "${file.summary.schema}"`} testId="source-unknown">
      Install the source plugin for this collector or export the inventory with a supported collector. {describeSources(sources)}
    </Alert>
  );
}

function TierLegend() {
  return (
    <Hint
      content={
        <ul className="space-y-1">
          {(Object.keys(TIER_COPY) as SupportTier[]).map((tier) => (
            <li key={tier}>
              <span className="font-medium">{TIER_COPY[tier].label}</span>: {TIER_COPY[tier].text}
            </li>
          ))}
        </ul>
      }
    >
      <button type="button" className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground" aria-label="What the support tiers mean" data-testid="tier-legend">
        <CircleHelp className="size-4" />
      </button>
    </Hint>
  );
}
