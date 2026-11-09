import type { ConnectionField, ConnectionMethod } from "@/types";

/** Form state: strings for every input (numbers included), booleans for switches. */
export type FormValue = string | boolean;
export type FormValues = Record<string, FormValue>;

type Condition = (values: FormValues) => boolean;

/**
 * Fields that only apply for a given base method. The catalog lists every field of a method;
 * the server validates the relevant ones (see the method validators in vma/connections/models.py).
 */
const VISIBLE_WHEN: Record<string, Record<string, Condition>> = {
  "aws/assume_role": {
    access_key_id: (values) => values.base_method === "access_keys",
    secret_access_key: (values) => values.base_method === "access_keys",
    session_token: (values) => values.base_method === "access_keys",
    profile: (values) => values.base_method === "profile",
    shared_credentials_file: (values) => values.base_method === "profile",
    config_file: (values) => values.base_method === "profile",
  },
  "gcp/impersonation": {
    credentials_file: (values) => values.base_method === "adc",
    key_json: (values) => values.base_method === "service_account_key",
  },
};

/** Optional in the catalog but required by the server whenever they are relevant. */
const REQUIRED_WHEN_VISIBLE: Record<string, string[]> = {
  "aws/assume_role": ["access_key_id", "secret_access_key", "profile"],
  "gcp/impersonation": ["key_json"],
};

export function fieldVisible(provider: string, methodKey: string, field: ConnectionField, values: FormValues): boolean {
  const condition = VISIBLE_WHEN[`${provider}/${methodKey}`]?.[field.key];
  return condition ? condition(values) : true;
}

export function fieldRequired(provider: string, methodKey: string, field: ConnectionField, values: FormValues): boolean {
  if (field.required) return true;
  const conditional = REQUIRED_WHEN_VISIBLE[`${provider}/${methodKey}`] ?? [];
  return conditional.includes(field.key) && fieldVisible(provider, methodKey, field, values);
}

export function isBlank(value: FormValue | undefined): boolean {
  return value === undefined || value === null || (typeof value === "string" && value.trim() === "");
}

/** Initial form values: stored config first, then catalog defaults. Secret fields always start empty. */
export function initialValues(fields: ConnectionField[], existing: Record<string, unknown> = {}): FormValues {
  const values: FormValues = {};
  for (const field of fields) {
    if (field.secret) {
      values[field.key] = "";
      continue;
    }
    const raw = existing[field.key] ?? field.default;
    if (field.type === "boolean") values[field.key] = raw === true || raw === "true";
    else values[field.key] = raw === undefined || raw === null ? "" : String(raw);
  }
  return values;
}

export interface SecretOptions {
  /** Secret fields already stored on the server (edit mode). */
  storedSecrets?: string[];
  /** Stored secret fields the user chose to replace. */
  replacing?: string[];
}

function keptSecret(field: ConnectionField, options: SecretOptions): boolean {
  return field.secret && (options.storedSecrets ?? []).includes(field.key) && !(options.replacing ?? []).includes(field.key);
}

/** Client-side validation mirroring the catalog rules: required, numeric, listed options, one-of pairs. */
export function validateValues(provider: string, method: ConnectionMethod, values: FormValues, options: SecretOptions = {}): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of method.fields) {
    if (!fieldVisible(provider, method.key, field, values)) continue;
    if (keptSecret(field, options)) continue;
    const value = values[field.key];
    if (field.type === "boolean") continue;
    if (fieldRequired(provider, method.key, field, values) && isBlank(value)) {
      errors[field.key] = `${field.label} is required.`;
    } else if (field.type === "number" && !isBlank(value) && Number.isNaN(Number(value))) {
      errors[field.key] = "Enter a number.";
    } else if (field.type === "select" && !isBlank(value) && field.options && !field.options.some((option) => option.value === value)) {
      errors[field.key] = "Choose one of the listed options.";
    } else if (typeof value === "string" && value.length > 65536) {
      errors[field.key] = "This value is too long.";
    }
  }
  if (provider === "azure" && method.key === "oidc") {
    const tokenField = method.fields.find((field) => field.key === "oidc_token");
    const tokenPresent = (tokenField && keptSecret(tokenField, options)) || !isBlank(values.oidc_token);
    if (!tokenPresent && isBlank(values.oidc_token_file_path)) {
      const message = "Provide an OIDC token or a token file path.";
      errors.oidc_token ??= message;
      errors.oidc_token_file_path ??= message;
    }
  }
  return errors;
}

/** Split form values into the `config` and `secret` request bodies, dropping blanks and hidden fields. */
export function splitValues(provider: string, method: ConnectionMethod, values: FormValues, options: SecretOptions = {}): { config: Record<string, unknown>; secret: Record<string, string> } {
  const config: Record<string, unknown> = {};
  const secret: Record<string, string> = {};
  for (const field of method.fields) {
    if (!fieldVisible(provider, method.key, field, values)) continue;
    const value = values[field.key];
    if (field.secret) {
      if (keptSecret(field, options) || isBlank(value)) continue;
      secret[field.key] = field.type === "textarea" ? String(value) : String(value).trim();
      continue;
    }
    if (field.type === "boolean") {
      config[field.key] = value === true;
    } else if (isBlank(value)) {
      continue;
    } else if (field.type === "number") {
      config[field.key] = Number(value);
    } else {
      config[field.key] = field.type === "textarea" ? String(value) : String(value).trim();
    }
  }
  return { config, secret };
}

/**
 * The PATCH body for `config`: changed keys with their new value, keys that were cleared as null
 * (the server removes them). Returns null when nothing changed, so the status is not reset for free.
 */
export function configPatch(provider: string, method: ConnectionMethod, values: FormValues, current: Record<string, unknown>): Record<string, unknown> | null {
  const { config } = splitValues(provider, method, values);
  const patch: Record<string, unknown> = {};
  for (const field of method.fields) {
    if (field.secret) continue;
    const next = config[field.key];
    const previous = current[field.key];
    if (next === undefined) {
      if (previous !== undefined && previous !== null) patch[field.key] = null;
    } else if (next !== previous) {
      patch[field.key] = next;
    }
  }
  return Object.keys(patch).length > 0 ? patch : null;
}

/** Human label for a stored config value (option labels for selects, Yes/No for booleans). */
export function displayValue(field: ConnectionField, value: unknown): string {
  if (value === undefined || value === null || value === "") return "";
  if (field.type === "boolean") return value === true || value === "true" ? "Yes" : "No";
  if (field.type === "select") return field.options?.find((option) => option.value === String(value))?.label ?? String(value);
  return String(value);
}
