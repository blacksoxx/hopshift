import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Cable, Check, ChevronDown, Cloud, Copy, Download, FileJson, Pencil, Play, Plus, RefreshCw, RotateCcw, StopCircle, Tag, Trash2, User, X } from "lucide-react";
import { TERMINAL_STATUSES, api } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Hint } from "@/components/ui/tooltip";
import { Alert, Pill } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Connection, Meta, RunRecord } from "@/types";

export interface RunHeaderProps {
  run: RunRecord;
  meta: Meta | null;
  connections: Connection[];
  canOperate: boolean;
  executing: boolean;
  onChange: (run: RunRecord) => void;
  onRefresh: () => Promise<void>;
}

const NONE = "__none__";

export function RunHeader({ run, meta, connections, canOperate, executing, onChange, onRefresh }: RunHeaderProps) {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [busy, setBusy] = React.useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);

  const paused = run.status === "paused" && !executing;
  const terminal = TERMINAL_STATUSES.has(run.status) && !executing;
  const cancellable = (run.status === "running" || run.status === "paused" || run.status === "created") && !run.cancel_requested;
  const nodes = meta?.nodes ?? [];
  const sameCloud = connections.filter((connection) => connection.provider === run.cloud);
  const current = connections.find((connection) => connection.id === run.connection_id) ?? null;

  async function mutate(key: string, action: () => Promise<unknown>, success: { title: string; description?: string; variant?: "success" | "warning" | "default" }, after: "refresh" | "none" = "refresh") {
    setBusy(key);
    try {
      await action();
      toast({ variant: "success", ...success });
      if (after === "refresh") await onRefresh();
    } catch (exc) {
      toast({ title: "Request failed", description: (exc as Error).message, variant: "error" });
    } finally {
      setBusy(null);
    }
  }

  async function patch(body: Parameters<typeof api.updateRun>[1], title: string) {
    setBusy("patch");
    try {
      const updated = await api.updateRun(run.run_id, body);
      onChange(updated);
      toast({ title, variant: "success" });
    } catch (exc) {
      toast({ title: "Could not update the run", description: (exc as Error).message, variant: "error" });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setBusy("delete");
    try {
      await api.deleteRun(run.run_id);
      toast({ title: "Run deleted", description: run.name || run.run_id, variant: "success" });
      navigate("/runs");
    } catch (exc) {
      toast({ title: "Could not delete", description: (exc as Error).message, variant: "error" });
      setBusy(null);
    }
  }

  const approveLabel = run.pause_point === "approve_output" ? "Approve and write output" : run.pause_point === "review_cim" ? "Approve CIM and generate" : "Approve and continue";

  return (
    <div className="mb-5 space-y-3">
      <Link to="/runs" className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
        <ArrowLeft className="size-3.5" /> Runs
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1 basis-80 space-y-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <RunName run={run} editable={canOperate} saving={busy === "patch"} onSave={(name) => patch({ name }, name ? "Run renamed" : "Run name cleared")} />
            <StatusBadge status={executing ? "running" : run.status} />
            {run.cancel_requested && executing ? <span className="text-xs text-warning">cancelling…</span> : null}
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
            <RunId id={run.run_id} />
            <span className="inline-flex items-center gap-1 uppercase">
              <Cloud className="size-3.5" /> {run.cloud}
            </span>
            <span>{run.mode}</span>
            <span className="inline-flex items-center gap-1">
              <FileJson className="size-3.5" /> {run.input_filename}
            </span>
            <Hint content={formatDateTime(run.created_at)}>
              <span className="cursor-default whitespace-nowrap">created {relativeTime(run.created_at)}</span>
            </Hint>
            {run.created_by ? (
              <span className="inline-flex items-center gap-1">
                <User className="size-3.5" /> {run.created_by}
              </span>
            ) : null}
            <ConnectionChip run={run} current={current} options={sameCloud} enabled={canOperate && meta?.features.connections !== false} busy={busy === "patch"} onSelect={(id) => (id ? patch({ connection_id: id }, "Connection set") : patch({ clear_connection: true }, "Connection cleared"))} />
          </div>

          <TagsEditor tags={run.tags ?? []} editable={canOperate} saving={busy === "patch"} onSave={(tags) => patch({ tags }, "Tags updated")} />
        </div>

        <div className="flex flex-wrap items-center gap-2" data-testid="run-actions">
          {canOperate && paused ? (
            <Button onClick={() => void mutate("approve", () => api.resume(run.run_id), { title: "Approved", description: `Resumed from ${run.pause_point ?? run.paused_before ?? "the pause point"}.` })} loading={busy === "approve"} data-testid="approve">
              <Play /> {approveLabel}
            </Button>
          ) : null}
          {canOperate && cancellable ? (
            <Button variant="outline" onClick={() => void mutate("cancel", () => api.cancel(run.run_id), { title: "Cancellation requested", description: "The run stops after the current step.", variant: "warning" })} loading={busy === "cancel"} data-testid="cancel-run">
              <StopCircle /> Cancel
            </Button>
          ) : null}
          {canOperate && terminal && nodes.length > 0 ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" loading={busy === "rerun"} data-testid="rerun">
                  <RotateCcw /> Re-run from… <ChevronDown className="opacity-60" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-[14rem]">
                <DropdownMenuLabel>Replay the pipeline from</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {nodes.map((node, index) => (
                  <DropdownMenuItem key={node} onSelect={() => void mutate("rerun", () => api.rerun(run.run_id, node), { title: `Re-running from ${node}`, description: "Earlier results are kept from the checkpoint." })} data-testid={`rerun-${node}`}>
                    <span className="w-4 text-right font-mono text-[11px] text-muted-foreground">{index + 1}</span>
                    <span className="font-mono text-xs">{node}</span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
          {terminal ? (
            <Button variant="outline" asChild>
              <a href={api.artifactsArchiveUrl(run.run_id)} download data-testid="download-artifacts">
                <Download /> Artifacts
              </a>
            </Button>
          ) : null}
          <Hint content="Refresh (r)">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Refresh"
              data-testid="refresh"
              onClick={() => {
                setRefreshing(true);
                void onRefresh().finally(() => setRefreshing(false));
              }}
            >
              <RefreshCw className={cn(refreshing && "animate-spin")} />
            </Button>
          </Hint>
          {canOperate ? (
            <Hint content={executing ? "Cancel the run before deleting it" : "Delete run"}>
              <span>
                <Button variant="ghost" size="icon" aria-label="Delete run" className="text-muted-foreground hover:text-destructive" disabled={executing} onClick={() => setConfirmDelete(true)} data-testid="delete-run">
                  <Trash2 />
                </Button>
              </span>
            </Hint>
          ) : null}
        </div>
      </div>

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent size="sm">
          <DialogHeader>
            <DialogTitle>Delete this run?</DialogTitle>
            <DialogDescription>{run.name || run.run_id} and all of its artifacts, events and Terraform state will be removed. This cannot be undone.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(false)}>
              Keep it
            </Button>
            <Button variant="destructive" onClick={() => void remove()} loading={busy === "delete"} data-testid="confirm-delete">
              Delete run
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function RunName({ run, editable, saving, onSave }: { run: RunRecord; editable: boolean; saving: boolean; onSave: (name: string | null) => void }) {
  const [editing, setEditing] = React.useState(false);
  const [value, setValue] = React.useState(run.name ?? "");
  React.useEffect(() => setValue(run.name ?? ""), [run.name]);

  function commit() {
    const next = value.trim();
    setEditing(false);
    if (next === (run.name ?? "")) return;
    onSave(next || null);
  }

  if (editing) {
    return (
      <form
        className="flex items-center gap-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          commit();
        }}
      >
        <Input
          autoFocus
          value={value}
          maxLength={120}
          placeholder="Run name"
          className="h-8 w-72 max-w-full text-base font-semibold"
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setValue(run.name ?? "");
              setEditing(false);
            }
          }}
          data-testid="run-name-input"
        />
        <Button type="submit" size="icon-sm" variant="ghost" aria-label="Save name" loading={saving}>
          <Check />
        </Button>
      </form>
    );
  }
  return (
    <div className="group/name flex min-w-0 items-center gap-1.5">
      <h1 className={cn("truncate text-xl font-semibold tracking-tight", !run.name && "text-muted-foreground")} data-testid="run-name">
        {run.name || "Untitled run"}
      </h1>
      {editable ? (
        <Button variant="ghost" size="icon-sm" aria-label="Rename run" className="opacity-0 transition-opacity group-hover/name:opacity-100 focus-visible:opacity-100" onClick={() => setEditing(true)} data-testid="rename">
          <Pencil className="size-3.5" />
        </Button>
      ) : null}
    </div>
  );
}

