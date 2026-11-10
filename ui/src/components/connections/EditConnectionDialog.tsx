import * as React from "react";
import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Alert, Spinner } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import type { Connection, ConnectionCatalog } from "@/types";
import { ConnectionForm } from "./ConnectionForm";
import { describeApiError, type ErrorInfo } from "./errors";
import { configPatch, initialValues, splitValues, validateValues, type FormValue, type FormValues } from "./form";
import { providerMeta } from "./providers";

export interface EditConnectionDialogProps {
  connection: Connection | null;
  catalog: ConnectionCatalog | null;
  onOpenChange: (open: boolean) => void;
  secretsAvailable: boolean;
  existingNames: string[];
  onSaved: (connection: Connection) => void;
}

/** Rename and change the non-secret configuration; stored secrets can only be replaced, never read. */
export function EditConnectionDialog({ connection, catalog, onOpenChange, secretsAvailable, existingNames, onSaved }: EditConnectionDialogProps) {
  const { toast } = useToast();
  const method = connection && catalog ? (catalog[connection.provider]?.methods.find((item) => item.key === connection.auth_method) ?? null) : null;
  const [name, setName] = React.useState("");
  const [values, setValues] = React.useState<FormValues>({});
  const [replacing, setReplacing] = React.useState<string[]>([]);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [apiError, setApiError] = React.useState<ErrorInfo | null>(null);
  const [busy, setBusy] = React.useState(false);

  const connectionId = connection?.id;
  React.useEffect(() => {
    if (!connection) return;
    setName(connection.name);
    setValues(method ? initialValues(method.fields, connection.config) : {});
    setReplacing([]);
    setErrors({});
    setApiError(null);
    setBusy(false);
    // Reset when another connection is opened or the catalog arrives, not on every list refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionId, method]);

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

  function replace(key: string, on: boolean) {
    setReplacing((current) => (on ? Array.from(new Set([...current, key])) : current.filter((item) => item !== key)));
    if (!on) {
      setValues((current) => ({ ...current, [key]: "" }));
      clearError(key);
    }
  }

  async function submit() {
    if (!connection || !method) return;
    const secretOptions = { storedSecrets: connection.secret_fields, replacing };
    const nextErrors = validateValues(connection.provider, method, values, secretOptions);
    const trimmed = name.trim();
    if (!trimmed) nextErrors.name = "Name is required.";
    else if (trimmed.length > 80) nextErrors.name = "Keep the name under 80 characters.";
    else if (existingNames.some((item) => item.toLowerCase() === trimmed.toLowerCase() && item.toLowerCase() !== connection.name.toLowerCase())) nextErrors.name = "A connection with this name already exists.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    const body: { name?: string; config?: Record<string, unknown>; secret?: Record<string, unknown> } = {};
    if (trimmed !== connection.name) body.name = trimmed;
    const patch = configPatch(connection.provider, method, values, connection.config);
    if (patch) body.config = patch;
    const { secret } = splitValues(connection.provider, method, values, secretOptions);
    if (Object.keys(secret).length > 0) body.secret = secret;
    if (!body.name && !body.config && !body.secret) {
      onOpenChange(false);
      return;
    }

    setBusy(true);
    setApiError(null);
    try {
      const updated = await api.updateConnection(connection.id, body);
      toast({
        title: "Connection updated",
        description: body.config || body.secret ? "Status reset to unverified. Run a test to confirm the new settings." : `Renamed to ${updated.name}.`,
        variant: "success",
      });
      onSaved(updated);
      onOpenChange(false);
    } catch (exc) {
      setApiError(describeApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={connection !== null} onOpenChange={(open) => !open && !busy && onOpenChange(false)}>
      <DialogContent size="lg" className="max-h-[88vh] overflow-y-auto" data-testid="edit-connection-dialog">
        <DialogHeader>
          <DialogTitle>Edit {connection?.name}</DialogTitle>
          <DialogDescription>
            {connection ? `${connection.provider_label ?? providerMeta(connection.provider, catalog).label} · ${connection.method_label ?? method?.label ?? connection.auth_method}. ` : ""}
            Changing the configuration or a secret resets the status to unverified.
          </DialogDescription>
        </DialogHeader>
        <div className="mt-4 space-y-4">
          {apiError ? (
            <Alert variant="error" title={apiError.title} testId="edit-error">
              <p className="break-words">{apiError.message}</p>
            </Alert>
          ) : null}
          {connection && !method ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Spinner /> Loading the catalog…
            </div>
          ) : null}
          {connection && method ? (
            <>
              <Field
                label={
                  <span>
                    Name{" "}
                    <span className="text-destructive" aria-hidden>
                      *
                    </span>
                  </span>
                }
                htmlFor="edit-name"
                error={errors.name}
              >
                <Input
                  id="edit-name"
                  value={name}
                  onChange={(event) => {
                    setName(event.target.value);
                    clearError("name");
                  }}
                  maxLength={80}
                  autoComplete="off"
                  aria-invalid={!!errors.name || undefined}
                  disabled={busy}
                  data-testid="edit-field-name"
                />
              </Field>
              <ConnectionForm
                provider={connection.provider}
                method={method}
                values={values}
                onChange={update}
                errors={errors}
                mode="edit"
                storedSecrets={connection.secret_fields}
                replacing={replacing}
                onReplace={replace}
                secretsAvailable={secretsAvailable}
                disabled={busy}
                idPrefix="edit"
              />
            </>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy} disabled={!method} data-testid="edit-submit">
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
