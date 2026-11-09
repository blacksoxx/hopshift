import * as React from "react";
import { KeyRound, Plus, Trash2 } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Alert, CodeBlock, EmptyState, Skeleton } from "@/components/ui/misc";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/providers/AuthProvider";
import { formatDateTime, relativeTime } from "@/lib/format";
import type { ApiToken, Role } from "@/types";
import { CopyButton } from "./CopyButton";
import { RoleBadge, ROLES } from "./UsersPanel";
import { FeatureUnavailable, loadOrUnavailable } from "./unavailable";

const ROLE_ORDER: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

/** A token can carry the caller's role or a lower one, never more. */
export function allowedRoles(role: Role | undefined): Role[] {
  const ceiling = ROLE_ORDER[role ?? "viewer"] ?? 0;
  return ROLES.filter((item) => ROLE_ORDER[item] <= ceiling);
}

export function isExpired(token: ApiToken, now = Date.now()): boolean {
  return token.expires_at !== null && new Date(token.expires_at).getTime() < now;
}

export function TokensPanel() {
  const { user, can } = useAuth();
  const { toast } = useToast();
  const admin = can("admin");
  const [all, setAll] = React.useState(false);
  const tokens = useAsync(() => loadOrUnavailable(() => api.listTokens(admin && all)), [all, admin]);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [created, setCreated] = React.useState<{ id: string; token: string; name: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState<ApiToken | null>(null);
  const [deleting, setDeleting] = React.useState(false);

  async function remove(token: ApiToken) {
    setDeleting(true);
    try {
      await api.deleteToken(token.id);
      toast({ title: "Token revoked", description: `${token.name} no longer authenticates.`, variant: "success" });
      setConfirmDelete(null);
      await tokens.reload();
    } catch (exc) {
      toast({ title: "Could not revoke the token", description: (exc as Error).message, variant: "error" });
    } finally {
      setDeleting(false);
    }
  }

  const loaded = tokens.data;
  if (loaded?.kind === "unavailable") return <FeatureUnavailable what="API tokens" testId="tokens-unavailable" />;
  const list = loaded?.kind === "ok" ? loaded.data : [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Tokens authenticate scripts and CI with <span className="font-mono text-[12.5px]">Authorization: Bearer vma_…</span>. They carry at most your own role and can expire.
        </p>
        <div className="flex items-center gap-3">
          {admin ? (
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <Switch checked={all} onCheckedChange={setAll} aria-label="Show tokens of all users" data-testid="tokens-all" /> All users
            </label>
          ) : null}
          <Button size="sm" onClick={() => setCreateOpen(true)} data-testid="create-token">
            <Plus /> Create token
          </Button>
        </div>
      </div>

      <div className="surface overflow-hidden">
        {tokens.loading && !loaded ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-9" />
            ))}
          </div>
        ) : tokens.error ? (
          <EmptyState title="Could not load tokens" description={tokens.error} action={<Button variant="outline" onClick={() => void tokens.reload()}>Retry</Button>} />
        ) : list.length === 0 ? (
          <EmptyState icon={KeyRound} title={all ? "No tokens exist yet" : "You have no API tokens"} description="Create one to call the API from scripts or CI without a browser session." testId="tokens-empty" />
        ) : (
          <Table data-testid="tokens-table">
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Name</TableHead>
                {all ? <TableHead>User</TableHead> : null}
                <TableHead>Role</TableHead>
                <TableHead className="hidden md:table-cell">Created</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead className="hidden sm:table-cell">Last used</TableHead>
                <TableHead className="w-10 pr-3" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((token) => {
                const expired = isExpired(token);
                return (
                  <TableRow key={token.id} data-testid="token-row">
                    <TableCell className="pl-4">
                      <div className="flex items-center gap-2 font-medium">
                        {token.name}
                        {expired ? (
                          <Badge variant="danger" dot>
                            expired
                          </Badge>
                        ) : null}
                      </div>
                      <div className="font-mono text-[11px] text-muted-foreground">{token.id}</div>
                    </TableCell>
                    {all ? <TableCell className="text-sm text-muted-foreground">{token.username ?? token.user_id ?? "–"}</TableCell> : null}
                    <TableCell>
                      <RoleBadge role={token.role} />
                    </TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground md:table-cell" title={formatDateTime(token.created_at)}>
                      {relativeTime(token.created_at)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground" title={token.expires_at ? formatDateTime(token.expires_at) : undefined}>
                      {token.expires_at ? relativeTime(token.expires_at) : "never"}
                    </TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground sm:table-cell" title={token.last_used_at ? formatDateTime(token.last_used_at) : undefined}>
                      {token.last_used_at ? relativeTime(token.last_used_at) : "never"}
                    </TableCell>
                    <TableCell className="pr-3">
                      <Button variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-destructive" onClick={() => setConfirmDelete(token)} aria-label={`Revoke ${token.name}`} data-testid="token-delete">
                        <Trash2 />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>

      <CreateTokenDialog
        open={createOpen}
        roles={allowedRoles(user?.role)}
        onOpenChange={setCreateOpen}
        onCreated={(value) => {
          setCreateOpen(false);
          setCreated(value);
          void tokens.reload();
        }}
      />

      <Dialog open={created !== null} onOpenChange={(open) => !open && setCreated(null)}>
        <DialogContent size="md">
          <DialogHeader>
            <DialogTitle>Token created</DialogTitle>
            <DialogDescription>{created?.name}</DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-3">
            <Alert variant="warning" title="Copy it now">
              This is the only time the token is shown. It is stored hashed; if it is lost, revoke it and create a new one.
            </Alert>
            <CodeBlock className="select-all break-all whitespace-pre-wrap" testId="token-value">
              {created?.token}
            </CodeBlock>
          </div>
          <DialogFooter>
            {created ? <CopyButton text={created.token} label="Copy token" testId="token-copy" /> : null}
            <Button onClick={() => setCreated(null)} data-testid="token-done">
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmDelete !== null} onOpenChange={(open) => !open && !deleting && setConfirmDelete(null)}>
        <DialogContent size="sm">
          <DialogHeader>
            <DialogTitle>Revoke this token?</DialogTitle>
            <DialogDescription>{confirmDelete?.name} stops authenticating immediately. Anything still using it fails with 401.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(null)} disabled={deleting}>
              Keep it
            </Button>
            <Button variant="destructive" loading={deleting} onClick={() => confirmDelete && void remove(confirmDelete)} data-testid="confirm-delete-token">
              Revoke token
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function CreateTokenDialog({ open, roles, onOpenChange, onCreated }: { open: boolean; roles: Role[]; onOpenChange: (open: boolean) => void; onCreated: (value: { id: string; token: string; name: string }) => void }) {
  const highest = roles[roles.length - 1] ?? "viewer";
  const [name, setName] = React.useState("");
  const [role, setRole] = React.useState<Role>(highest);
  const [expires, setExpires] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setName("");
      setRole(highest);
      setExpires("");
      setError(null);
    }
  }, [open, highest]);

  const days = expires.trim() === "" ? undefined : Number(expires);
  const valid = name.trim().length > 0 && (days === undefined || (Number.isInteger(days) && days > 0 && days <= 3650));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.createToken(name.trim(), role, days);
      onCreated({ ...result, name: name.trim() });
    } catch (exc) {
      setError((exc as Error).message || "Could not create the token.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent size="sm">
        <form onSubmit={submit} className="space-y-4" data-testid="token-dialog">
          <DialogHeader>
            <DialogTitle>Create an API token</DialogTitle>
            <DialogDescription>Give it a name you will recognise in the audit log.</DialogDescription>
          </DialogHeader>
          {error ? <Alert variant="error">{error}</Alert> : null}
          <Field label="Name" htmlFor="token-name">
            <Input id="token-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="ci-pipeline" required autoFocus data-testid="token-name" />
          </Field>
          <Field label="Role" htmlFor="token-role" hint={roles.length === 1 ? "Tokens cannot exceed your own role." : "At most your own role."}>
            <SimpleSelect id="token-role" value={role} onValueChange={(value) => setRole(value as Role)} options={roles.map((item) => ({ value: item, label: item }))} testId="token-role" />
          </Field>
          <Field label="Expires in (days)" htmlFor="token-expires" hint="Leave empty for a token that never expires." error={!valid && expires.trim() !== "" ? "Enter a whole number of days between 1 and 3650." : undefined}>
            <Input id="token-expires" type="number" inputMode="numeric" min={1} max={3650} step={1} value={expires} onChange={(event) => setExpires(event.target.value)} placeholder="90" data-testid="token-expires" />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" loading={busy} disabled={!valid} data-testid="token-submit">
              Create token
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
