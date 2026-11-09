import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { BookOpen, Cable, FlaskConical, MoreHorizontal, Pencil, Plus, Rocket, Search, Trash2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { EmptyState, Skeleton } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime, relativeTime } from "@/lib/format";
import type { Connection } from "@/types";
import { ProviderIcon, TerraformBadge } from "./ProviderBadge";
import { DOCS_URL, identitySummary, providerMeta, sortProviders } from "./providers";

export interface ConnectionListProps {
  connections: Connection[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  /** operator */
  canTest: boolean;
  /** admin */
  canManage: boolean;
  testingId?: string | null;
  onTest: (connection: Connection) => void;
  onEdit: (connection: Connection) => void;
  onDelete: (connection: Connection) => void;
  onAdd?: () => void;
}

export function runUrlFor(connection: Pick<Connection, "provider" | "id">): string {
  return `/runs/new?cloud=${encodeURIComponent(connection.provider)}&connection=${encodeURIComponent(connection.id)}`;
}

export function ConnectionList({ connections, loading, error, onRetry, canTest, canManage, testingId, onTest, onEdit, onDelete, onAdd }: ConnectionListProps) {
  const navigate = useNavigate();
  const [provider, setProvider] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");

  const providersPresent = React.useMemo(() => sortProviders(Array.from(new Set(connections.map((item) => item.provider)))), [connections]);
  const needle = query.trim().toLowerCase();
  const filtered = React.useMemo(
    () =>
      connections
        .filter((item) => !provider || item.provider === provider)
        .filter((item) => {
          if (!needle) return true;
          const haystack = [item.name, item.method_label ?? item.auth_method, item.provider_label ?? providerMeta(item.provider).label, identitySummary(item) ?? "", item.created_by ?? ""].join(" ").toLowerCase();
          return haystack.includes(needle);
        })
        .sort((a, b) => a.name.localeCompare(b.name)),
    [connections, provider, needle],
  );
  const filtersActive = provider !== null || needle !== "";
  const showMenu = canTest || canManage;

  if (loading && connections.length === 0) {
    return (
      <div className="surface space-y-2 p-4" data-testid="connections-loading">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-11" />
        ))}
      </div>
    );
  }

  if (error && connections.length === 0) {
    return (
      <div className="surface">
        <EmptyState
          title="Could not load connections"
          description={error}
          action={
            <Button variant="outline" onClick={onRetry}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  if (connections.length === 0) {
    return (
      <div className="surface">
        <EmptyState
          icon={Cable}
          title="No cloud connections yet"
          description="A connection stores how the platform authenticates to a cloud account. Test verifies the identity without touching resources, and Terraform plan and apply receive the credentials as environment variables."
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              {canManage && onAdd ? (
                <Button onClick={onAdd} data-testid="add-connection-empty">
                  <Plus /> Add connection
                </Button>
              ) : null}
              <Button variant="outline" asChild>
                <a href={DOCS_URL} target="_blank" rel="noreferrer noopener">
                  <BookOpen /> Connections guide
                </a>
              </Button>
            </div>
          }
          testId="connections-empty"
        />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by name, method or identity…" className="pl-8" data-testid="connections-search" />
        </div>
        {providersPresent.length > 1 ? (
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by provider">
            {providersPresent.map((key) => (
              <button key={key} type="button" onClick={() => setProvider(provider === key ? null : key)} className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-pressed={provider === key} data-testid={`filter-${key}`}>
                <Badge variant={provider === key ? "default" : "outline"} className="cursor-pointer gap-1.5 pl-1">
                  <ProviderIcon provider={key} size="sm" />
                  {providerMeta(key).label}
                </Badge>
              </button>
            ))}
          </div>
        ) : null}
        {filtersActive ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setQuery("");
              setProvider(null);
            }}
          >
            <X /> Clear
          </Button>
        ) : null}
      </div>

      <div className="surface overflow-hidden">
        {filtered.length === 0 ? (
          <EmptyState title="No connections match" description="Try a different search or clear the filters." testId="connections-no-match" />
        ) : (
          <Table data-testid="connections-table">
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Connection</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden lg:table-cell">Terraform</TableHead>
                <TableHead className="hidden xl:table-cell">Identity</TableHead>
                <TableHead className="hidden lg:table-cell">Last checked</TableHead>
                <TableHead className="hidden xl:table-cell">Created by</TableHead>
                <TableHead className="w-10 pr-3" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((connection) => {
                const identity = identitySummary(connection);
                const testing = testingId === connection.id;
                return (
                  <TableRow key={connection.id} clickable onClick={() => navigate(`/connections/${connection.id}`)} data-testid="connection-row">
                    <TableCell className="pl-4">
                      <div className="flex items-center gap-3">
                        <ProviderIcon provider={connection.provider} />
                        <div className="min-w-0">
                          <div className="truncate font-medium">{connection.name}</div>
                          <div className="truncate text-xs text-muted-foreground">
                            {connection.provider_label ?? providerMeta(connection.provider).label} · {connection.method_label ?? connection.auth_method.replace(/_/g, " ")}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={connection.status} pulse={testing} />
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <TerraformBadge ready={connection.terraform_ready} />
                    </TableCell>
                    <TableCell className="hidden max-w-[260px] xl:table-cell">
                      {identity ? (
                        <span className="block truncate font-mono text-[12px] text-muted-foreground" title={identity}>
                          {identity}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground/70">—</span>
                      )}
                    </TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground lg:table-cell">
                      {connection.last_checked_at ? (
                        <span title={formatDateTime(connection.last_checked_at)}>{relativeTime(connection.last_checked_at)}</span>
                      ) : (
                        <span className="text-muted-foreground/70">never</span>
                      )}
                    </TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground xl:table-cell">
                      <span className="block truncate" title={connection.created_by ?? undefined}>
                        {connection.created_by ?? "—"}
                      </span>
                    </TableCell>
                    <TableCell className="pr-3" onClick={(event) => event.stopPropagation()}>
                      {showMenu ? (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${connection.name}`} data-testid="connection-actions">
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {canTest ? (
                              <>
                                <DropdownMenuItem onSelect={() => onTest(connection)} disabled={testing} data-testid="action-test">
                                  <FlaskConical /> Test
                                </DropdownMenuItem>
                                <DropdownMenuItem asChild data-testid="action-run">
                                  <Link to={runUrlFor(connection)}>
                                    <Rocket /> New run with this connection
                                  </Link>
                                </DropdownMenuItem>
                              </>
                            ) : null}
                            {canTest && canManage ? <DropdownMenuSeparator /> : null}
                            {canManage ? (
                              <>
                                <DropdownMenuItem onSelect={() => onEdit(connection)} data-testid="action-edit">
                                  <Pencil /> Edit
                                </DropdownMenuItem>
                                <DropdownMenuItem destructive onSelect={() => onDelete(connection)} data-testid="action-delete">
                                  <Trash2 /> Delete…
                                </DropdownMenuItem>
                              </>
                            ) : null}
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
    </div>
  );
}
