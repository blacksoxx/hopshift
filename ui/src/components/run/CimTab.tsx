import * as React from "react";
import {
  columnFilteringFeature,
  createColumnHelper,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_includesString,
  globalFilteringFeature,
  rowSelectionFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  sortFn_text,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, Braces, ChevronsUpDown, Eraser, Network, Save, Search, Server, Undo2, Wand2, X } from "lucide-react";
import { api } from "@/api";
import { useTargets } from "@/hooks/useTargets";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Checkbox, Switch } from "@/components/ui/switch";
import { SimpleSelect } from "@/components/ui/select";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, EmptyState, Pill } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import type { Cim, ComputeUnit } from "@/types";

export const CIM_SAVED_MESSAGE = "CIM saved into the paused run";

const features = tableFeatures({
  columnFilteringFeature,
  globalFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  filterFns: { includesString: filterFn_includesString },
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric, basic: sortFn_basic, text: sortFn_text },
  rowSelectionFeature,
});

const helper = createColumnHelper<typeof features, ComputeUnit>();

type UnitPatch = Partial<Pick<ComputeUnit, "name" | "vcpus" | "ram_mb" | "image_ref" | "cluster_ref">>;

interface CellTools {
  editable: boolean;
  update: (index: number, patch: UnitPatch) => void;
}

const NONE = "__none__";

function gb(mb: number): string {
  const value = mb / 1024;
  return `${Number.isInteger(value) ? value : value.toFixed(1)} GB`;
}

/** Shape check for the raw JSON editor: enough to refuse obviously broken payloads before the API does. */
export function validateCim(value: unknown): Cim {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("The CIM must be a JSON object.");
  const cim = value as Cim;
  if (!Array.isArray(cim.compute_units)) throw new Error("compute_units must be an array.");
  cim.compute_units.forEach((unit, index) => {
    if (!unit || typeof unit !== "object") throw new Error(`compute_units[${index}] must be an object.`);
    if (typeof unit.id !== "string" || !unit.id) throw new Error(`compute_units[${index}].id must be a non-empty string.`);
    if (typeof unit.name !== "string" || !unit.name) throw new Error(`compute_units[${index}].name must be a non-empty string.`);
  });
  return cim;
}

