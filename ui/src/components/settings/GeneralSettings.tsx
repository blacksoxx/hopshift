import * as React from "react";
import { Lock, RotateCcw, Save, SlidersHorizontal } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Alert, EmptyState, Skeleton } from "@/components/ui/misc";
import { SimpleSelect } from "@/components/ui/select";
import { Checkbox, ToggleRow } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { Hint } from "@/components/ui/tooltip";
import { useAuth } from "@/providers/AuthProvider";
import { cn } from "@/lib/utils";
import { pluralize } from "@/lib/format";
import type { SettingSpec } from "@/types";

export type SettingsDraft = Record<string, unknown>;

/** Shape an effective value the way the matching form control holds it. */
export function controlValue(spec: SettingSpec, value: unknown): unknown {
  switch (spec.type) {
    case "boolean":
      return value === true || value === "true";
    case "integer":
      return value === null || value === undefined || value === "" ? "" : String(value);
    case "list":
      return Array.isArray(value) ? value.map(String) : [];
    default:
      return value === null || value === undefined ? "" : String(value);
  }
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Only the keys whose draft differs from the effective value, typed for the API. */
export function changedValues(schema: SettingSpec[], effective: Record<string, unknown>, draft: SettingsDraft): Record<string, unknown> {
  const changes: Record<string, unknown> = {};
  for (const spec of schema) {
    if (!(spec.key in draft)) continue;
    const base = controlValue(spec, effective[spec.key]);
    const next = draft[spec.key];
    if (same(base, next)) continue;
    changes[spec.key] = spec.type === "integer" ? Number(next) : next;
  }
  return changes;
}

/** Group specs by `group`, keeping the order in which groups first appear. */
export function groupSchema(schema: SettingSpec[]): { group: string; specs: SettingSpec[] }[] {
  const groups: { group: string; specs: SettingSpec[] }[] = [];
  for (const spec of schema) {
    let bucket = groups.find((item) => item.group === spec.group);
    if (!bucket) {
      bucket = { group: spec.group, specs: [] };
      groups.push(bucket);
    }
    bucket.specs.push(spec);
  }
  return groups;
}

function invalidIntegers(schema: SettingSpec[], draft: SettingsDraft): string[] {
  return schema
    .filter((spec) => spec.type === "integer" && spec.key in draft)
    .filter((spec) => {
      const raw = String(draft[spec.key] ?? "");
      if (raw.trim() === "") return true;
      const value = Number(raw);
      if (!Number.isInteger(value)) return true;
      if (spec.minimum !== null && value < spec.minimum) return true;
      if (spec.maximum !== null && value > spec.maximum) return true;
      return false;
    })
    .map((spec) => spec.key);
}

export function GeneralSettings() {
  const { can } = useAuth();
  const admin = can("admin");
  const { toast } = useToast();
  const settings = useAsync(() => api.settings(), []);
  const [draft, setDraft] = React.useState<SettingsDraft>({});
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const data = settings.data;
  const changes = React.useMemo(() => (data ? changedValues(data.schema, data.effective, draft) : {}), [data, draft]);
  const invalid = React.useMemo(() => (data ? invalidIntegers(data.schema, draft) : []), [data, draft]);
  const changedCount = Object.keys(changes).length;
  const dirty = changedCount > 0;

  const valueFor = (spec: SettingSpec): unknown => (spec.key in draft ? draft[spec.key] : controlValue(spec, data?.effective[spec.key]));
  const set = (key: string, value: unknown) => setDraft((current) => ({ ...current, [key]: value }));

  async function save() {
    if (!data || !dirty) return;
    setSaving(true);
    setError(null);
    try {
      const next = await api.updateSettings(changes);
      settings.setData(next);
      setDraft({});
      toast({ title: "Settings saved", description: `${pluralize(changedCount, "setting")} updated.`, variant: "success" });
    } catch (exc) {
      setError((exc as Error).message || "Could not save the settings.");
    } finally {
      setSaving(false);
    }
  }

  async function reset(spec: SettingSpec) {
    setError(null);
    try {
      const next = await api.updateSettings({ [spec.key]: null });
      settings.setData(next);
      setDraft((current) => {
        const copy = { ...current };
        delete copy[spec.key];
        return copy;
      });
      toast({ title: "Override removed", description: `${spec.label} follows config.yaml again.`, variant: "success" });
    } catch (exc) {
      setError((exc as Error).message || "Could not reset the setting.");
    }
  }

  if (settings.loading && !data) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-40" />
        ))}
      </div>
    );
  }

  if (!data) {
    return (
      <EmptyState
        icon={Lock}
        title={admin ? "Could not load the settings" : "Only administrators can view platform settings"}
        description={settings.error ?? "The settings endpoint did not answer."}
        action={
          admin ? (
            <Button variant="outline" onClick={() => void settings.reload()}>
              Retry
            </Button>
          ) : undefined
        }
        testId="settings-unavailable"
      />
    );
  }

  return (
    <div className="space-y-4">
      {!admin ? (
        <Alert variant="info" title="Read only">
          You can see the effective platform settings. Only administrators can change them; ask one if a value needs to move.
        </Alert>
      ) : (
        <p className="text-sm text-muted-foreground">
          Values below are applied on top of <span className="font-mono text-[12.5px]">config.yaml</span> for new runs. Everything else stays file-only and is changed with a deployment.
        </p>
      )}
      {error ? (
        <Alert variant="error" title="The settings were not saved" testId="settings-error">
          {error}
        </Alert>
      ) : null}

      {groupSchema(data.schema).map(({ group, specs }) => (
        <Card key={group} data-testid={`settings-group-${group.toLowerCase().replace(/\s+/g, "-")}`}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SlidersHorizontal className="size-4 text-muted-foreground" /> {group}
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 pt-1 sm:grid-cols-2">
            {specs.map((spec) => (
              <SettingField key={spec.key} spec={spec} value={valueFor(spec)} overridden={spec.key in data.overrides} invalid={invalid.includes(spec.key)} disabled={!admin || saving} onChange={(value) => set(spec.key, value)} onReset={() => void reset(spec)} />
            ))}
          </CardContent>
        </Card>
      ))}

      {admin ? (
        <div className={cn("sticky bottom-0 z-10 -mx-1 flex items-center justify-between gap-3 rounded-xl border border-border bg-background/90 px-4 py-3 shadow-[0_-4px_16px_rgb(0_0_0/0.04)] backdrop-blur transition-opacity", !dirty && "opacity-80")} data-testid="settings-footer">
          <div className="text-sm text-muted-foreground" data-testid="settings-dirty">
            {dirty ? `${pluralize(changedCount, "unsaved change")}.` : "No unsaved changes."}
            {invalid.length > 0 ? <span className="ml-1 text-destructive">Fix the highlighted numbers first.</span> : null}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDraft({})} disabled={!dirty || saving}>
              Discard
            </Button>
            <Button size="sm" onClick={() => void save()} loading={saving} disabled={!dirty || invalid.length > 0} data-testid="settings-save">
              <Save /> Save changes
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SettingField({ spec, value, overridden, invalid, disabled, onChange, onReset }: { spec: SettingSpec; value: unknown; overridden: boolean; invalid: boolean; disabled: boolean; onChange: (value: unknown) => void; onReset: () => void }) {
  const id = `setting-${spec.key}`;
  const testId = `setting-${spec.key}`;
  const header = (withLabel: boolean) => (
    <div className="flex items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-2">
        {withLabel ? <Label htmlFor={id}>{spec.label}</Label> : null}
        {overridden ? (
          <Badge variant="info" data-testid={`${testId}-overridden`}>
            overridden
          </Badge>
        ) : null}
      </div>
      {overridden && !disabled ? (
        <Hint content="Reset to the value in config.yaml">
          <Button type="button" variant="ghost" size="icon-sm" className="-my-1 text-muted-foreground" onClick={onReset} aria-label={`Reset ${spec.label} to file value`} data-testid={`${testId}-reset`}>
            <RotateCcw />
          </Button>
        </Hint>
      ) : null}
    </div>
  );

  if (spec.type === "boolean") {
    return (
      <div className="space-y-1.5 sm:col-span-2">
        {overridden ? header(false) : null}
        <ToggleRow id={id} label={spec.label} hint={spec.help} checked={Boolean(value)} onCheckedChange={onChange} disabled={disabled} testId={testId} />
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {header(true)}
      {spec.type === "choice" ? (
        <SimpleSelect id={id} value={String(value ?? "")} onValueChange={onChange} options={spec.options.map((option) => ({ value: option, label: option }))} placeholder="Not set" disabled={disabled} testId={testId} />
      ) : spec.type === "integer" ? (
        <Input id={id} type="number" inputMode="numeric" value={String(value ?? "")} min={spec.minimum ?? undefined} max={spec.maximum ?? undefined} step={1} onChange={(event) => onChange(event.target.value)} disabled={disabled} aria-invalid={invalid || undefined} className={cn("tabular", invalid && "border-destructive focus-visible:ring-destructive/40")} data-testid={testId} />
      ) : spec.type === "list" ? (
        <div className="flex flex-wrap gap-x-4 gap-y-2 rounded-md border border-border bg-card px-3 py-2" data-testid={testId}>
          {spec.options.map((option) => {
            const selected = Array.isArray(value) && (value as string[]).includes(option);
            const optionId = `${id}-${option}`;
            return (
              <div key={option} className="flex items-center gap-2 text-sm">
                <Checkbox id={optionId} checked={selected} disabled={disabled} onCheckedChange={(checked) => onChange(checked ? [...((value as string[]) ?? []), option] : ((value as string[]) ?? []).filter((item) => item !== option))} data-testid={`${testId}-${option}`} />
                <label htmlFor={optionId} className="cursor-pointer">
                  {option.replace(/_/g, " ")}
                </label>
              </div>
            );
          })}
        </div>
      ) : (
        <Input id={id} value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} disabled={disabled} data-testid={testId} />
      )}
      <p className="text-xs text-muted-foreground">
        {spec.help}
        {spec.type === "integer" && (spec.minimum !== null || spec.maximum !== null) ? (
          <span className="tabular">
            {" "}
            ({spec.minimum ?? "…"}–{spec.maximum ?? "…"})
          </span>
        ) : null}
      </p>
    </div>
  );
}

