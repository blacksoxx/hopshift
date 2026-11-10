import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { ListChecks, MoreHorizontal, Plus, Search, StopCircle, Tag, Trash2, X } from "lucide-react";
import { api } from "@/api";
import { useAsync, useDebounced } from "@/hooks/useAsync";
import { useTargets } from "@/hooks/useTargets";
import { TargetBadge } from "@/components/TargetBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { SimpleSelect } from "@/components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/providers/AuthProvider";
import { formatDateTime, relativeTime, shortId } from "@/lib/format";
import type { RunRecord } from "@/types";

const STATUSES = ["created", "running", "paused", "succeeded", "failed", "error", "cancelled"];

export function RunsPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const { toast } = useToast();
  const [query, setQuery] = React.useState("");
  const [status, setStatus] = React.useState("all");
  const [cloud, setCloud] = React.useState("all");
  const [tag, setTag] = React.useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState<RunRecord | null>(null);
  const debounced = useDebounced(query);

  const runs = useAsync(
    () => api.listRuns({ q: debounced || undefined, status: status === "all" ? undefined : status, cloud: cloud === "all" ? undefined : cloud, tag: tag ?? undefined }),
    [debounced, status, cloud, tag],
    { pollMs: (data) => (data?.some((run) => run.status === "running" || run.executing) ? 3000 : 15000) },
  );
  const { targets } = useTargets();

  const allTags = React.useMemo(() => Array.from(new Set((runs.data ?? []).flatMap((run) => run.tags ?? []))).sort(), [runs.data]);

  async function cancel(run: RunRecord) {
    try {
      await api.cancel(run.run_id);
      toast({ title: "Cancellation requested", description: "The run stops after the current step.", variant: "warning" });
      await runs.reload();
    } catch (exc) {
      toast({ title: "Could not cancel", description: (exc as Error).message, variant: "error" });
    }
  }

  async function remove(run: RunRecord) {
    try {
      await api.deleteRun(run.run_id);
      toast({ title: "Run deleted", description: run.name || run.run_id, variant: "success" });
      setConfirmDelete(null);
      await runs.reload();
    } catch (exc) {
      toast({ title: "Could not delete", description: (exc as Error).message, variant: "error" });
    }
  }

  const filtersActive = query || status !== "all" || cloud !== "all" || tag;

  return (
    <div>
      <PageHeader
        title="Runs"
        description="Every migration run with its lifecycle, from discovery to deployed infrastructure."
        actions={
          can("operator") ? (
            <Button asChild>
              <Link to="/runs/new" data-testid="new-run">
                <Plus /> New run
              </Link>
            </Button>
          ) : null
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by name, id, file or tag…" className="pl-8" data-testid="runs-search" />
        </div>
        <SimpleSelect value={status} onValueChange={setStatus} className="w-40" options={[{ value: "all", label: "Any status" }, ...STATUSES.map((item) => ({ value: item, label: item }))]} testId="runs-status-filter" />
        <SimpleSelect value={cloud} onValueChange={setCloud} className="w-44" options={[{ value: "all", label: "Any target" }, ...targets.map((item) => ({ value: item.name, label: item.label }))]} testId="runs-target-filter" />
        {allTags.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <Tag className="size-3.5 text-muted-foreground" />
            {allTags.map((item) => (
              <button key={item} onClick={() => setTag(tag === item ? null : item)} className="focus-visible:outline-none">
                <Badge variant={tag === item ? "default" : "outline"} className="cursor-pointer">
                  {item}
                </Badge>
              </button>
            ))}
          </div>
        ) : null}
        {filtersActive ? (
          <Button variant="ghost" size="sm" onClick={() => { setQuery(""); setStatus("all"); setCloud("all"); setTag(null); }}>
            <X /> Clear
          </Button>
        ) : null}
      </div>

      <div className="surface overflow-hidden">
        {runs.loading && !runs.data ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-10" />
            ))}
          </div>
        ) : runs.error ? (
          <EmptyState title="Could not load runs" description={runs.error} action={<Button variant="outline" onClick={() => void runs.reload()}>Retry</Button>} />
        ) : (runs.data ?? []).length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title={filtersActive ? "No runs match these filters" : "No runs yet"}
            description={filtersActive ? "Try a different search or clear the filters." : "Upload a discovery JSON from any registered source and hopshift turns it into validated Terraform for the target you choose."}
            action={!filtersActive && can("operator") ? <Button asChild><Link to="/runs/new">Create the first run</Link></Button> : undefined}
            testId="runs-empty"
          />
        ) : (
          <Table data-testid="runs-table">
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Run</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden md:table-cell">Mode</TableHead>
                <TableHead className="hidden lg:table-cell">Tags</TableHead>
                <TableHead className="hidden md:table-cell">Created</TableHead>
                <TableHead className="w-10 pr-3" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {(runs.data ?? []).map((run) => {
                const live = run.status === "running" || run.executing;
                return (
                  <TableRow key={run.run_id} clickable onClick={() => navigate(`/runs/${run.run_id}`)} data-testid="run-row">
                    <TableCell className="pl-4">
                      <div className="font-medium">{run.name || run.input_filename}</div>
                      <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                        {shortId(run.run_id)}
                        {run.name ? <span className="font-sans">· {run.input_filename}</span> : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      <TargetBadge name={run.cloud} />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <StatusBadge status={live ? "running" : run.status} />
                        {run.status === "paused" ? <span className="text-xs text-muted-foreground">{run.pause_point?.replace("_", " ")}</span> : null}
                      </div>
                    </TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground md:table-cell">{run.mode}</TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <div className="flex flex-wrap gap-1">
                        {(run.tags ?? []).map((item) => (
                          <Badge key={item} variant="outline">
                            {item}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground md:table-cell" title={formatDateTime(run.created_at)}>
                      {relativeTime(run.created_at)}
                      {run.created_by ? <span className="block truncate">{run.created_by}</span> : null}
                    </TableCell>
                    <TableCell className="pr-3" onClick={(event) => event.stopPropagation()}>
                      {can("operator") ? (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-sm" aria-label="Run actions" data-testid="run-actions">
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {live || run.status === "paused" || run.status === "created" ? (
                              <DropdownMenuItem onSelect={() => void cancel(run)}>
                                <StopCircle /> Cancel run
                              </DropdownMenuItem>
                            ) : null}
                            <DropdownMenuItem destructive onSelect={() => setConfirmDelete(run)} disabled={!!live}>
                              <Trash2 /> Delete…
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      ) : null}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>

      <Dialog open={confirmDelete !== null} onOpenChange={(open) => !open && setConfirmDelete(null)}>
        <DialogContent size="sm">
          <DialogHeader>
            <DialogTitle>Delete this run?</DialogTitle>
            <DialogDescription>
              {confirmDelete?.name || confirmDelete?.run_id} and all of its artifacts, events and Terraform state will be removed. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(null)}>
              Keep it
            </Button>
            <Button variant="destructive" onClick={() => confirmDelete && void remove(confirmDelete)} data-testid="confirm-delete">
              Delete run
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