function buildColumns(tools: React.MutableRefObject<CellTools>) {
  const editable = () => tools.current.editable;
  const update = (index: number, patch: UnitPatch) => tools.current.update(index, patch);
  return helper.columns([
    helper.display({
      id: "select",
      header: ({ table }) => (
        <Checkbox
          aria-label="Select all"
          checked={table.getIsAllRowsSelected() ? true : table.getIsSomeRowsSelected() ? "indeterminate" : false}
          onCheckedChange={(value) => table.toggleAllRowsSelected(value === true)}
          data-testid="cim-select-all"
        />
      ),
      cell: ({ row }) => <Checkbox aria-label={`Select ${row.original.name}`} checked={row.getIsSelected()} onCheckedChange={(value) => row.toggleSelected(value === true)} data-testid={`cim-select-${row.index}`} />,
      enableSorting: false,
    }),
    helper.accessor((row) => row.name, {
      id: "name",
      header: "Name",
      sortFn: "text",
      cell: ({ row, getValue }) =>
        editable() ? (
          <Input value={getValue()} onChange={(event) => update(row.index, { name: event.target.value })} className="h-8 min-w-40 text-sm" data-testid={`unit-name-${row.index}`} aria-label={`Name of ${row.original.id}`} />
        ) : (
          <div className="min-w-0">
            <div className="font-medium" data-testid={`unit-name-${row.index}`}>
              {getValue()}
            </div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">{row.original.id}</div>
          </div>
        ),
    }),
    helper.accessor((row) => row.vcpus, {
      id: "vcpus",
      header: "vCPU",
      sortFn: "basic",
      cell: ({ row, getValue }) =>
        editable() ? (
          <Input type="number" min={1} value={getValue()} onChange={(event) => update(row.index, { vcpus: Math.max(1, Number(event.target.value) || 1) })} className="h-8 w-20 text-sm tabular" aria-label={`vCPUs of ${row.original.name}`} />
        ) : (
          <span className="tabular">{getValue()}</span>
        ),
    }),
    helper.accessor((row) => row.ram_mb, {
      id: "ram_mb",
      header: "RAM",
      sortFn: "basic",
      cell: ({ row, getValue }) =>
        editable() ? (
          <div className="flex items-center gap-1.5">
            <Input type="number" min={1} step={256} value={getValue()} onChange={(event) => update(row.index, { ram_mb: Math.max(1, Number(event.target.value) || 1) })} className="h-8 w-24 text-sm tabular" aria-label={`RAM in MB of ${row.original.name}`} />
            <span className="whitespace-nowrap text-[11px] text-muted-foreground">MB · {gb(getValue())}</span>
          </div>
        ) : (
          <span className="tabular" title={`${getValue()} MB`}>
            {gb(getValue())}
          </span>
        ),
    }),
    helper.accessor((row) => row.cluster_ref ?? "", {
      id: "cluster",
      header: "Cluster",
      sortFn: "text",
      cell: ({ getValue }) => (getValue() ? <span className="whitespace-nowrap font-mono text-xs">{getValue()}</span> : <span className="text-muted-foreground">–</span>),
    }),
    helper.accessor((row) => row.migration_status, {
      id: "status",
      header: "Status",
      sortFn: "text",
      cell: ({ row, getValue }) => (
        <div className="flex flex-wrap items-center gap-1">
          <StatusBadge status={getValue()} />
          {row.original.blockers.map((blocker) => (
            <Badge key={blocker} variant="danger" className="font-mono text-[10.5px]" title={blocker}>
              {blocker}
            </Badge>
          ))}
        </div>
      ),
    }),
    helper.accessor((row) => row.guest_os ?? "", {
      id: "guest_os",
      header: "Guest OS",
      sortFn: "text",
      cell: ({ getValue }) =>
        getValue() ? (
          <span className="block max-w-[180px] truncate text-xs" title={getValue()}>
            {getValue()}
          </span>
        ) : (
          <span className="text-muted-foreground">–</span>
        ),
    }),
    helper.accessor((row) => row.image_ref ?? "", {
      id: "image_ref",
      header: "Image ref",
      sortFn: "text",
      cell: ({ row, getValue }) =>
        editable() ? (
          <Input value={getValue()} placeholder="ami-… / image id" onChange={(event) => update(row.index, { image_ref: event.target.value || null })} className="h-8 min-w-36 font-mono text-xs" aria-label={`Image of ${row.original.name}`} data-testid={`unit-image-${row.index}`} />
        ) : getValue() ? (
          <span className="font-mono text-xs">{getValue()}</span>
        ) : (
          <span className="text-muted-foreground">–</span>
        ),
    }),
    helper.accessor((row) => row.nics.map((nic) => nic.port_group_ref).join(", "), {
      id: "nics",
      header: "NICs",
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-1">
          {row.original.nics.length === 0 ? <span className="text-muted-foreground">–</span> : null}
          {row.original.nics.map((nic, index) => (
            <span key={`${nic.name}-${index}`} title={nic.name}>
              <Pill className="whitespace-nowrap">{nic.port_group_ref}</Pill>
            </span>
          ))}
        </div>
      ),
    }),
    helper.accessor((row) => row.storage_volumes.reduce((total, volume) => total + volume.size_gb, 0), {
      id: "disks",
      header: "Disks",
      sortFn: "basic",
      cell: ({ row }) => (
        <span className="whitespace-nowrap text-xs tabular" title={row.original.storage_volumes.map((volume) => `${volume.id}: ${volume.size_gb} GB${volume.datastore ? ` on ${volume.datastore}` : ""}`).join("\n")}>
          {row.original.storage_volumes.length === 0 ? <span className="text-muted-foreground">–</span> : row.original.storage_volumes.map((volume) => `${volume.size_gb} GB`).join(", ")}
        </span>
      ),
    }),
  ]);
}

