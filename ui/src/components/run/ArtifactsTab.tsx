import * as React from "react";
import { Check, ChevronDown, ChevronRight, Copy, Download, File, FileCode, FileJson, FileText, Folder, FolderOpen, GitCompare, Package, X } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { SimpleSelect } from "@/components/ui/select";
import { Alert, EmptyState, Skeleton, Spinner } from "@/components/ui/misc";
import { formatBytes, shortId } from "@/lib/format";
import { cn, downloadText } from "@/lib/utils";
import { CodeView, languageFor } from "./CodeView";
import { UnifiedDiff } from "./UnifiedDiff";
import type { Artifact, DiffFile, RunRecord } from "@/types";

export interface TreeNode {
  name: string;
  path: string;
  children: TreeNode[];
  file: Artifact | null;
}

/** Group a flat artifact list into a directory tree (directories first, then files, both sorted). */
export function buildTree(files: Artifact[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", children: [], file: null };
  for (const file of [...files].sort((a, b) => a.path.localeCompare(b.path))) {
    const parts = file.path.split("/").filter(Boolean);
    let node = root;
    parts.forEach((part, index) => {
      const last = index === parts.length - 1;
      let child = node.children.find((item) => item.name === part && (last ? item.file !== null : item.file === null));
      if (!child) {
        child = { name: part, path: parts.slice(0, index + 1).join("/"), children: [], file: last ? file : null };
        node.children.push(child);
      }
      node = child;
    });
  }
  const sort = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => (a.file === null) === (b.file === null) ? a.name.localeCompare(b.name) : a.file === null ? -1 : 1);
    nodes.forEach((node) => sort(node.children));
  };
  sort(root.children);
  return root.children;
}

function FileIcon({ name, className }: { name: string; className?: string }) {
  const lang = languageFor(name);
  const Icon = lang === "hcl" ? FileCode : lang === "json" ? FileJson : lang === "markdown" ? FileText : File;
  return <Icon className={cn("size-4 shrink-0", className)} />;
}

function Tree({ nodes, selected, onSelect, depth = 0 }: { nodes: TreeNode[]; selected: string | null; onSelect: (path: string) => void; depth?: number }) {
  return (
    <ul className={cn(depth === 0 ? "space-y-0.5" : "mt-0.5 space-y-0.5")}>
      {nodes.map((node) => (
        <TreeItem key={node.path} node={node} selected={selected} onSelect={onSelect} depth={depth} />
      ))}
    </ul>
  );
}

function TreeItem({ node, selected, onSelect, depth }: { node: TreeNode; selected: string | null; onSelect: (path: string) => void; depth: number }) {
  const [open, setOpen] = React.useState(true);
  const indent = { paddingLeft: `${8 + depth * 14}px` };
  if (node.file) {
    const active = node.path === selected;
    return (
      <li>
        <button
          type="button"
          onClick={() => onSelect(node.path)}
          style={indent}
          className={cn("flex w-full items-center gap-2 rounded-md py-1.5 pr-2 text-left text-[13px] transition-colors", active ? "bg-accent text-accent-foreground" : "text-foreground/85 hover:bg-accent/50")}
          data-testid="artifact-item"
          data-path={node.path}
          aria-current={active ? "true" : undefined}
        >
          <FileIcon name={node.name} className={active ? "text-primary" : "text-muted-foreground"} />
          <span className="min-w-0 flex-1 truncate">{node.name}</span>
          <span className="shrink-0 text-[11px] tabular text-muted-foreground">{formatBytes(node.file.size)}</span>
        </button>
      </li>
    );
  }
  return (
    <li>
      <button type="button" onClick={() => setOpen((value) => !value)} style={indent} className="flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-[12.5px] font-medium text-muted-foreground hover:bg-accent/50" aria-expanded={open} data-testid="artifact-dir">
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        {open ? <FolderOpen className="size-4" /> : <Folder className="size-4" />}
        <span className="truncate">{node.name}</span>
        <span className="ml-auto text-[11px] font-normal">{countFiles(node)}</span>
      </button>
      {open ? <Tree nodes={node.children} selected={selected} onSelect={onSelect} depth={depth + 1} /> : null}
    </li>
  );
}

