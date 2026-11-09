import * as React from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "motion/react";
import { KeyRound, ShieldCheck, Sparkles, Workflow } from "lucide-react";
import { ApiError, api } from "@/api";
import { Wordmark } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Alert, Separator } from "@/components/ui/misc";
import { useAuth } from "@/providers/AuthProvider";

export function AuthLayout({ children, title, subtitle }: { children: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden overflow-hidden border-r border-border bg-sidebar lg:flex lg:flex-col lg:justify-between lg:p-12">
        <Wordmark />
        <div className="space-y-8">
          <h2 className="max-w-md text-balance text-3xl font-semibold tracking-tight">From vSphere discovery to deployed, compliant cloud infrastructure.</h2>
          <ul className="space-y-4 text-sm text-muted-foreground">
            {[
              { icon: Workflow, title: "Deterministic pipeline", text: "Discovery JSON becomes a canonical model, then Terraform that is validated by terraform, tflint and OPA." },
              { icon: ShieldCheck, title: "Compliance built in", text: "CIS, SOC 2 and HIPAA controls are checked on every run, with evidence in a tamper-evident audit log." },
              { icon: Sparkles, title: "AI where it helps", text: "Optional model-written review notes and generation modes; never in the gate." },
            ].map((item) => (
              <li key={item.title} className="flex gap-3">
                <item.icon className="mt-0.5 size-4 shrink-0 text-primary" />
                <div>
                  <div className="font-medium text-foreground">{item.title}</div>
                  <div>{item.text}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="text-xs text-muted-foreground">Open source · MIT</div>
        <div className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full bg-primary/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-24 -left-16 size-72 rounded-full bg-info/10 blur-3xl" />
      </div>
      <div className="flex items-center justify-center p-6">
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }} className="w-full max-w-sm space-y-6">
          <div className="lg:hidden">
            <Wordmark />
          </div>
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {subtitle ? <p className="text-sm text-muted-foreground">{subtitle}</p> : null}
          </div>
          {children}
        </motion.div>
      </div>
    </div>
  );
}

export function LoginPage() {
  const { login, status } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [totp, setTotp] = React.useState("");
  const [mfaStep, setMfaStep] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password, mfaStep ? totp.trim() : undefined);
      const next = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("next");
      navigate(next && next.startsWith("/") ? next : "/", { replace: true });
    } catch (exc) {
      const apiError = exc as ApiError;
      const body = apiError.body as { mfa_required?: boolean } | undefined;
      if (apiError.status === 401 && body && typeof body === "object" && body.mfa_required) {
        setMfaStep(true);
        setError(mfaStep ? "That code was not accepted." : null);
      } else {
        setError(apiError.message || "Sign-in failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={mfaStep ? "Two-factor code" : "Sign in"} subtitle={mfaStep ? "Enter the 6-digit code from your authenticator app, or a recovery code." : "Use your platform account."}>
      <form onSubmit={submit} className="space-y-4" data-testid="login-form">
        {error ? <Alert variant="error">{error}</Alert> : null}
        {!mfaStep ? (
          <>
            <Field label="Username" htmlFor="username">
              <Input id="username" autoComplete="username" autoFocus value={username} onChange={(event) => setUsername(event.target.value)} required data-testid="login-username" />
            </Field>
            <Field label="Password" htmlFor="password">
              <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required data-testid="login-password" />
            </Field>
          </>
        ) : (
          <Field label="Code" htmlFor="totp">
            <Input id="totp" inputMode="numeric" autoComplete="one-time-code" autoFocus value={totp} onChange={(event) => setTotp(event.target.value)} required className="font-mono tracking-[0.3em]" data-testid="login-totp" />
          </Field>
        )}
        <Button type="submit" className="w-full" loading={busy} data-testid="login-submit">
          {mfaStep ? "Verify" : "Sign in"}
        </Button>
        {mfaStep ? (
          <Button type="button" variant="ghost" className="w-full" onClick={() => { setMfaStep(false); setTotp(""); setError(null); }}>
            Back
          </Button>
        ) : null}
      </form>
      {status?.oidc_enabled && !mfaStep ? (
        <>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <Separator className="flex-1" /> or <Separator className="flex-1" />
          </div>
          <Button variant="outline" className="w-full" asChild>
            <a href={api.oidcLoginUrl()} data-testid="sso-login">
              <KeyRound /> Continue with single sign-on
            </a>
          </Button>
        </>
      ) : null}
    </AuthLayout>
  );
}