export interface CimTabProps {
  runId: string;
  cim: Cim | null;
  editable: boolean;
  /** Why the table is read-only (shown as a hint). */
  readOnlyReason?: string;
  onSaved: () => Promise<void> | void;
}

export function CimTab({ runId, cim, editable, readOnlyReason, onSaved }: CimTabProps) {
  const { toast } = useToast();
  const { labelOf } = useTargets();
  const [draft, setDraft] = React.useState<Cim | null>(cim);
  const [raw, setRaw] = React.useState(false);
  const [rawText, setRawText] = React.useState(() => (cim ? JSON.stringify(cim, null, 2) : ""));
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [bulkImage, setBulkImage] = React.useState("");
  const [bulkCluster, setBulkCluster] = React.useState(NONE);
  const baseline = React.useRef(cim ? JSON.stringify(cim) : "");

  // Re-sync only when the server copy really changed (a status poll must not clobber edits).
  React.useEffect(() => {
    const serialized = cim ? JSON.stringify(cim) : "";
    if (serialized === baseline.current) return;
    baseline.current = serialized;
    setDraft(cim);
    setRawText(cim ? JSON.stringify(cim, null, 2) : "");
    setError(null);
  }, [cim]);

  const update = React.useCallback((index: number, patch: UnitPatch) => {
    setDraft((current) => {
      if (!current) return current;
      const units = current.compute_units.map((unit, i) => (i === index ? { ...unit, ...patch } : unit));
      return { ...current, compute_units: units };
    });
  }, []);

  const tools = React.useRef<CellTools>({ editable, update });
  tools.current = { editable, update };
  const columns = React.useMemo(() => buildColumns(tools), []);
  const data = React.useMemo(() => draft?.compute_units ?? [], [draft]);

  const table = useTable({
    features,
    columns,
    data,
    getRowId: (unit) => unit.id,
    globalFilterFn: "includesString",
    enableSortingRemoval: true,
  });

  const selectedRows = table.getSelectedRowModel().rows;
  const selectedIndexes = selectedRows.map((row) => row.index);
  const dirty = raw ? rawText !== (cim ? JSON.stringify(cim, null, 2) : "") : JSON.stringify(draft) !== baseline.current;

  function applyBulk(patch: UnitPatch) {
    setDraft((current) => {
      if (!current) return current;
      const indexes = new Set(selectedIndexes);
      return { ...current, compute_units: current.compute_units.map((unit, i) => (indexes.has(i) ? { ...unit, ...patch } : unit)) };
    });
  }

  function toggleRaw(next: boolean) {
    setError(null);
    if (next) {
      setRawText(JSON.stringify(draft, null, 2));
      setRaw(true);
      return;
    }
    if (!editable) {
      setRaw(false);
      return;
    }
    try {
      setDraft(validateCim(JSON.parse(rawText)));
      setRaw(false);
    } catch (exc) {
      setError(`The JSON is not valid: ${(exc as Error).message}`);
    }
  }

  function discard() {
    setDraft(cim);
    setRawText(cim ? JSON.stringify(cim, null, 2) : "");
    setError(null);
    table.resetRowSelection(true);
  }

  async function save() {
    let payload: Cim | null = draft;
    if (raw) {
      try {
        payload = validateCim(JSON.parse(rawText));
      } catch (exc) {
        setError(`The JSON is not valid: ${(exc as Error).message}`);
        return;
      }
    }
    if (!payload) return;
    setSaving(true);
    setError(null);
    try {
      await api.patchState(runId, { sized_cim: payload });
      baseline.current = JSON.stringify(payload);
      setDraft(payload);
      setRawText(JSON.stringify(payload, null, 2));
      toast({
        // The live-region announcement repeats the toast text; give it an equivalent wording so
        // the visible message stays the only element with this exact text (tests look it up).
        title: (
          <span data-radix-toast-announce-exclude="" data-radix-toast-announce-alt="The edited CIM was stored in the paused run.">
            {CIM_SAVED_MESSAGE}
          </span>
        ),
        description: "Approve to continue with the edited model.",
        variant: "success",
      });
      await onSaved();
    } catch (exc) {
      setError((exc as Error).message);
      toast({ title: "Could not save the CIM", description: (exc as Error).message, variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  if (!draft) {
    return <EmptyState icon={Server} title="No canonical model yet" description="The CIM is available once the run has paused at review_cim or finished." testId="cim-empty" />;
  }

  const switches = draft.network_topology?.distributed_switches ?? [];
  const clusters = draft.clusters ?? [];
  const clusterOptions = [{ value: NONE, label: "No cluster" }, ...clusters.map((cluster) => ({ value: cluster.name, label: cluster.name }))];
  const rows = table.getRowModel().rows;

  return (
    <div className="space-y-4">
      {!editable ? (
        <Alert variant="info" testId="cim-readonly">
          {readOnlyReason ?? "The CIM is read-only. It can be edited by an operator while the run is paused at review_cim."}
        </Alert>
      ) : null}
      {error ? (
        <Alert variant="error" testId="cim-error">
          <pre className="font-mono text-xs">{error}</pre>
        </Alert>
      ) : null}

      <div className="surface overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{draft.source?.platform ?? "unknown source"}</span> · {draft.source?.name ?? draft.source_vcenter} → <span className="font-medium text-foreground">{labelOf(draft.target_provider)}</span> · {draft.compute_units.length} unit{draft.compute_units.length === 1 ? "" : "s"} · {clusters.length} cluster{clusters.length === 1 ? "" : "s"} · {switches.length} switch{switches.length === 1 ? "" : "es"}
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            {!raw ? (
              <div className="relative w-56">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={table.state.globalFilter ?? ""} onChange={(event) => table.setGlobalFilter(event.target.value)} placeholder="Filter units…" className="h-8 pl-8 text-xs" data-testid="cim-filter" />
              </div>
            ) : null}
            <div className="flex items-center gap-2">
              <Switch id="cim-raw" checked={raw} onCheckedChange={toggleRaw} data-testid="cim-raw-toggle" />
              <Label htmlFor="cim-raw" className="flex cursor-pointer items-center gap-1 text-xs font-normal text-muted-foreground">
                <Braces className="size-3.5" /> Raw JSON
              </Label>
            </div>
            {editable ? (
              <>
                {dirty ? (
                  <Button variant="ghost" size="sm" onClick={discard} disabled={saving} data-testid="discard-cim">
                    <Undo2 /> Discard
                  </Button>
                ) : null}
                <Button size="sm" onClick={() => void save()} loading={saving} disabled={!dirty} data-testid="save-cim">
                  <Save /> Save CIM
                </Button>
              </>
            ) : null}
          </div>
        </div>

        {editable && !raw && selectedRows.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 border-b border-border bg-accent/40 px-4 py-2 text-xs" data-testid="cim-bulk-bar">
            <span className="font-medium">
              {selectedRows.length} selected
            </span>
            <span className="mx-1 h-4 w-px bg-border" />
            <Input value={bulkImage} onChange={(event) => setBulkImage(event.target.value)} placeholder="ami-… / image id" className="h-7 w-44 font-mono text-xs" aria-label="Image ref for selected units" data-testid="bulk-image-input" />
            <Button size="sm" variant="outline" className="h-7" disabled={!bulkImage.trim()} onClick={() => applyBulk({ image_ref: bulkImage.trim() })} data-testid="bulk-set-image">
              <Wand2 /> Set image ref
            </Button>
            <Button size="sm" variant="outline" className="h-7" onClick={() => applyBulk({ image_ref: null })} data-testid="bulk-clear-image">
              <Eraser /> Clear image ref
            </Button>
            <span className="mx-1 h-4 w-px bg-border" />
            <SimpleSelect value={bulkCluster} onValueChange={setBulkCluster} options={clusterOptions} className="h-7 w-44 text-xs" testId="bulk-cluster-select" />
            <Button size="sm" variant="outline" className="h-7" onClick={() => applyBulk({ cluster_ref: bulkCluster === NONE ? null : bulkCluster })} data-testid="bulk-set-cluster">
              Set cluster
            </Button>
            <Button size="sm" variant="ghost" className="ml-auto h-7" onClick={() => table.resetRowSelection(true)}>
              <X /> Clear selection
            </Button>
          </div>
        ) : null}

        {raw ? (
          <div className="p-3">
            <Textarea value={rawText} onChange={(event) => setRawText(event.target.value)} readOnly={!editable} spellCheck={false} className="min-h-[420px] font-mono text-[12px] leading-relaxed" data-testid="cim-json" aria-label="CIM JSON" />
          </div>
        ) : (
          <Table data-testid="cim-table">
            <TableHeader>
              {table.getHeaderGroups().map((group) => (
                <TableRow key={group.id}>
                  {group.headers.map((header) => {
                    const sortable = header.column.getCanSort();
                    const sorted = header.column.getIsSorted();
                    return (
                      <TableHead key={header.id} className={cn(header.column.id === "select" && "w-8 pl-4", sortable && "cursor-pointer select-none hover:text-foreground")} onClick={sortable ? header.column.getToggleSortingHandler() : undefined} aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}>
                        {header.isPlaceholder ? null : (
                          <span className="inline-flex items-center gap-1">
                            <table.FlexRender header={header} />
                            {sortable ? sorted === "asc" ? <ArrowUp className="size-3" /> : sorted === "desc" ? <ArrowDown className="size-3" /> : <ChevronsUpDown className="size-3 opacity-40" /> : null}
                          </span>
                        )}
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={columns.length} className="py-8 text-center text-sm text-muted-foreground">
                    {data.length === 0 ? "The model has no compute units." : "No units match the filter."}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => (
                  <TableRow key={row.id} data-state={row.getIsSelected() ? "selected" : undefined} data-testid="cim-row">
                    {row.getAllCells().map((cell) => (
                      <TableCell key={cell.id} className={cn(cell.column.id === "select" && "w-8 pl-4")}>
                        <table.FlexRender cell={cell} />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Network className="size-4 text-muted-foreground" /> Network topology
            </CardTitle>
            <CardDescription>Distributed switches and their segments.</CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            {switches.length === 0 ? (
              <div className="text-sm text-muted-foreground">No switches in the model.</div>
            ) : (
              <ul className="space-y-3">
                {switches.map((sw) => (
                  <li key={sw.name}>
                    <div className="text-sm font-medium">{sw.name}</div>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {sw.port_groups.map((group) => (
                        <span key={group.name} className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 px-1.5 py-0.5 text-xs">
                          {group.name}
                          {group.vlan_id ? <span className="font-mono text-[10.5px] text-muted-foreground">VLAN {group.vlan_id}</span> : null}
                        </span>
                      ))}
                      {sw.port_groups.length === 0 ? <span className="text-xs text-muted-foreground">no segments</span> : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="size-4 text-muted-foreground" /> Clusters
            </CardTitle>
            <CardDescription>Placement semantics carried into the target.</CardDescription>
          </CardHeader>
          <CardContent className="px-0 pt-0">
            {clusters.length === 0 ? (
              <div className="px-5 text-sm text-muted-foreground">No clusters in the model.</div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-5">Name</TableHead>
                    <TableHead className="pr-5">Semantics</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {clusters.map((cluster) => (
                    <TableRow key={cluster.name}>
                      <TableCell className="pl-5 font-mono text-xs">{cluster.name}</TableCell>
                      <TableCell className="pr-5">
                        <Badge variant="outline">{cluster.semantics}</Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