function RunId({ id }: { id: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 rounded-md focus-visible:outline-none"
      onClick={() => {
        void navigator.clipboard?.writeText(id);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}
      title="Copy run id"
    >
      <Pill>{id}</Pill>
      {copied ? <Check className="size-3 text-success" /> : <Copy className="size-3 opacity-60" />}
    </button>
  );
}

function ConnectionChip({ run, current, options, enabled, busy, onSelect }: { run: RunRecord; current: Connection | null; options: Connection[]; enabled: boolean; busy: boolean; onSelect: (id: string | null) => void }) {
  if (!enabled) {
    return (
      <span className="inline-flex items-center gap-1">
        <Cable className="size-3.5" /> {current ? current.name : run.connection_id ? run.connection_id : "no connection"}
      </span>
    );
  }
  return (
    <Select value={run.connection_id ?? NONE} onValueChange={(value) => onSelect(value === NONE ? null : value)} disabled={busy}>
      <SelectTrigger className="h-6 w-auto gap-1 rounded-full border-border bg-muted/60 px-2 py-0 text-[11.5px] shadow-none focus:ring-0" aria-label="Connection" data-testid="run-connection">
        <Cable className="size-3 shrink-0" />
        <SelectValue placeholder="no connection">{current ? current.name : run.connection_id ? run.connection_id : "no connection"}</SelectValue>
      </SelectTrigger>
      <SelectContent align="start">
        <SelectItem value={NONE}>No connection</SelectItem>
        {options.map((connection) => (
          <SelectItem key={connection.id} value={connection.id}>
            {connection.name} <span className="text-muted-foreground">· {connection.auth_method}</span>
          </SelectItem>
        ))}
        {options.length === 0 ? <div className="px-2 py-1.5 text-xs text-muted-foreground">No {run.cloud.toUpperCase()} connections yet.</div> : null}
      </SelectContent>
    </Select>
  );
}

function TagsEditor({ tags, editable, saving, onSave }: { tags: string[]; editable: boolean; saving: boolean; onSave: (tags: string[]) => void }) {
  const [adding, setAdding] = React.useState(false);
  const [draft, setDraft] = React.useState("");

  function add() {
    const value = draft.trim();
    setDraft("");
    setAdding(false);
    if (!value || tags.includes(value)) return;
    onSave([...tags, value]);
  }

  if (tags.length === 0 && !editable) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="tags">
      <Tag className="size-3.5 text-muted-foreground" />
      {tags.map((tag) => (
        <Badge key={tag} variant="outline" className="gap-1 pr-1">
          {tag}
          {editable ? (
            <button type="button" aria-label={`Remove tag ${tag}`} className="rounded-sm p-0.5 hover:bg-accent hover:text-foreground" disabled={saving} onClick={() => onSave(tags.filter((item) => item !== tag))}>
              <X className="size-3" />
            </button>
          ) : null}
        </Badge>
      ))}
      {editable ? (
        adding ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              add();
            }}
          >
            <Input
              autoFocus
              value={draft}
              placeholder="tag"
              className="h-6 w-28 px-2 text-xs"
              onChange={(event) => setDraft(event.target.value)}
              onBlur={add}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setDraft("");
                  setAdding(false);
                }
              }}
              data-testid="tag-input"
            />
          </form>
        ) : (
          <button type="button" className="inline-flex h-6 items-center gap-0.5 rounded-md border border-dashed border-border px-1.5 text-[11.5px] text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground" onClick={() => setAdding(true)} disabled={saving} data-testid="add-tag">
            <Plus className="size-3" /> tag
          </button>
        )
      ) : null}
    </div>
  );
}

