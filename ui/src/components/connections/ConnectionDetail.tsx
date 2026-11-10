import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Cable, Check, FlaskConical, Lock, LogIn, MoreHorizontal, Pencil, Rocket, Trash2, X } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input, Textarea } from "@/components/ui/input";
import { Alert, EmptyState, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/providers/AuthProvider";
import { formatDateTime, relativeTime, titleCase } from "@/lib/format";
import type { Connection, ConnectionField, ConnectionMethod, ConnectionTest } from "@/types";
import { PasswordInput } from "./ConnectionForm";
import { runUrlFor } from "./ConnectionList";
import { DeleteConnectionDialog } from "./DeleteDialog";
import { DeviceFlowDialog } from "./DeviceFlowDialog";
import { EditConnectionDialog } from "./EditConnectionDialog";
import { ProviderIcon, TerraformBadge } from "./ProviderBadge";
import { IdentityList } from "./TestResult";
import { describeApiError } from "./errors";
import { displayValue, fieldVisible, initialValues } from "./form";
import { NOT_TERRAFORM_READY, hasDeviceFlow, identitySummary, providerMeta, terraformEnvNames } from "./providers";

/** Secret keys written by the service itself (device flows); listed, never replaceable here. */
const INTERNAL_SECRET_LABELS: Record<string, string> = {
  sso_access_token: "SSO access token (from device sign-in)",
  sso_token_expires_at: "SSO token expiry",
};

function lastCheckOf(connection: Connection): ConnectionTest | null {
  if (connection.status === "unverified" || !connection.last_checked_at) return null;
  return { ok: connection.status === "ok", identity: connection.last_check?.identity ?? {}, message: connection.last_check?.message ?? "", checked_at: connection.last_checked_at };
}

export function ConnectionDetail({ connectionId }: { connectionId: string }) {
  const navigate = useNavigate();
  const { can } = useAuth();
  const { toast } = useToast();
  const meta = useAsync(() => api.meta(), []);
  const catalog = useAsync(() => api.connectionCatalog(), []);
  const siblings = useAsync(() => api.listConnections().catch(() => [] as Connection[]), []);
  const state = useAsync(() => api.getConnection(connectionId), [connectionId]);
  const connection = state.data;
  const [testing, setTesting] = React.useState(false);
  const [editOpen, setEditOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [deviceOpen, setDeviceOpen] = React.useState(false);

  const secretsAvailable = meta.data?.features.secrets ?? true;
  const method: ConnectionMethod | null = connection && catalog.data ? (catalog.data[connection.provider]?.methods.find((item) => item.key === connection.auth_method) ?? null) : null;

  async function runTest() {
    if (!connection) return;
    setTesting(true);
    try {
      const check = await api.testConnection(connection.id);
      state.setData((current) => (current ? { ...current, status: check.ok ? "ok" : "failed", last_checked_at: check.checked_at, last_check: { identity: check.identity, message: check.message } } : current));
      toast({
        title: check.ok ? "Connection verified" : "Verification failed",
        description: check.ok ? (identitySummary({ provider: connection.provider, last_check: { identity: check.identity } }) ?? check.message) : check.message,
        variant: check.ok ? "success" : "error",
      });
    } catch (exc) {
      const info = describeApiError(exc);
      toast({ title: info.title, description: info.message, variant: "error" });
    } finally {
      setTesting(false);
    }
  }

  if (state.loading && !connection) {
    return (
      <div data-testid="connection-detail-loading">
        <BackLink />
        <div className="mb-6 flex items-start gap-3">
          <Skeleton className="size-10 rounded-lg" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-56" />
            <Skeleton className="h-4 w-80" />
          </div>
        </div>
        <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  if (state.error || !connection) {
    return (
      <div>
        <BackLink />
        <EmptyState
          icon={Cable}
          title="Connection not found"
          description={state.error ?? "It may have been deleted."}
          action={
            <Button variant="outline" asChild>
              <Link to="/connections">Back to connections</Link>
            </Button>
          }
          testId="connection-missing"
        />
      </div>
    );
  }

  const provider = providerMeta(connection.provider);
  const providerLabel = connection.provider_label ?? provider.label;
  const methodLabel = connection.method_label ?? method?.label ?? connection.auth_method.replace(/_/g, " ");
  const env = terraformEnvNames(connection);
  const lastCheck = lastCheckOf(connection);
  const secretFields = method?.fields.filter((field) => field.secret) ?? [];
  const internalSecrets = connection.secret_fields.filter((key) => !secretFields.some((field) => field.key === key));
  const existingNames = (siblings.data ?? []).map((item) => item.name);

  const applyUpdate = (updated: Connection) => state.setData(updated);

  return (
    <div data-testid="connection-detail">
      <BackLink />
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <ProviderIcon provider={connection.provider} size="lg" className="mt-0.5" />
          <div className="min-w-0 space-y-1.5">
            <NameHeading connection={connection} canEdit={can("admin")} onSaved={applyUpdate} />
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <span>
                {providerLabel} · {methodLabel}
              </span>
              <span data-testid="connection-status">
                <StatusBadge status={connection.status} pulse={testing} />
              </span>
              <TerraformBadge ready={connection.terraform_ready} />
            </div>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {can("operator") ? (
            <Button variant="outline" onClick={() => void runTest()} loading={testing} data-testid="test-connection">
              <FlaskConical /> Test now
            </Button>
          ) : null}
          {can("operator") && hasDeviceFlow(connection) ? (
            <Button variant="outline" onClick={() => setDeviceOpen(true)} data-testid="device-signin">
              <LogIn /> Sign in
            </Button>
          ) : null}
          {can("operator") ? (
            <Button asChild>
              <Link to={runUrlFor(connection)} data-testid="detail-new-run">
                <Rocket /> New run
              </Link>
            </Button>
          ) : null}
          {can("admin") ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="More actions" data-testid="detail-actions">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setEditOpen(true)} data-testid="detail-edit">
                  <Pencil /> Edit configuration
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem destructive onSelect={() => setDeleting(true)} data-testid="delete-connection">
                  <Trash2 /> Delete…
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Identity</CardTitle>
              <CardDescription>
                {lastCheck ? (
                  <>
                    {lastCheck.ok ? "Verified" : "Failed"}{" "}
                    <span title={formatDateTime(lastCheck.checked_at)}>{relativeTime(lastCheck.checked_at)}</span>. What the provider reported for these credentials.
                  </>
                ) : (
                  "What the provider reports for these credentials once they are tested."
                )}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              <IdentityPanel check={lastCheck} canTest={can("operator")} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-start justify-between gap-3">
              <div className="space-y-1">
                <CardTitle>Configuration</CardTitle>
                <CardDescription>Non-secret settings of the {methodLabel} method.</CardDescription>
              </div>
              {can("admin") ? (
                <Button variant="outline" size="sm" onClick={() => setEditOpen(true)} data-testid="detail-edit-config">
                  <Pencil /> Edit
                </Button>
              ) : null}
            </CardHeader>
            <CardContent className="pt-0">
              <ConfigList connection={connection} method={method} />
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Secrets</CardTitle>
              <CardDescription>Encrypted at rest with HOPSHIFT_SECRET_KEY. The API never returns the values.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 pt-0" data-testid="secrets-card">
              {secretFields.length === 0 && internalSecrets.length === 0 ? <p className="text-sm text-muted-foreground">This method stores no secrets; it relies on the identity of the host.</p> : null}
              {secretFields.map((field) => (
                <SecretItem
                  key={field.key}
                  connection={connection}
                  field={field}
                  stored={connection.secret_fields.includes(field.key)}
                  canReplace={can("admin")}
                  secretsAvailable={secretsAvailable}
                  onSaved={applyUpdate}
                />
              ))}
              {internalSecrets.map((key) => (
                <div key={key} className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm" data-testid={`secret-${key}`}>
                  <span className="flex min-w-0 items-center gap-2">
                    <Lock className="size-4 shrink-0 text-muted-foreground" />
                    <span className="truncate">{INTERNAL_SECRET_LABELS[key] ?? titleCase(key)}</span>
                  </span>
                  <Badge variant="success" dot>
                    set
                  </Badge>
                </div>
              ))}
              {!secretsAvailable && secretFields.length > 0 && can("admin") ? <p className="text-xs text-muted-foreground">Set HOPSHIFT_SECRET_KEY on the server to replace secrets.</p> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Terraform environment</CardTitle>
              <CardDescription>Variables plan and apply receive from this connection. Values are resolved on the server and never shown.</CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              {env === null ? (
                <Alert variant="warning" title="Verify only" testId="terraform-env-blocked">
                  {NOT_TERRAFORM_READY}
                </Alert>
              ) : env.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nothing is set; the Terraform providers use the process environment.</p>
              ) : (
                <ul className="space-y-1.5" data-testid="terraform-env">
                  {env.map((item) => (
                    <li key={item.name} className="flex items-center justify-between gap-3 text-sm">
                      <code className="font-mono text-[12.5px]">{item.name}</code>
                      {item.note ? <span className="text-right text-xs text-muted-foreground">{item.note}</span> : null}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Details</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
                <dt className="text-muted-foreground">ID</dt>
                <dd className="break-all font-mono text-[12px]">{connection.id}</dd>
                <dt className="text-muted-foreground">Created by</dt>
                <dd>{connection.created_by ?? "—"}</dd>
                <dt className="text-muted-foreground">Created</dt>
                <dd title={formatDateTime(connection.created_at)}>{relativeTime(connection.created_at)}</dd>
                <dt className="text-muted-foreground">Updated</dt>
                <dd title={formatDateTime(connection.updated_at)}>{relativeTime(connection.updated_at)}</dd>
              </dl>
            </CardContent>
          </Card>
        </div>
      </div>

      <EditConnectionDialog connection={editOpen ? connection : null} catalog={catalog.data} onOpenChange={(open) => !open && setEditOpen(false)} secretsAvailable={secretsAvailable} existingNames={existingNames} onSaved={applyUpdate} />
      <DeleteConnectionDialog connection={deleting ? connection : null} onOpenChange={(open) => !open && setDeleting(false)} onDeleted={() => navigate("/connections")} />
      <DeviceFlowDialog connection={connection} open={deviceOpen} onOpenChange={setDeviceOpen} onComplete={() => state.reload()} />
    </div>
  );
}

function BackLink() {
  return (
    <Link to="/connections" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground">
      <ArrowLeft className="size-4" /> Connections
    </Link>
  );
}

function IdentityPanel({ check, canTest }: { check: ConnectionTest | null; canTest: boolean }) {
  if (!check) {
    return (
      <div className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground" data-testid="identity-unverified">
        Not verified yet. {canTest ? "Run a test to confirm the credentials and see the identity the provider reports." : "An operator can run a test to confirm the credentials."}
      </div>
    );
  }
  if (!check.ok) {
    return (
      <Alert variant="error" title="Verification failed" testId="test-result">
        <p className="break-words">{check.message || "The provider rejected the credentials."}</p>
        <div className="mt-1">Secret values are masked in this message.</div>
      </Alert>
    );
  }
  return (
    <div className="space-y-3" data-testid="test-result">
      {check.message ? <p className="text-sm text-muted-foreground">{check.message}</p> : null}
      <IdentityList identity={check.identity} />
    </div>
  );
}

function ConfigList({ connection, method }: { connection: Connection; method: ConnectionMethod | null }) {
  if (!method) {
    const entries = Object.entries(connection.config);
    if (entries.length === 0) return <p className="text-sm text-muted-foreground">No configuration.</p>;
    return (
      <dl className="grid grid-cols-[minmax(140px,max-content)_1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="config-list">
        {entries.map(([key, value]) => (
          <React.Fragment key={key}>
            <dt className="text-muted-foreground">{titleCase(key)}</dt>
            <dd className="min-w-0 break-all">{String(value)}</dd>
          </React.Fragment>
        ))}
      </dl>
    );
  }
  const values = initialValues(method.fields, connection.config);
  const fields = method.fields.filter((field) => !field.secret && fieldVisible(connection.provider, method.key, field, values));
  if (fields.length === 0) return <p className="text-sm text-muted-foreground">This method has no configuration.</p>;
  return (
    <dl className="grid grid-cols-[minmax(140px,max-content)_1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="config-list">
      {fields.map((field) => {
        const shown = displayValue(field, connection.config[field.key]);
        return (
          <React.Fragment key={field.key}>
            <dt className="text-muted-foreground">{field.label}</dt>
            <dd className="min-w-0 break-all">{shown ? <span className={field.type === "select" || field.type === "boolean" ? "" : "font-mono text-[12.5px]"}>{shown}</span> : <span className="text-muted-foreground/70">—</span>}</dd>
          </React.Fragment>
        );
      })}
    </dl>
  );
}

function NameHeading({ connection, canEdit, onSaved }: { connection: Connection; canEdit: boolean; onSaved: (connection: Connection) => void }) {
  const { toast } = useToast();
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(connection.name);
  const [busy, setBusy] = React.useState(false);

  function cancel() {
    setEditing(false);
    setDraft(connection.name);
  }

  async function save() {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === connection.name) {
      cancel();
      return;
    }
    setBusy(true);
    try {
      const updated = await api.updateConnection(connection.id, { name: trimmed });
      onSaved(updated);
      setEditing(false);
      toast({ title: "Renamed", description: updated.name, variant: "success" });
    } catch (exc) {
      const info = describeApiError(exc);
      toast({ title: info.title, description: info.message, variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") cancel();
          }}
          autoFocus
          maxLength={80}
          aria-label="Connection name"
          className="h-9 w-72 max-w-full text-base font-semibold"
          data-testid="name-input"
        />
        <Button type="submit" size="sm" loading={busy} data-testid="name-save">
          <Check /> Save
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={cancel} disabled={busy}>
          <X /> Cancel
        </Button>
      </form>
    );
  }
  return (
    <div className="flex items-center gap-1.5">
      <h1 className="truncate text-xl font-semibold tracking-tight" data-testid="connection-title">
        {connection.name}
      </h1>
      {canEdit ? (
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => {
            setDraft(connection.name);
            setEditing(true);
          }}
          aria-label="Rename connection"
          data-testid="name-edit"
        >
          <Pencil />
        </Button>
      ) : null}
    </div>
  );
}

function SecretItem({ connection, field, stored, canReplace, secretsAvailable, onSaved }: { connection: Connection; field: ConnectionField; stored: boolean; canReplace: boolean; secretsAvailable: boolean; onSaved: (connection: Connection) => void }) {
  const { toast } = useToast();
  const [editing, setEditing] = React.useState(false);
  const [value, setValue] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  function cancel() {
    setEditing(false);
    setValue("");
    setError(null);
  }

  async function save() {
    if (!value.trim()) {
      setError("Enter a value.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateConnection(connection.id, { secret: { [field.key]: value } });
      toast({ title: `${field.label} replaced`, description: "Status reset to unverified. Run a test to confirm it.", variant: "success" });
      onSaved(updated);
      cancel();
    } catch (exc) {
      setError(describeApiError(exc).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-md border border-border px-3 py-2" data-testid={`secret-${field.key}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <Lock className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{field.label}</span>
          {stored ? (
            <Badge variant="success" dot>
              set
            </Badge>
          ) : (
            <Badge variant="muted">not set</Badge>
          )}
        </div>
        {canReplace && !editing ? (
          <Button variant="ghost" size="sm" onClick={() => setEditing(true)} disabled={!secretsAvailable} data-testid={`replace-${field.key}`}>
            {stored ? "Replace" : "Set"}
          </Button>
        ) : null}
      </div>
      {editing ? (
        <div className="mt-2 space-y-2">
          {field.type === "textarea" ? (
            <Textarea
              value={value}
              onChange={(event) => setValue(event.target.value)}
              rows={6}
              placeholder={field.placeholder || "Paste the new value"}
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              className="font-mono text-[12.5px] leading-relaxed"
              aria-label={field.label}
              data-testid={`secret-input-${field.key}`}
            />
          ) : (
            <PasswordInput value={value} onChange={setValue} placeholder={field.placeholder || "New value"} invalid={!!error} testId={`secret-input-${field.key}`} />
          )}
          {field.help ? <p className="text-xs text-muted-foreground">{field.help}</p> : null}
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => void save()} loading={busy} data-testid={`save-${field.key}`}>
              <Check /> Save
            </Button>
            <Button size="sm" variant="ghost" onClick={cancel} disabled={busy}>
              <X /> Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
