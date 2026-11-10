import * as React from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "motion/react";
import { ArrowLeft, ArrowRight, Check, KeyRound, Lock, Smartphone } from "lucide-react";
import { api } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Alert, Skeleton, Spinner } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import type { Connection, ConnectionCatalog, ConnectionMethod, ConnectionTest } from "@/types";
import { ConnectionForm } from "./ConnectionForm";
import { ProviderIcon } from "./ProviderBadge";
import { TestResult } from "./TestResult";
import { describeApiError, type ErrorInfo } from "./errors";
import { initialValues, splitValues, validateValues, type FormValue, type FormValues } from "./form";
import { methodNeedsSecrets, providerMeta, sortProviders } from "./providers";

const STEPS = ["Provider", "Method", "Details"] as const;

export interface AddConnectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  catalog: ConnectionCatalog | null;
  secretsAvailable: boolean;
  existingNames: string[];
  /** Called after creation and again once the automatic test finishes, with the updated record. */
  onCreated: (connection: Connection) => void;
}

export function AddConnectionDialog({ open, onOpenChange, catalog, secretsAvailable, existingNames, onCreated }: AddConnectionDialogProps) {
  const navigate = useNavigate();
  const [step, setStep] = React.useState(0);
  const [provider, setProvider] = React.useState<string | null>(null);
  const [method, setMethod] = React.useState<ConnectionMethod | null>(null);
  const [name, setName] = React.useState("");
  const [values, setValues] = React.useState<FormValues>({});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [apiError, setApiError] = React.useState<ErrorInfo | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [created, setCreated] = React.useState<Connection | null>(null);
  const [testing, setTesting] = React.useState(false);
  const [result, setResult] = React.useState<ConnectionTest | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setStep(0);
    setProvider(null);
    setMethod(null);
    setName("");
    setValues({});
    setErrors({});
    setApiError(null);
    setBusy(false);
    setCreated(null);
    setTesting(false);
    setResult(null);
  }, [open]);

  const providers = catalog ? sortProviders(Object.keys(catalog)) : [];
  const methods = provider && catalog ? (catalog[provider]?.methods ?? []) : [];
  const providerLabel = provider ? (catalog?.[provider]?.label ?? providerMeta(provider).label) : "";

  function chooseProvider(key: string) {
    setProvider(key);
    setMethod(null);
    setStep(1);
  }

  function chooseMethod(item: ConnectionMethod) {
    setMethod(item);
    setValues(initialValues(item.fields));
    setErrors({});
    setApiError(null);
    setStep(2);
  }

  function clearError(key: string) {
    setErrors((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function update(key: string, value: FormValue) {
    setValues((current) => ({ ...current, [key]: value }));
    clearError(key);
  }

  async function submit() {
    if (!provider || !method) return;
    const nextErrors = validateValues(provider, method, values);
    const trimmed = name.trim();
    if (!trimmed) nextErrors.name = "Name is required.";
    else if (trimmed.length > 80) nextErrors.name = "Keep the name under 80 characters.";
    else if (existingNames.some((item) => item.toLowerCase() === trimmed.toLowerCase())) nextErrors.name = "A connection with this name already exists.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setBusy(true);
    setApiError(null);
    const { config, secret } = splitValues(provider, method, values);
    let connection: Connection;
    try {
      connection = await api.createConnection({ name: trimmed, provider, auth_method: method.key, config, secret });
    } catch (exc) {
      setApiError(describeApiError(exc));
      setBusy(false);
      return;
    }
    setBusy(false);
    setCreated(connection);
    onCreated(connection);
    setStep(3);
    setTesting(true);
    try {
      const check = await api.testConnection(connection.id);
      setResult(check);
      onCreated({ ...connection, status: check.ok ? "ok" : "failed", last_checked_at: check.checked_at, last_check: { identity: check.identity, message: check.message } });
    } catch (exc) {
      setResult({ ok: false, identity: {}, message: describeApiError(exc).message, checked_at: new Date().toISOString() });
    } finally {
      setTesting(false);
    }
  }

  function close() {
    if (busy) return;
    onOpenChange(false);
  }

  function openCreated() {
    if (!created) return;
    onOpenChange(false);
    navigate(`/connections/${created.id}`);
  }

  const description =
    step === 0
      ? "Pick the cloud this connection authenticates to."
      : step === 1
        ? `How should the platform authenticate to ${providerLabel}?`
        : step === 2
          ? `${providerLabel} · ${method?.label ?? ""}`
          : "The connection was created; its credentials are being verified.";

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent size="lg" className="max-h-[88vh] overflow-y-auto" data-testid="add-connection-dialog">
        <DialogHeader>
          <DialogTitle>{step === 3 ? "Connection created" : "Add a connection"}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        {step < 3 ? (
          <ol className="mb-4 mt-4 flex items-center gap-2 text-xs" aria-label="Steps">
            {STEPS.map((label, index) => (
              <li key={label} className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => index < step && setStep(index)}
                  disabled={index >= step || busy}
                  className={cn("flex items-center gap-1.5 rounded-full px-2 py-0.5 transition-colors", index === step ? "bg-primary/10 text-primary" : index < step ? "text-foreground hover:bg-accent" : "text-muted-foreground")}
                  data-testid={`add-step-${index}`}
                >
                  <span className={cn("flex size-4 items-center justify-center rounded-full border text-[10px] font-semibold", index < step ? "border-primary bg-primary text-primary-foreground" : index === step ? "border-primary" : "border-border")}>
                    {index < step ? <Check className="size-2.5" /> : index + 1}
                  </span>
                  {label}
                </button>
                {index < STEPS.length - 1 ? <span className="h-px w-4 bg-border" aria-hidden /> : null}
              </li>
            ))}
          </ol>
        ) : (
          <div className="mt-4" />
        )}

        <motion.div key={step} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.14 }}>
          {step === 0 ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {!catalog
                ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[76px]" />)
                : providers.map((key) => {
                    const meta = providerMeta(key);
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => chooseProvider(key)}
                        className={cn("flex items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent/50", provider === key ? "border-primary bg-primary/5" : "border-border")}
                        data-testid={`provider-${key}`}
                      >
                        <ProviderIcon provider={key} size="lg" />
                        <span className="min-w-0">
                          <span className="block text-sm font-medium">{catalog[key]?.label ?? meta.label}</span>
                          <span className="block text-xs text-muted-foreground">{meta.blurb}</span>
                        </span>
                      </button>
                    );
                  })}
            </div>
          ) : null}

          {step === 1 ? (
            <div className="space-y-2">
              {methods.map((item) => {
                const needsSecrets = methodNeedsSecrets(item);
                const blocked = needsSecrets && !secretsAvailable;
                return (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => chooseMethod(item)}
                    disabled={blocked}
                    className={cn(
                      "flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors",
                      blocked ? "cursor-not-allowed opacity-55" : "hover:bg-accent/50",
                      method?.key === item.key ? "border-primary bg-primary/5" : "border-border",
                    )}
                    data-testid={`method-${item.key}`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-sm font-medium">{item.label}</span>
                        {item.terraform_ready ? <Badge variant="info">terraform ready</Badge> : <Badge variant="outline">verify only</Badge>}
                        {item.device_flow ? (
                          <Badge variant="secondary">
                            <Smartphone className="size-3" /> device sign-in
                          </Badge>
                        ) : null}
                        {needsSecrets ? (
                          <Badge variant={blocked ? "warning" : "muted"}>
                            <Lock className="size-3" /> {blocked ? "needs HOPSHIFT_SECRET_KEY" : "stores secrets"}
                          </Badge>
                        ) : null}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{item.description}</span>
                    </span>
                    <ArrowRight className="mt-1 size-4 shrink-0 text-muted-foreground" />
                  </button>
                );
              })}
            </div>
          ) : null}

          {step === 2 && provider && method ? (
            <div className="space-y-4">
              {apiError ? (
                <Alert variant="error" title={apiError.title} testId="add-error">
                  <p className="break-words">{apiError.message}</p>
                  {apiError.status === 503 ? <p className="mt-1">Set HOPSHIFT_SECRET_KEY on the server and restart it, or pick a method without secrets.</p> : null}
                </Alert>
              ) : null}
              <Field
                label={
                  <span>
                    Name{" "}
                    <span className="text-destructive" aria-hidden>
                      *
                    </span>
                  </span>
                }
                htmlFor="add-name"
                hint="Shown in lists and on run pages. Names are unique."
                error={errors.name}
              >
                <Input
                  id="add-name"
                  value={name}
                  onChange={(event) => {
                    setName(event.target.value);
                    clearError("name");
                  }}
                  placeholder={`${providerLabel} production`}
                  maxLength={80}
                  autoComplete="off"
                  aria-invalid={!!errors.name || undefined}
                  disabled={busy}
                  data-testid="connection-name"
                />
              </Field>
              <ConnectionForm provider={provider} method={method} values={values} onChange={update} errors={errors} secretsAvailable={secretsAvailable} disabled={busy} idPrefix="add" />
              {methodNeedsSecrets(method) ? (
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Lock className="size-3" /> Secret fields are encrypted at rest and never returned by the API.
                </p>
              ) : null}
            </div>
          ) : null}

          {step === 3 && created ? (
            <div className="space-y-4">
              <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-sm">
                <ProviderIcon provider={created.provider} />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{created.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {created.provider_label ?? providerLabel} · {created.method_label ?? method?.label}
                  </div>
                </div>
                <Badge variant="success" dot>
                  created
                </Badge>
              </div>
              {testing ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="add-testing">
                  <Spinner /> Verifying the credentials against the provider…
                </div>
              ) : result ? (
                <TestResult result={result} testId="connection-test-result" />
              ) : null}
            </div>
          ) : null}
        </motion.div>

        <DialogFooter>
          {step === 0 ? (
            <Button variant="outline" onClick={close}>
              Cancel
            </Button>
          ) : null}
          {step === 1 || step === 2 ? (
            <Button variant="ghost" onClick={() => setStep(step - 1)} disabled={busy} data-testid="add-back">
              <ArrowLeft /> Back
            </Button>
          ) : null}
          {step === 2 ? (
            <Button onClick={() => void submit()} loading={busy} data-testid="connection-submit">
              <KeyRound /> Create and test
            </Button>
          ) : null}
          {step === 3 ? (
            <>
              <Button variant="outline" onClick={close}>
                Close
              </Button>
              <Button onClick={openCreated} disabled={testing} data-testid="add-open">
                Open connection <ArrowRight />
              </Button>
            </>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
