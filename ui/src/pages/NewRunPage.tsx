import * as React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { motion } from "motion/react";
import { ArrowLeft, ArrowRight, Cable, Check, FileJson, Rocket, Upload, X } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { SimpleSelect } from "@/components/ui/select";
import { ToggleRow, Checkbox } from "@/components/ui/switch";
import { Alert, PageHeader } from "@/components/ui/misc";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/lib/format";
import type { Connection, RunOptions } from "@/types";

const STEPS = ["Discovery", "Target", "Connection", "Review"] as const;

const CLOUDS: Record<string, { label: string; blurb: string }> = {
  aws: { label: "Amazon Web Services", blurb: "EC2, EBS, VPC, security groups, placement groups" },
  azure: { label: "Microsoft Azure", blurb: "Virtual machines, managed disks, VNets, NSGs, availability sets" },
  gcp: { label: "Google Cloud", blurb: "Compute Engine, persistent disks, VPC, firewall rules, placement policies" },
  openstack: { label: "OpenStack", blurb: "Nova, Cinder, Neutron networks, security groups, server groups" },
  proxmox: { label: "Proxmox VE", blurb: "KVM virtual machines, VLAN-tagged bridges, disks on a datastore, HA groups and anti-affinity" },
};

interface Summary {
  vms: number;
  vcenter: string;
  schema: string;
  switches: number;
  clusters: number;
}

function summarize(payload: unknown): Summary {
  const data = (payload ?? {}) as Record<string, unknown>;
  const metadata = (data.metadata ?? {}) as Record<string, unknown>;
  const vms = (Array.isArray(data.virtual_machines) ? data.virtual_machines : Array.isArray(data.vms) ? data.vms : []) as Record<string, unknown>[];
  const clusters = new Set<string>();
  const switches = new Set<string>();
  const vcenters = new Set<string>();
  for (const vm of vms) {
    if (typeof vm.cluster === "string" && vm.cluster) clusters.add(vm.cluster);
    if (typeof vm.source_vcenter === "string" && vm.source_vcenter) vcenters.add(vm.source_vcenter);
    for (const nic of (Array.isArray(vm.networks) ? vm.networks : []) as Record<string, unknown>[]) {
      if (typeof nic.distributed_switch === "string" && nic.distributed_switch) switches.add(nic.distributed_switch);
    }
  }
  const queried = Array.isArray(metadata.vcenters_queried) ? (metadata.vcenters_queried as unknown[]).map(String) : [];
  const vcenter = queried[0] ?? [...vcenters][0] ?? String(metadata.source_vcenter ?? "unknown");
  return {
    vms: vms.length,
    vcenter: queried.length > 1 ? `${vcenter} +${queried.length - 1}` : vcenter,
    schema: String(metadata.schema_name ?? "unknown"),
    switches: switches.size,
    clusters: clusters.size,
  };
}