const PAUSE_COPY: Record<string, string> = {
  review_cim: "Review or edit the canonical infrastructure model, then approve to generate Terraform.",
  approve_output: "The generated files have been validated. Approve to write them into the run folder.",
};

export function RunBanners({ run, executing }: { run: RunRecord; executing: boolean }) {
  const pausePoint = run.pause_point ?? run.paused_before;
  return (
    <div className="mb-5 space-y-2 empty:hidden">
      {run.status === "paused" && !executing ? (
        <Alert variant="warning" testId="paused-banner" title={<span className="inline-flex flex-wrap items-center gap-2">Paused at <Pill className="bg-warning/15 text-foreground">{pausePoint}</Pill></span>}>
          {(pausePoint && PAUSE_COPY[pausePoint]) ?? `The pipeline stopped before ${run.paused_before ?? "the next node"} and waits for an operator.`}
        </Alert>
      ) : null}
      {run.error ? (
        <Alert variant="error" title="The run failed" testId="error-banner">
          <pre className="font-mono text-xs">{run.error}</pre>
        </Alert>
      ) : null}
      {run.status === "cancelled" ? (
        <Alert variant="info" title="This run was cancelled" testId="cancelled-banner">
          Re-run from a node to continue from its last checkpoint.
        </Alert>
      ) : run.cancel_requested && executing ? (
        <Alert variant="warning" title="Cancellation requested">
          The run stops after the current node finishes.
        </Alert>
      ) : null}
    </div>
  );
}
