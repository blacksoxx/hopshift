import * as React from "react";
import { Eye, EyeOff, Lock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { ToggleRow } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { ConnectionField, ConnectionMethod } from "@/types";
import { fieldRequired, fieldVisible, type FormValue, type FormValues } from "./form";

export interface ConnectionFormProps {
  provider: string;
  method: ConnectionMethod;
  values: FormValues;
  onChange: (key: string, value: FormValue) => void;
  errors?: Record<string, string>;
  /** Edit mode never shows stored secrets: each is listed as set or not set with a Replace action. */
  mode?: "create" | "edit";
  storedSecrets?: string[];
  replacing?: string[];
  onReplace?: (key: string, replace: boolean) => void;
  /** False when the server has no VMA_SECRET_KEY: secret inputs are disabled. */
  secretsAvailable?: boolean;
  disabled?: boolean;
  idPrefix?: string;
}

export function FieldLabel({ field, required }: { field: ConnectionField; required: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {field.label}
      {required ? (
        <span className="text-destructive" aria-hidden>
          *
        </span>
      ) : null}
      {field.secret ? <Lock className="size-3 text-muted-foreground" aria-label="stored encrypted" /> : null}
    </span>
  );
}

export function PasswordInput({
  id,
  name,
  value,
  onChange,
  placeholder,
  disabled,
  invalid,
  testId,
  className,
}: {
  id?: string;
  name?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  invalid?: boolean;
  testId?: string;
  className?: string;
}) {
  const [show, setShow] = React.useState(false);
  return (
    <div className={cn("relative", className)}>
      <Input
        id={id}
        name={name}
        type={show ? "text" : "password"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        aria-invalid={invalid || undefined}
        className="pr-10 font-mono text-[13px]"
        data-testid={testId}
        data-1p-ignore=""
        data-lpignore="true"
      />
      <button
        type="button"
        onClick={() => setShow((current) => !current)}
        disabled={disabled}
        aria-label={show ? "Hide value" : "Show value"}
        aria-pressed={show}
        className="absolute right-1 top-1/2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
        data-testid={testId ? `${testId}-toggle` : undefined}
      >
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  );
}

function StoredSecretRow({ field, stored, canReplace, disabled, onReplace }: { field: ConnectionField; stored: boolean; canReplace: boolean; disabled?: boolean; onReplace: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/40 px-3 py-2" data-testid={`secret-${field.key}`}>
      <div className="flex min-w-0 items-center gap-2 text-sm">
        <Lock className="size-4 shrink-0 text-muted-foreground" />
        {stored ? (
          <Badge variant="success" dot>
            set
          </Badge>
        ) : (
          <Badge variant="muted">not set</Badge>
        )}
        <span className="truncate text-xs text-muted-foreground">{stored ? "Stored encrypted; the value is never shown." : "No value stored."}</span>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={onReplace} disabled={disabled || !canReplace} data-testid={`replace-${field.key}`}>
        {stored ? "Replace" : "Set"}
      </Button>
    </div>
  );
}

/** Renders a method's catalog fields. Secret values are sent in `secret`, the rest in `config` (see form.ts). */
export function ConnectionForm({
  provider,
  method,
  values,
  onChange,
  errors = {},
  mode = "create",
  storedSecrets = [],
  replacing = [],
  onReplace,
  secretsAvailable = true,
  disabled = false,
  idPrefix = "connection",
}: ConnectionFormProps) {
  const visible = method.fields.filter((field) => fieldVisible(provider, method.key, field, values));
  return (
    <div className="space-y-4" data-testid="connection-form">
      {visible.map((field) => {
        const id = `${idPrefix}-${field.key}`;
        const required = fieldRequired(provider, method.key, field, values);
        const error = errors[field.key];
        const testId = `field-${field.key}`;
        const value = values[field.key];
        const stringValue = typeof value === "string" ? value : "";

        if (field.type === "boolean") {
          return (
            <ToggleRow
              key={field.key}
              id={id}
              label={<FieldLabel field={field} required={false} />}
              hint={field.help || undefined}
              checked={value === true}
              onCheckedChange={(checked) => onChange(field.key, checked)}
              disabled={disabled}
              testId={testId}
            />
          );
        }

        const isStored = storedSecrets.includes(field.key);
        const isReplacing = replacing.includes(field.key);
        if (field.secret && mode === "edit" && !isReplacing) {
          return (
            <Field key={field.key} label={<FieldLabel field={field} required={required} />} hint={secretsAvailable ? field.help || undefined : "Secrets cannot be stored until VMA_SECRET_KEY is set on the server."} error={error}>
              <StoredSecretRow field={field} stored={isStored} canReplace={secretsAvailable} disabled={disabled} onReplace={() => onReplace?.(field.key, true)} />
            </Field>
          );
        }

        const locked = disabled || (field.secret && !secretsAvailable);
        let control: React.ReactNode;
        switch (field.type) {
          case "password":
            control = <PasswordInput id={id} name={field.key} value={stringValue} onChange={(next) => onChange(field.key, next)} placeholder={field.placeholder} disabled={locked} invalid={!!error} testId={testId} />;
            break;
          case "textarea":
            control = (
              <Textarea
                id={id}
                name={field.key}
                value={stringValue}
                onChange={(event) => onChange(field.key, event.target.value)}
                rows={8}
                placeholder={field.placeholder || "Paste the contents here"}
                disabled={locked}
                autoComplete="off"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                aria-invalid={!!error || undefined}
                className="font-mono text-[12.5px] leading-relaxed"
                data-testid={testId}
              />
            );
            break;
          case "select":
            control = <SimpleSelect id={id} value={stringValue} onValueChange={(next) => onChange(field.key, next)} options={field.options ?? []} placeholder={field.placeholder || "Choose…"} disabled={locked} testId={testId} />;
            break;
          case "number":
            control = (
              <Input
                id={id}
                name={field.key}
                type="number"
                inputMode="decimal"
                value={stringValue}
                onChange={(event) => onChange(field.key, event.target.value)}
                placeholder={field.placeholder}
                disabled={locked}
                autoComplete="off"
                aria-invalid={!!error || undefined}
                data-testid={testId}
              />
            );
            break;
          default:
            control = (
              <Input
                id={id}
                name={field.key}
                value={stringValue}
                onChange={(event) => onChange(field.key, event.target.value)}
                placeholder={field.placeholder}
                disabled={locked}
                autoComplete="off"
                spellCheck={false}
                aria-invalid={!!error || undefined}
                data-testid={testId}
              />
            );
        }

        return (
          <Field key={field.key} htmlFor={id} label={<FieldLabel field={field} required={required} />} hint={field.help || undefined} error={error}>
            {mode === "edit" && field.secret ? (
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">{control}</div>
                <Button type="button" variant="ghost" size="sm" className="shrink-0" onClick={() => onReplace?.(field.key, false)} disabled={disabled} data-testid={`keep-${field.key}`}>
                  {isStored ? "Keep current" : "Cancel"}
                </Button>
              </div>
            ) : (
              control
            )}
          </Field>
        );
      })}
    </div>
  );
}