function countFiles(node: TreeNode): number {
  return node.file ? 1 : node.children.reduce((total, child) => total + countFiles(child), 0);
}

const DIFF_VARIANT: Record<DiffFile["status"], "success" | "danger" | "warning" | "muted"> = { added: "success", removed: "danger", modified: "warning", same: "muted" };

export function ArtifactsTab({ run }: { run: RunRecord }) {
  const runId = run.run_id;
  const files = useAsync(() => api.artifacts(runId), [runId, run.status, run.updated_at]);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [compareWith, setCompareWith] = React.useState<string>("");
  const [diffFile, setDiffFile] = React.useState<string | null>(null);

  const tree = React.useMemo(() => buildTree(files.data ?? []), [files.data]);
  const list = files.data ?? [];
  const current = list.find((file) => file.path === selected) ?? null;

  React.useEffect(() => {
    if (list.length === 0) return;
    if (!selected || !list.some((file) => file.path === selected)) {
      const preferred = list.find((file) => file.path.endsWith("main.tf")) ?? list.find((file) => file.path.endsWith(".tf")) ?? list[0];
      setSelected(preferred.path);
    }
  }, [list, selected]);

  const content = useAsync(() => (selected ? api.artifact(runId, selected) : Promise.resolve("")), [runId, selected, run.updated_at]);
  const others = useAsync(() => api.listRuns({ cloud: run.cloud }).then((runs) => runs.filter((item) => item.run_id !== runId && item.status === "succeeded")), [runId, run.cloud]);
  const diff = useAsync(() => (compareWith ? api.diff(runId, compareWith) : Promise.resolve(null)), [runId, compareWith]);

  React.useEffect(() => {
    if (!diff.data) {
      setDiffFile(null);
      return;
    }
    const changed = diff.data.files.find((file) => file.status !== "same") ?? diff.data.files[0] ?? null;
    setDiffFile((value) => (value && diff.data?.files.some((file) => file.path === value) ? value : (changed?.path ?? null)));
  }, [diff.data]);

  async function copy() {
    if (!content.data) return;
    await navigator.clipboard.writeText(content.data);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  if (files.loading && !files.data) {
    return (
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    );
  }
  if (files.error) {
    return <Alert variant="error" title="Could not load artifacts" action={<Button size="sm" variant="outline" onClick={() => void files.reload()}>Retry</Button>}>{files.error}</Alert>;
  }
  if (list.length === 0) {
    return <EmptyState icon={Package} title="No artifacts yet" description={run.status === "paused" ? "Files are written to the run folder once the output is approved." : run.status === "succeeded" ? "This run produced no files." : "Artifacts appear after the pipeline writes its output."} testId="artifacts-empty" />;
  }

  const compareOptions = (others.data ?? []).map((item) => ({ value: item.run_id, label: `${item.name || item.input_filename} · ${shortId(item.run_id)}` }));
  const selectedDiff = diff.data?.files.find((file) => file.path === diffFile) ?? null;

  return (
    <div className="space-y-4" data-testid="artifacts">
      <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="surface flex max-h-[70vh] flex-col overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs text-muted-foreground">
            <span>
              {list.length} file{list.length === 1 ? "" : "s"} · {formatBytes(list.reduce((total, file) => total + file.size, 0))}
            </span>
            <Button variant="ghost" size="sm" className="h-7 px-2" asChild>
              <a href={api.artifactsArchiveUrl(runId)} download>
                <Download /> zip
              </a>
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-2">
            <Tree nodes={tree} selected={selected} onSelect={setSelected} />
          </div>
        </div>

        <div className="surface flex min-h-[320px] flex-col overflow-hidden">
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2">
            {current ? (
              <>
                <FileIcon name={current.path} className="text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate font-mono text-xs" title={current.path} data-testid="artifact-path">
                  {current.path}
                </span>
                <span className="text-xs tabular text-muted-foreground">{formatBytes(current.size)}</span>
                <Button variant="ghost" size="sm" className="h-7" onClick={() => void copy()} disabled={!content.data} data-testid="artifact-copy">
                  {copied ? <Check className="text-success" /> : <Copy />} {copied ? "Copied" : "Copy"}
                </Button>
                <Button variant="ghost" size="sm" className="h-7" onClick={() => content.data !== null && downloadText(current.path.split("/").pop() ?? "artifact.txt", content.data)} disabled={!content.data}>
                  <Download /> Save
                </Button>
              </>
            ) : (
              <span className="text-sm text-muted-foreground">Select a file.</span>
            )}
          </div>
          <div className="relative min-h-0 flex-1">
            {content.loading && !content.data ? (
              <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
                <Spinner /> Loading…
              </div>
            ) : content.error ? (
              <div className="p-4">
                <Alert variant="error">{content.error}</Alert>
              </div>
            ) : (
              <CodeView code={content.data ?? ""} lang={current ? languageFor(current.path) : "text"} className="max-h-[70vh]" testId="artifact-content" />
            )}
          </div>
        </div>
      </div>

      <div className="surface overflow-hidden" data-testid="artifact-compare">
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <GitCompare className="size-4 text-muted-foreground" /> Compare with…
          </div>
          <SimpleSelect value={compareWith} onValueChange={setCompareWith} options={compareOptions} placeholder={others.loading ? "Loading runs…" : compareOptions.length === 0 ? `No other succeeded ${run.cloud.toUpperCase()} runs` : "Pick a run"} className="h-8 w-72 text-xs" disabled={compareOptions.length === 0} testId="compare-select" />
          {compareWith ? (
            <Button variant="ghost" size="sm" className="h-8" onClick={() => setCompareWith("")}>
              <X /> Clear
            </Button>
          ) : null}
          {diff.data ? (
            <div className="ml-auto flex flex-wrap items-center gap-1.5 text-xs">
              {(["added", "modified", "removed", "same"] as const).map((status) => (
                <Badge key={status} variant={DIFF_VARIANT[status]} className="capitalize">
                  {diff.data?.summary[status] ?? 0} {status}
                </Badge>
              ))}
            </div>
          ) : null}
        </div>
        {!compareWith ? (
          <div className="px-4 py-6 text-sm text-muted-foreground">Pick another {run.cloud.toUpperCase()} run to see how the generated Terraform differs (other on the left, this run on the right).</div>
        ) : diff.loading && !diff.data ? (
          <div className="flex items-center gap-2 px-4 py-6 text-sm text-muted-foreground">
            <Spinner /> Computing diff…
          </div>
        ) : diff.error ? (
          <div className="p-4">
            <Alert variant="error">{diff.error}</Alert>
          </div>
        ) : diff.data ? (
          <div className="grid lg:grid-cols-[280px_minmax(0,1fr)]">
            <ul className="max-h-[60vh] overflow-auto border-b border-border p-2 lg:border-b-0 lg:border-r" data-testid="diff-files">
              {diff.data.files.map((file) => (
                <li key={file.path}>
                  <button type="button" onClick={() => setDiffFile(file.path)} className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors", file.path === diffFile ? "bg-accent text-accent-foreground" : "hover:bg-accent/50", file.status === "same" && "text-muted-foreground")} data-testid="diff-file" data-status={file.status}>
                    <span className="min-w-0 flex-1 truncate font-mono text-xs">{file.path}</span>
                    <Badge variant={DIFF_VARIANT[file.status]} className="text-[10.5px]">
                      {file.status}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
            <div className="max-h-[60vh] overflow-auto">
              {selectedDiff ? (
                selectedDiff.status === "same" ? (
                  <div className="px-4 py-8 text-center text-sm text-muted-foreground">Identical in both runs.</div>
                ) : (
                  <UnifiedDiff diff={selectedDiff.diff} testId="diff-view" />
                )
              ) : (
                <div className="px-4 py-8 text-center text-sm text-muted-foreground">Select a file.</div>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
