export interface DiscoverySummary {
  vms: number;
  blocked: number;
  poweredOff: number;
  clusters: number;
  vcenter: string;
  schema: string;
  version: string;
}

export interface LoadedDiscovery {
  name: string;
  size: number;
  payload: Record<string, unknown>;
  summary: DiscoverySummary;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

/**
 * Counts the parts of a discovery JSON that matter before scoring it. The assessment service
 * scores workload inventories (`virtual_machines`, as the VMware vSphere collector writes them);
 * the origin fields are read when present and left blank otherwise.
 */
export function summarizeDiscovery(payload: unknown): DiscoverySummary {
  const data = asRecord(payload);
  const metadata = asRecord(data.metadata);
  const vms = (Array.isArray(data.virtual_machines) ? data.virtual_machines : Array.isArray(data.vms) ? data.vms : []).map(asRecord);
  const clusters = new Set<string>();
  const vcenters = new Set<string>();
  let blocked = 0;
  let poweredOff = 0;
  for (const vm of vms) {
    if (typeof vm.cluster === "string" && vm.cluster) clusters.add(vm.cluster);
    if (typeof vm.source_vcenter === "string" && vm.source_vcenter) vcenters.add(vm.source_vcenter);
    if (vm.migration_blocked === true || (Array.isArray(vm.migration_blockers) && vm.migration_blockers.length > 0)) blocked += 1;
    if (vm.power_state === "poweredOff") poweredOff += 1;
  }
  const queried = Array.isArray(metadata.vcenters_queried) ? (metadata.vcenters_queried as unknown[]).map(String) : [];
  const first = queried[0] ?? [...vcenters][0] ?? String(metadata.source_vcenter ?? "unknown");
  return {
    vms: vms.length,
    blocked,
    poweredOff,
    clusters: clusters.size,
    vcenter: queried.length > 1 ? `${first} +${queried.length - 1}` : first,
    schema: String(metadata.schema_name ?? "unknown"),
    version: String(metadata.schema_version ?? ""),
  };
}

/** Parses the file text; throws a readable error for anything that is not a discovery document. */
export function parseDiscovery(text: string, name: string, size: number): LoadedDiscovery {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch (exc) {
    throw new Error(`${name} is not valid JSON: ${(exc as Error).message}`);
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error(`${name} is not a JSON object.`);
  const summary = summarizeDiscovery(payload);
  if (summary.vms === 0) throw new Error("No workloads found. Expected a discovery JSON with a virtual_machines list.");
  return { name, size, payload: payload as Record<string, unknown>, summary };
}

export async function readDiscoveryFile(file: File): Promise<LoadedDiscovery> {
  return parseDiscovery(await file.text(), file.name, file.size);
}
