import * as React from "react";
import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Alert } from "@/components/ui/misc";
import { useAuth } from "@/providers/AuthProvider";
import { AuthLayout } from "./LoginPage";

export function passwordIssues(password: string, username: string): string[] {
  const issues: string[] = [];
  if (password.length < 12) issues.push("at least 12 characters");
  if (username && password.toLowerCase().includes(username.toLowerCase())) issues.push("must not contain the username");
  return issues;
}

export function SetupPage() {
  const { login } = useAuth();
  const [username, setUsername] = React.useState("admin");
  const [name, setName] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const issues = passwordIssues(password, username);
  const mismatch = confirm.length > 0 && confirm !== password;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (issues.length > 0 || mismatch) return;
    setBusy(true);
    setError(null);
    try {
      await api.setup(username.trim(), password, name.trim() || username.trim());
      // login() updates the auth state; the PublicOnly guard then redirects to the dashboard.
      // No explicit navigate here: a late navigate would yank the user away from wherever
      // they already went.
      await login(username.trim(), password);
    } catch (exc) {
      setError((exc as Error).message || "Setup failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Create the first administrator" subtitle="This account manages users, connections and settings. You can enable multi-factor authentication right after.">
      <form onSubmit={submit} className="space-y-4" data-testid="setup-form">
        {error ? <Alert variant="error">{error}</Alert> : null}
        <Field label="Username" htmlFor="setup-username">
          <Input id="setup-username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required data-testid="setup-username" />
        </Field>
        <Field label="Display name" htmlFor="setup-name">
          <Input id="setup-name" autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Optional" data-testid="setup-name" />
        </Field>
        <Field label="Password" htmlFor="setup-password" hint={password.length > 0 && issues.length > 0 ? `Needs: ${issues.join(", ")}.` : "At least 12 characters."}>
          <Input id="setup-password" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required data-testid="setup-password" />
        </Field>
        <Field label="Confirm password" htmlFor="setup-confirm" error={mismatch ? "Passwords do not match." : undefined}>
          <Input id="setup-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} required data-testid="setup-confirm" />
        </Field>
        <Button type="submit" className="w-full" loading={busy} disabled={issues.length > 0 || mismatch || !confirm} data-testid="setup-submit">
          Create account and continue
        </Button>
      </form>
    </AuthLayout>
  );
}
