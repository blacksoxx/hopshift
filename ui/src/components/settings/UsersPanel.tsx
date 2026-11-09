import * as React from "react";
import { KeyRound, MoreHorizontal, Pencil, Plus, ShieldOff, Trash2, UserCheck, UserCog, UserX, Users } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { passwordIssues } from "@/pages/SetupPage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Field, Input } from "@/components/ui/input";
import { Alert, EmptyState, Skeleton } from "@/components/ui/misc";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/providers/AuthProvider";
import { formatDateTime, relativeTime } from "@/lib/format";
import type { AuthUser, Role } from "@/types";
import { FeatureUnavailable, loadOrUnavailable } from "./unavailable";

export const ROLES: Role[] = ["viewer", "operator", "admin"];
const ROLE_VARIANT: Record<Role, "default" | "info" | "muted"> = { admin: "default", operator: "info", viewer: "muted" };

type Mode = { kind: "create" } | { kind: "role" | "name" | "password" | "reset-mfa" | "delete"; user: AuthUser };

export function RoleBadge({ role }: { role: Role }) {
  return (
    <Badge variant={ROLE_VARIANT[role] ?? "secondary"} className="capitalize">
      {role}
    </Badge>
  );
}

export function UsersPanel() {
  const { user: me, can } = useAuth();
  const { toast } = useToast();
  const admin = can("admin");
  const users = useAsync(() => loadOrUnavailable(() => api.listUsers()), [], { enabled: admin });
  const [mode, setMode] = React.useState<Mode | null>(null);

  async function toggleDisabled(target: AuthUser) {
    try {
      await api.updateUser(target.id, { disabled: !target.disabled });
      toast({ title: target.disabled ? "Account enabled" : "Account disabled", description: target.username, variant: "success" });
      await users.reload();
    } catch (exc) {
      toast({ title: "Could not update the account", description: (exc as Error).message, variant: "error" });
    }
  }

  if (!admin) {
    return <EmptyState icon={Users} title="Administrators manage users" description="Your role does not include account administration. Ask an administrator to add or change accounts." testId="users-forbidden" />;
  }

  const loaded = users.data;
  if (loaded?.kind === "unavailable") return <FeatureUnavailable what="User accounts" testId="users-unavailable" />;
  const list = loaded?.kind === "ok" ? loaded.data : [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Local accounts sign in with a password and, by policy, a second factor. Single sign-on accounts are created on first login.
        </p>
        <Button size="sm" onClick={() => setMode({ kind: "create" })} data-testid="add-user">
          <Plus /> Add user
        </Button>
      </div>

      <div className="surface overflow-hidden">
        {users.loading && !loaded ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-9" />
            ))}
          </div>
        ) : users.error ? (
          <EmptyState title="Could not load users" description={users.error} action={<Button variant="outline" onClick={() => void users.reload()}>Retry</Button>} />
        ) : list.length === 0 ? (
          <EmptyState icon={Users} title="No accounts yet" description="Create the first user; administrators can manage everything, operators run migrations, viewers read." />
        ) : (
          <Table data-testid="users-table">
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">User</TableHead>
                <TableHead>Role</TableHead>
                <TableHead className="hidden md:table-cell">Sign-in</TableHead>
                <TableHead className="hidden sm:table-cell">MFA</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden lg:table-cell">Last login</TableHead>
                <TableHead className="w-10 pr-3" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((item) => {
                const self = me?.id === item.id;
                return (
                  <TableRow key={item.id} data-testid="user-row" data-username={item.username}>
                    <TableCell className="pl-4">
                      <div className="flex items-center gap-2 font-medium">
                        {item.name || item.username}
                        {self ? (
                          <Badge variant="outline" className="font-normal">
                            you
                          </Badge>
                        ) : null}
                      </div>
                      <div className="font-mono text-[11.5px] text-muted-foreground">{item.username}</div>
                    </TableCell>
                    <TableCell>
                      <RoleBadge role={item.role} />
                    </TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground md:table-cell">{item.auth_kind}</TableCell>
                    <TableCell className="hidden sm:table-cell">
                      {item.mfa_enabled ? (
                        <Badge variant="success" dot>
                          enabled
                        </Badge>
                      ) : (
                        <Badge variant="muted">off</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {item.disabled ? (
                        <Badge variant="danger" dot>
                          disabled
                        </Badge>
                      ) : (
                        <Badge variant="outline">active</Badge>
                      )}
                    </TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground lg:table-cell" title={formatDateTime(item.last_login_at)}>
                      {item.last_login_at ? relativeTime(item.last_login_at) : "never"}
                    </TableCell>
                    <TableCell className="pr-3">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${item.username}`} data-testid="user-actions">
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-48">
                          <DropdownMenuItem onSelect={() => setMode({ kind: "role", user: item })} data-testid="user-change-role">
                            <UserCog /> Change role…
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={() => setMode({ kind: "name", user: item })}>
                            <Pencil /> Edit name…
                          </DropdownMenuItem>
                          {item.auth_kind !== "oidc" ? (
                            <DropdownMenuItem onSelect={() => setMode({ kind: "password", user: item })}>
                              <KeyRound /> Set password…
                            </DropdownMenuItem>
                          ) : null}
                          <DropdownMenuItem onSelect={() => setMode({ kind: "reset-mfa", user: item })} disabled={!item.mfa_enabled}>
                            <ShieldOff /> Reset second factor…
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem onSelect={() => void toggleDisabled(item)} disabled={self} data-testid="user-toggle-disabled">
                            {item.disabled ? (
                              <>
                                <UserCheck /> Enable account
                              </>
                            ) : (
                              <>
                                <UserX /> Disable account
                              </>
                            )}
                          </DropdownMenuItem>
                          <DropdownMenuItem destructive onSelect={() => setMode({ kind: "delete", user: item })} disabled={self} data-testid="user-delete">
                            <Trash2 /> Delete…
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>

      <UserDialog mode={mode} onClose={() => setMode(null)} onChanged={() => void users.reload()} />
    </div>
  );
}

const TITLES: Record<Mode["kind"], string> = {
  create: "Add a user",
  role: "Change role",
  name: "Edit display name",
  password: "Set a new password",
  "reset-mfa": "Reset the second factor?",
  delete: "Delete this account?",
};

function UserDialog({ mode, onClose, onChanged }: { mode: Mode | null; onClose: () => void; onChanged: () => void }) {
  const { toast } = useToast();
  const [username, setUsername] = React.useState("");
  const [name, setName] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [role, setRole] = React.useState<Role>("viewer");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const target = mode && mode.kind !== "create" ? mode.user : null;

  React.useEffect(() => {
    setUsername("");
    setPassword("");
    setError(null);
    setName(target?.name ?? "");
    setRole(target?.role ?? "viewer");
  }, [mode, target]);

  if (!mode) return null;
  const issues = mode.kind === "create" || mode.kind === "password" ? passwordIssues(password, mode.kind === "create" ? username : (target?.username ?? "")) : [];
  const valid =
    mode.kind === "create" ? username.trim().length > 0 && password.length > 0 && issues.length === 0 : mode.kind === "password" ? password.length > 0 && issues.length === 0 : mode.kind === "name" ? name.trim().length > 0 : true;

  async function submit(event?: React.FormEvent) {
    event?.preventDefault();
    if (!mode || !valid) return;
    setBusy(true);
    setError(null);
    try {
      let message = "";
      if (mode.kind === "create") {
        const created = await api.createUser({ username: username.trim(), password, name: name.trim() || username.trim(), role });
        message = `${created.username} can sign in now.`;
      } else if (mode.kind === "role") {
        await api.updateUser(mode.user.id, { role });
        message = `${mode.user.username} is now ${role}.`;
      } else if (mode.kind === "name") {
        await api.updateUser(mode.user.id, { name: name.trim() });
        message = `${mode.user.username} renamed.`;
      } else if (mode.kind === "password") {
        await api.updateUser(mode.user.id, { password });
        message = `${mode.user.username} must use the new password; other sessions are signed out.`;
      } else if (mode.kind === "reset-mfa") {
        await api.resetUserMfa(mode.user.id);
        message = `${mode.user.username} will enrol a new authenticator at next sign-in.`;
      } else {
        await api.deleteUser(mode.user.id);
        message = `${mode.user.username} removed.`;
      }
      toast({ title: TITLES[mode.kind].replace(/[?…]$/, ""), description: message, variant: "success" });
      onChanged();
      onClose();
    } catch (exc) {
      setError((exc as Error).message || "The request failed.");
    } finally {
      setBusy(false);
    }
  }

  const destructive = mode.kind === "delete" || mode.kind === "reset-mfa";

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent size="sm">
        <form onSubmit={submit} className="space-y-4" data-testid="user-dialog" data-mode={mode.kind}>
          <DialogHeader>
            <DialogTitle>{TITLES[mode.kind]}</DialogTitle>
            <DialogDescription>
              {mode.kind === "create"
                ? "The user signs in with this password and may be required to enrol a second factor."
                : mode.kind === "delete"
                  ? `${target?.username} loses access immediately; their runs and audit entries stay.`
                  : mode.kind === "reset-mfa"
                    ? `${target?.username} is signed out everywhere and asked to enrol again (lost device).`
                    : mode.kind === "password"
                      ? `${target?.username} is signed out of other sessions once the password changes.`
                      : target?.username}
            </DialogDescription>
          </DialogHeader>

          {error ? <Alert variant="error">{error}</Alert> : null}

          {mode.kind === "create" ? (
            <>
              <Field label="Username" htmlFor="user-username">
                <Input id="user-username" autoComplete="off" value={username} onChange={(event) => setUsername(event.target.value)} required data-testid="user-username" />
              </Field>
              <Field label="Display name" htmlFor="user-name">
                <Input id="user-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Optional" data-testid="user-name" />
              </Field>
            </>
          ) : null}
          {mode.kind === "name" ? (
            <Field label="Display name" htmlFor="user-name">
              <Input id="user-name" value={name} onChange={(event) => setName(event.target.value)} required autoFocus data-testid="user-name" />
            </Field>
          ) : null}
          {mode.kind === "create" || mode.kind === "password" ? (
            <Field label={mode.kind === "create" ? "Password" : "New password"} htmlFor="user-password" hint={password.length > 0 && issues.length > 0 ? `Needs: ${issues.join(", ")}.` : "At least 12 characters, not containing the username."}>
              <Input id="user-password" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required data-testid="user-password" />
            </Field>
          ) : null}
          {mode.kind === "create" || mode.kind === "role" ? (
            <Field label="Role" htmlFor="user-role" hint="Viewers read, operators run and approve, administrators manage the platform.">
              <SimpleSelect id="user-role" value={role} onValueChange={(value) => setRole(value as Role)} options={ROLES.map((item) => ({ value: item, label: item }))} testId="user-role" />
            </Field>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant={destructive ? "destructive" : "default"} loading={busy} disabled={!valid} data-testid="user-submit">
              {mode.kind === "create" ? "Create user" : mode.kind === "delete" ? "Delete account" : mode.kind === "reset-mfa" ? "Reset second factor" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
