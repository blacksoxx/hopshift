import * as React from "react";
import { useSearchParams } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { Download, KeyRound, ShieldCheck, ShieldOff } from "lucide-react";
import { api } from "@/api";
import { passwordIssues } from "@/pages/SetupPage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Alert, CodeBlock, Spinner } from "@/components/ui/misc";
import { Checkbox } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/providers/AuthProvider";
import { cn, downloadText } from "@/lib/utils";
import { formatDateTime } from "@/lib/format";
import { CopyButton } from "./CopyButton";
import { RoleBadge } from "./UsersPanel";
import { FeatureUnavailable, errorMessage, isUnavailable } from "./unavailable";

export function ProfilePanel() {
  const { user, status, refresh } = useAuth();
  const [params, setParams] = useSearchParams();
  const enrollRequested = params.get("enroll") === "1";
  const [enrollOpen, setEnrollOpen] = React.useState(enrollRequested);
  const [disableOpen, setDisableOpen] = React.useState(false);

  if (!user) return null;
  const authDisabled = user.auth_kind === "disabled";
  const oidc = user.auth_kind === "oidc";
  const mustEnroll = enrollRequested || Boolean(user.mfa_enrollment_required);
  const initials = (user.name || user.username)
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  async function enrolled() {
    await refresh();
    if (enrollRequested) setParams({}, { replace: true });
  }

  return (
    <div className="space-y-4">
      {mustEnroll && !authDisabled ? (
        <Alert variant="warning" title="A second factor is required" testId="mfa-required">
          Policy requires every account to enrol multi-factor authentication before continuing. Scan the code with an authenticator app, confirm one code and keep the recovery codes somewhere safe.
        </Alert>
      ) : null}

      <Card>
        <CardHeader className="flex-row items-center gap-4">
          <div className="flex size-12 shrink-0 items-center justify-center rounded-full bg-primary/15 text-base font-semibold text-primary">{initials}</div>
          <div className="min-w-0">
            <CardTitle className="truncate">{user.name || user.username}</CardTitle>
            <CardDescription className="font-mono text-[12.5px]">{user.username}</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="pt-2">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4" data-testid="profile-card">
            <div>
              <dt className="text-xs text-muted-foreground">Role</dt>
              <dd className="mt-1">
                <RoleBadge role={user.role} />
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Sign-in</dt>
              <dd className={cn("mt-1", !authDisabled && !oidc && "capitalize")}>{authDisabled ? "Anonymous (auth disabled)" : oidc ? "Single sign-on" : user.auth_kind}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Second factor</dt>
              <dd className="mt-1">
                {user.mfa_enabled ? (
                  <Badge variant="success" dot data-testid="mfa-status">
                    enabled
                  </Badge>
                ) : (
                  <Badge variant="muted" data-testid="mfa-status">
                    not enrolled
                  </Badge>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Last sign-in</dt>
              <dd className="mt-1 text-muted-foreground">{user.last_login_at ? formatDateTime(user.last_login_at) : "–"}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {authDisabled ? (
        <FeatureUnavailable what="Password and second-factor settings" testId="profile-unavailable" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <KeyRound className="size-4 text-muted-foreground" /> Password
              </CardTitle>
              <CardDescription>{oidc ? "Managed by your identity provider." : "Changing it signs out your other sessions."}</CardDescription>
            </CardHeader>
            <CardContent className="pt-2">
              {oidc ? (
                <Alert variant="info" testId="password-oidc">
                  This account signs in through single sign-on; change the password with your identity provider.
                </Alert>
              ) : (
                <ChangePasswordForm username={user.username} />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-muted-foreground" /> Second factor
              </CardTitle>
              <CardDescription>Time-based one-time codes from an authenticator app{status?.mfa_policy === "required" ? ", required by policy" : ""}.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 pt-2">
              {user.mfa_enabled ? (
                <>
                  <p className="text-sm text-muted-foreground">Enrolled. Sign-in asks for a code after the password; recovery codes work when the device is lost.</p>
                  <Button variant="outline" onClick={() => setDisableOpen(true)} data-testid="mfa-disable">
                    <ShieldOff /> Disable
                  </Button>
                </>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">Not enrolled. Adds a second check to your password; takes about a minute with any TOTP app.</p>
                  <Button onClick={() => setEnrollOpen(true)} data-testid="mfa-enable">
                    <ShieldCheck /> Enable
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <MfaEnrollDialog open={enrollOpen} onOpenChange={setEnrollOpen} onEnrolled={() => void enrolled()} />
      <MfaDisableDialog open={disableOpen} onOpenChange={setDisableOpen} onDisabled={() => void refresh()} />
    </div>
  );
}

function ChangePasswordForm({ username }: { username: string }) {
  const { toast } = useToast();
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [unavailable, setUnavailable] = React.useState(false);

  const issues = passwordIssues(next, username);
  const mismatch = confirm.length > 0 && confirm !== next;
  const valid = current.length > 0 && next.length > 0 && issues.length === 0 && confirm === next;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      await api.changePassword(current, next);
      toast({ title: "Password changed", description: "Your other sessions were signed out.", variant: "success" });
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (exc) {
      if (isUnavailable(exc)) setUnavailable(true);
      else setError(errorMessage(exc));
    } finally {
      setBusy(false);
    }
  }

  if (unavailable) {
    return (
      <Alert variant="info" testId="password-unavailable">
        Password changes are not available on this server.
      </Alert>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3" data-testid="password-form">
      {error ? <Alert variant="error">{error}</Alert> : null}
      <Field label="Current password" htmlFor="pw-current">
        <Input id="pw-current" type="password" autoComplete="current-password" value={current} onChange={(event) => setCurrent(event.target.value)} required data-testid="password-current" />
      </Field>
      <Field label="New password" htmlFor="pw-next" hint={next.length > 0 && issues.length > 0 ? `Needs: ${issues.join(", ")}.` : "At least 12 characters, not containing the username."}>
        <Input id="pw-next" type="password" autoComplete="new-password" value={next} onChange={(event) => setNext(event.target.value)} required data-testid="password-new" />
      </Field>
      <Field label="Confirm new password" htmlFor="pw-confirm" error={mismatch ? "Passwords do not match." : undefined}>
        <Input id="pw-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} required data-testid="password-confirm" />
      </Field>
      <div className="flex justify-end">
        <Button type="submit" loading={busy} disabled={!valid} data-testid="password-submit">
          Change password
        </Button>
      </div>
    </form>
  );
}

type EnrollStep = "loading" | "scan" | "recovery" | "unavailable" | "error";

function MfaEnrollDialog({ open, onOpenChange, onEnrolled }: { open: boolean; onOpenChange: (open: boolean) => void; onEnrolled: () => void }) {
  const [step, setStep] = React.useState<EnrollStep>("loading");
  const [setup, setSetup] = React.useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = React.useState("");
  const [codes, setCodes] = React.useState<string[]>([]);
  const [saved, setSaved] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setStep("loading");
    setSetup(null);
    setCode("");
    setCodes([]);
    setSaved(false);
    setError(null);
    api
      .mfaEnroll()
      .then((result) => {
        if (cancelled) return;
        setSetup(result);
        setStep("scan");
      })
      .catch((exc: unknown) => {
        if (cancelled) return;
        if (isUnavailable(exc)) setStep("unavailable");
        else {
          setError(errorMessage(exc));
          setStep("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    if (code.trim().length < 6) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.mfaConfirm(code.trim());
      setCodes(result.recovery_codes);
      setStep("recovery");
    } catch (exc) {
      setError(errorMessage(exc) || "That code was not accepted. Codes rotate every 30 seconds; try the next one.");
    } finally {
      setBusy(false);
    }
  }

  function close(next: boolean) {
    if (next) return;
    // Once enrolled, the recovery codes must be acknowledged before the dialog goes away.
    if (step === "recovery" && !saved) return;
    if (busy) return;
    onOpenChange(false);
    if (step === "recovery") onEnrolled();
  }

  const recoveryText = codes.join("\n");

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent size="md" data-testid="mfa-enroll-dialog">
        <DialogHeader>
          <DialogTitle>{step === "recovery" ? "Save your recovery codes" : "Enable multi-factor authentication"}</DialogTitle>
          <DialogDescription>
            {step === "recovery" ? "Each code signs you in once if the authenticator is unavailable. They are shown only now." : "Scan the code with an authenticator app (1Password, Authy, Google Authenticator…) and confirm with the 6-digit code it shows."}
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4">
          {step === "loading" ? (
            <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
              <Spinner /> Preparing your secret…
            </div>
          ) : step === "unavailable" ? (
            <Alert variant="info" testId="mfa-unavailable">
              Multi-factor authentication is not available on this server.
            </Alert>
          ) : step === "error" ? (
            <Alert variant="error">{error}</Alert>
          ) : step === "scan" && setup ? (
            <form onSubmit={confirm} className="grid gap-5 sm:grid-cols-[auto_1fr]" data-testid="mfa-scan">
              <div className="flex flex-col items-center gap-2">
                <div className="rounded-lg border border-border bg-white p-3">
                  <QRCodeSVG value={setup.otpauth_uri} size={168} level="M" data-testid="mfa-qr" />
                </div>
                <span className="text-[11px] text-muted-foreground">otpauth QR code</span>
              </div>
              <div className="min-w-0 space-y-4">
                <div className="space-y-1.5">
                  <div className="text-sm font-medium">Or enter the secret manually</div>
                  <div className="flex items-center gap-2">
                    <code className="min-w-0 flex-1 truncate rounded-md border border-border bg-muted/50 px-2.5 py-1.5 font-mono text-[12.5px] tracking-wider" title={setup.secret} data-testid="mfa-secret">
                      {setup.secret}
                    </code>
                    <CopyButton text={setup.secret} label="Copy" size="sm" testId="mfa-secret-copy" />
                  </div>
                </div>
                {error ? <Alert variant="error">{error}</Alert> : null}
                <Field label="6-digit code" htmlFor="mfa-code" hint="From the app, after scanning.">
                  <Input id="mfa-code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]*" maxLength={8} autoFocus value={code} onChange={(event) => setCode(event.target.value.replace(/\s+/g, ""))} className="font-mono text-base tracking-[0.3em]" data-testid="mfa-code" />
                </Field>
                <DialogFooter className="mt-0">
                  <Button type="button" variant="outline" onClick={() => close(false)} disabled={busy}>
                    Cancel
                  </Button>
                  <Button type="submit" loading={busy} disabled={code.trim().length < 6} data-testid="mfa-confirm">
                    Confirm and enable
                  </Button>
                </DialogFooter>
              </div>
            </form>
          ) : step === "recovery" ? (
            <div className="space-y-4" data-testid="mfa-recovery">
              <Alert variant="warning" title="Keep these somewhere safe">
                Treat them like passwords. Anyone with a code and your password can sign in.
              </Alert>
              <CodeBlock className="grid grid-cols-2 gap-x-6 gap-y-1 text-[13px] tracking-wider sm:grid-cols-3" testId="recovery-codes">
                {codes.map((item) => (
                  <span key={item}>{item}</span>
                ))}
              </CodeBlock>
              <div className="flex flex-wrap gap-2">
                <CopyButton text={recoveryText} label="Copy codes" testId="recovery-copy" />
                <Button variant="outline" size="sm" onClick={() => downloadText("vma-recovery-codes.txt", `${recoveryText}\n`)} data-testid="recovery-download">
                  <Download /> Download
                </Button>
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <Checkbox checked={saved} onCheckedChange={(value) => setSaved(value === true)} data-testid="recovery-saved" /> I saved these codes
              </label>
              <DialogFooter className="mt-0">
                <Button onClick={() => close(false)} disabled={!saved} data-testid="mfa-done">
                  Done
                </Button>
              </DialogFooter>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function MfaDisableDialog({ open, onOpenChange, onDisabled }: { open: boolean; onOpenChange: (open: boolean) => void; onDisabled: () => void }) {
  const { toast } = useToast();
  const [password, setPassword] = React.useState("");
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setPassword("");
      setCode("");
      setError(null);
    }
  }, [open]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.mfaDisable(password, code.trim());
      toast({ title: "Second factor disabled", description: "Sign-in asks for the password only.", variant: "warning" });
      onOpenChange(false);
      onDisabled();
    } catch (exc) {
      setError(errorMessage(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent size="sm">
        <form onSubmit={submit} className="space-y-4" data-testid="mfa-disable-dialog">
          <DialogHeader>
            <DialogTitle>Disable the second factor?</DialogTitle>
            <DialogDescription>Confirm with your password and a current code. Recovery codes are invalidated.</DialogDescription>
          </DialogHeader>
          {error ? <Alert variant="error">{error}</Alert> : null}
          <Field label="Password" htmlFor="mfa-disable-password">
            <Input id="mfa-disable-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required data-testid="mfa-disable-password" />
          </Field>
          <Field label="Current code" htmlFor="mfa-disable-code">
            <Input id="mfa-disable-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} required className="font-mono tracking-[0.3em]" data-testid="mfa-disable-code" />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
              Keep it on
            </Button>
            <Button type="submit" variant="destructive" loading={busy} disabled={!password || code.trim().length < 6} data-testid="mfa-disable-confirm">
              Disable
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