export function NewRunPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { toast } = useToast();
  const meta = useAsync(() => api.meta(), []);
  const connections = useAsync(() => api.listConnections().catch(() => [] as Connection[]), []);

  const [step, setStep] = React.useState(0);
  const [file, setFile] = React.useState<{ name: string; size: number; payload: unknown; summary: Summary } | null>(null);
  const [fileError, setFileError] = React.useState<string | null>(null);
  const [name, setName] = React.useState("");
  const [tags, setTags] = React.useState<string[]>([]);
  const [tagInput, setTagInput] = React.useState("");
  const [connectionId, setConnectionId] = React.useState<string>(params.get("connection") ?? "");
  const [startNow, setStartNow] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [options, setOptions] = React.useState<RunOptions>({
    cloud: params.get("cloud") ?? "aws",
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

  const defaultPauses = meta.data?.default_pause_points ?? ["review_cim", "approve_output"];
  const effectivePauses = pausePoints ?? defaultPauses;
  const update = <K extends keyof RunOptions>(key: K, value: RunOptions[K]) => setOptions((current) => ({ ...current, [key]: value }));

  async function readFile(selected: File) {
    setFileError(null);
    try {
      const text = await selected.text();
      const payload = JSON.parse(text) as unknown;
      if (!payload || typeof payload !== "object") throw new Error("The file is not a JSON object.");
      const summary = summarize(payload);
      if (summary.vms === 0) throw new Error("No virtual machines found. Expected a vSphere discovery JSON with a virtual_machines list.");
      setFile({ name: selected.name, size: selected.size, payload, summary });
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

  const matchingConnections = (connections.data ?? []).filter((item) => item.provider === options.cloud);

  const stepValid = [
    file !== null,
    options.environment.trim().length > 0 && options.owner.trim().length > 0 && (options.mode === null || options.mode === "deterministic" || !!options.llm_provider),
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
      <PageHeader title="New migration run" description="Four short steps: upload discovery, choose the target, pick a cloud connection, review and start." />

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
                <CardDescription>Output of the vSphere discovery playbook (schema vmware-discovery-stage1). Nothing leaves this server.</CardDescription>
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
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="discovery-summary">
                    {[
                      ["Virtual machines", file.summary.vms],
                      ["Switches", file.summary.switches],
                      ["Clusters", file.summary.clusters],
                      ["vCenter", file.summary.vcenter],
                    ].map(([label, value]) => (
                      <div key={String(label)} className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
                        <div className="truncate text-sm font-semibold">{String(value)}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : null}

          {step === 1 ? (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>Target cloud</CardTitle>
                  <CardDescription>The provider the Terraform root module is rendered for.</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {(meta.data?.clouds ?? Object.keys(CLOUDS)).map((cloud) => (
                      <button
                        key={cloud}
                        type="button"
                        onClick={() => { update("cloud", cloud); setConnectionId(""); }}
                        className={cn("flex items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent/50", options.cloud === cloud ? "border-primary bg-primary/5 ring-1 ring-primary/40" : "border-border")}
                        data-testid={`cloud-${cloud}`}
                      >
                        <span className={cn("mt-0.5 flex size-4 items-center justify-center rounded-full border", options.cloud === cloud ? "border-primary bg-primary" : "border-border")}>
                          {options.cloud === cloud ? <Check className="size-3 text-primary-foreground" /> : null}
                        </span>
                        <span>
                          <span className="block text-sm font-medium">{CLOUDS[cloud]?.label ?? cloud.toUpperCase()}</span>
                          <span className="block text-xs text-muted-foreground">{CLOUDS[cloud]?.blurb}</span>
                        </span>
                      </button>
                    ))}
                  </div>
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
                      <SimpleSelect id="mode" value={options.mode ?? "default"} onValueChange={(value) => update("mode", value === "default" ? null : value)} options={[{ value: "default", label: "Platform default" }, ...(meta.data?.modes ?? ["deterministic", "llm", "hybrid"]).map((item) => ({ value: item, label: item }))]} />
                    </Field>
                    {options.mode && options.mode !== "deterministic" ? (
                      <Field label="LLM provider" htmlFor="llm-provider">
                        <SimpleSelect id="llm-provider" value={options.llm_provider ?? ""} onValueChange={(value) => update("llm_provider", value)} placeholder="Choose a provider" options={["anthropic", "openai", "google"].map((item) => ({ value: item, label: item }))} />
                      </Field>
                    ) : null}
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <ToggleRow label="Validate with terraform and tflint" hint="Recommended. Needs the binaries and provider downloads." checked={!options.skip_validation} onCheckedChange={(value) => update("skip_validation", !value)} testId="toggle-validation" />
                    <ToggleRow label="Security and compliance policies" hint="OPA policies: CIS, SOC 2 and HIPAA controls." checked={!options.skip_opa} onCheckedChange={(value) => update("skip_opa", !value)} testId="toggle-opa" />
                    <ToggleRow label="AI review notes" hint="Model-written summary. Uses the configured LLM." checked={options.llm_review_notes} onCheckedChange={(value) => update("llm_review_notes", value)} testId="toggle-ai-notes" />
                    <ToggleRow label="Terraform registry docs (MCP)" hint="Only useful for llm or hybrid generation." checked={!options.no_mcp} onCheckedChange={(value) => update("no_mcp", !value)} testId="toggle-mcp" />
                    <ToggleRow label="Dry run" hint="Generate and validate without writing files." checked={options.dry_run} onCheckedChange={(value) => update("dry_run", value)} testId="toggle-dry-run" />
                  </div>
                  <div>
                    <div className="mb-1.5 text-sm font-medium">Pause for review</div>
                    <div className="flex flex-wrap gap-4">
                      {Object.entries(meta.data?.pause_points ?? { review_cim: "hcl_generator", approve_output: "reporter" }).map(([point, before]) => (
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
                <CardTitle>Cloud connection</CardTitle>
                <CardDescription>Optional now; required later to plan and apply. Only connections for {options.cloud.toUpperCase()} are listed.</CardDescription>
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
                      <span className="block text-xs text-muted-foreground">{connection.auth_method.replace(/_/g, " ")}</span>
                    </span>
                    <StatusBadge status={connection.status} />
                  </button>
                ))}
                {matchingConnections.length === 0 ? <div className="pt-1 text-xs text-muted-foreground">No {options.cloud.toUpperCase()} connections exist. An administrator can add one under Connections.</div> : null}
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
                <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 text-sm">
                  {[
                    ["Discovery", `${file.name} · ${file.summary.vms} VMs · ${file.summary.vcenter}`],
                    ["Name", name || "—"],
                    ["Tags", tags.join(", ") || "—"],
                    ["Target", `${CLOUDS[options.cloud]?.label ?? options.cloud} · ${options.environment} · ${options.owner}`],
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
