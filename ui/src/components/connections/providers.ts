import { titleCase } from "@/lib/format";
import type { Connection, ConnectionCatalog, ConnectionMethod } from "@/types";

/** The connections guide in the repository (the API does not serve the docs folder). */
export const DOCS_URL = "https://github.com/blacksoxx/hopshift/blob/main/docs/connections.md";

export interface ProviderMeta {
  key: string;
  /** Human name: the catalog's label when a catalog is given, the hand-written one for known providers, Title Case of the key otherwise. */
  label: string;
  /** Short monogram for the icon tile. */
  short: string;
  /** One line about the authentication methods; derived from the catalog for providers the UI does not know. */
  blurb: string;
  /** Tile classes. Brand tints for known providers only; every other colour comes from the theme tokens. */
  tile: string;
  /** False for providers the UI has no hand-written metadata for (plugins): they render generically. */
  known: boolean;
}

/**
 * Hand-written metadata for the providers that ship with hopshift. Labels come from the catalog
 * at runtime; these are fallbacks for lists rendered before the catalog has loaded. Anything not
 * listed here (a target plugin's provider, for example) renders with a generic monogram tile.
 */
const KNOWN: Record<string, Omit<ProviderMeta, "key" | "known">> = {
  aws: {
    label: "Amazon Web Services",
    short: "aws",
    blurb: "Access keys, a named profile, an assumed role, IAM Identity Center or the instance role.",
    tile: "bg-[#ff9900]/15 text-[#8a5200] dark:text-[#ffb547]",
  },
  azure: {
    label: "Microsoft Azure",
    short: "Az",
    blurb: "Service principals, managed identity, workload identity federation, the Azure CLI or device-code sign-in.",
    tile: "bg-[#0078d4]/12 text-[#005ea6] dark:text-[#62b3ff]",
  },
  gcp: {
    label: "Google Cloud",
    short: "G",
    blurb: "Service account keys, application default credentials, impersonation or workload identity federation.",
    tile: "bg-[#4285f4]/12 text-[#2a67cc] dark:text-[#8ab4ff]",
  },
  openstack: {
    label: "OpenStack",
    short: "OS",
    blurb: "A Keystone password, an application credential or a named cloud from clouds.yaml.",
    tile: "bg-[#ed1944]/12 text-[#b8102f] dark:text-[#ff6b86]",
  },
};

export const KNOWN_PROVIDERS: string[] = Object.keys(KNOWN);
const GENERIC_TILE = "bg-muted text-foreground/80 ring-1 ring-inset ring-border";

export function isKnownProvider(key: string): boolean {
  return Object.prototype.hasOwnProperty.call(KNOWN, key);
}

/**
 * Two-letter monogram derived from a provider key: initials of the words for multi-word keys
 * (`vmware-cloud` → `VC`), otherwise the first two characters with the first upper-cased
 * (`proxmox` → `Pr`, `k8s` → `K8`).
 */
export function monogram(key: string): string {
  const words = String(key ?? "")
    .split(/[^a-z0-9]+/i)
    .filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length > 1) return words.slice(0, 2).map((word) => word[0].toUpperCase()).join("");
  const word = words[0];
  return word[0].toUpperCase() + word.slice(1, 2).toLowerCase();
}

/** Blurb for a provider the UI has no copy for: the method labels from the catalog. */
function catalogBlurb(key: string, catalog?: ConnectionCatalog | null): string {
  const methods = catalog?.[key]?.methods ?? [];
  if (methods.length === 0) return "Authentication methods from the connection catalog.";
  return methods.map((item) => item.label).join(", ") + ".";
}

export function providerMeta(key: string, catalog?: ConnectionCatalog | null): ProviderMeta {
  const catalogLabel = catalog?.[key]?.label;
  const known = KNOWN[key];
  if (known) return { key, known: true, ...known, label: catalogLabel ?? known.label };
  return { key, known: false, label: catalogLabel ?? titleCase(key), short: monogram(key), blurb: catalogBlurb(key, catalog), tile: GENERIC_TILE };
}

/** Sort provider keys in catalog order (AWS, Azure, GCP, OpenStack, then anything unknown alphabetically). */
export function sortProviders(keys: string[]): string[] {
  const order = new Map(KNOWN_PROVIDERS.map((item, index) => [item, index]));
  return [...keys].sort((a, b) => (order.get(a) ?? 99) - (order.get(b) ?? 99) || a.localeCompare(b));
}

/** The most telling identity key per known provider, in order of preference. */
const IDENTITY_KEYS: Record<string, string[]> = {
  aws: ["arn", "account"],
  azure: ["subscription_name", "subscription_id"],
  gcp: ["project_id", "principal"],
  openstack: ["project_name", "project_id"],
};

function scalarText(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

/**
 * One line that identifies what a verified connection reaches: the provider's most telling
 * identity field for known providers, the first two scalar values for everything else.
 */
export function identitySummary(connection: Pick<Connection, "provider" | "last_check">): string | null {
  const identity = connection.last_check?.identity;
  if (!identity) return null;
  for (const key of IDENTITY_KEYS[connection.provider] ?? []) {
    const value = scalarText(identity[key]);
    if (value) return value;
  }
  const scalars = Object.values(identity).map(scalarText).filter((value): value is string => value !== null);
  return scalars.length > 0 ? scalars.slice(0, 2).join(" · ") : null;
}

export function hasDeviceFlow(connection: Pick<Connection, "auth_method" | "device_flow">): boolean {
  return connection.device_flow === true || connection.auth_method === "sso" || connection.auth_method === "device_code";
}

export function methodNeedsSecrets(method: Pick<ConnectionMethod, "fields">): boolean {
  return method.fields.some((field) => field.secret);
}

export const NOT_TERRAFORM_READY =
  "Device-code sign-in verifies access but cannot hand credentials to Terraform. Plan and apply need a service principal, managed identity, workload identity or CLI login.";

export const TERRAFORM_ENV_UNKNOWN = "The variables this provider hands to Terraform are not listed here; see the target's documentation.";

export interface EnvVar {
  name: string;
  note?: string;
}

type EnvConnection = Pick<Connection, "provider" | "auth_method" | "config" | "secret_fields">;
type EnvResolver = (connection: EnvConnection, has: (key: string) => boolean, secrets: Set<string>) => EnvVar[] | null;

const temporary = (source: string): EnvVar[] => [
  { name: "AWS_ACCESS_KEY_ID", note: `temporary, ${source}` },
  { name: "AWS_SECRET_ACCESS_KEY", note: "temporary" },
  { name: "AWS_SESSION_TOKEN", note: "temporary" },
];

/**
 * Names of the environment variables Terraform receives from a connection, keyed by provider
 * (values are resolved on the server at plan/apply time and never shown). Mirrors `terraform_env`
 * in hopshift/services/connections/*. A resolver returns null for methods that cannot drive
 * Terraform; providers without an entry are plugins the UI knows nothing about.
 */
const TERRAFORM_ENV: Record<string, EnvResolver> = {
  aws: ({ auth_method: method }, has, secrets) => {
    const vars: EnvVar[] = [{ name: "AWS_REGION" }, { name: "AWS_DEFAULT_REGION" }];
    if (has("endpoint_url")) vars.push({ name: "AWS_ENDPOINT_URL" });
    switch (method) {
      case "access_keys":
        vars.push({ name: "AWS_ACCESS_KEY_ID" }, { name: "AWS_SECRET_ACCESS_KEY" });
        if (secrets.has("session_token")) vars.push({ name: "AWS_SESSION_TOKEN" });
        break;
      case "profile":
        vars.push({ name: "AWS_PROFILE" }, { name: "AWS_SDK_LOAD_CONFIG", note: "=1" });
        if (has("shared_credentials_file")) vars.push({ name: "AWS_SHARED_CREDENTIALS_FILE" });
        if (has("config_file")) vars.push({ name: "AWS_CONFIG_FILE" });
        break;
      case "assume_role":
        vars.push(...temporary("from the assumed role"));
        break;
      case "sso":
        vars.push(...temporary("from the Identity Center role"));
        break;
      case "web_identity":
        vars.push({ name: "AWS_ROLE_ARN" }, { name: "AWS_WEB_IDENTITY_TOKEN_FILE" }, { name: "AWS_ROLE_SESSION_NAME" });
        break;
      default:
        // "environment": the process credentials are inherited; only the region is set.
        break;
    }
    return vars;
  },
  azure: ({ auth_method: method, config }, has, secrets) => {
    if (method === "device_code") return null;
    const vars: EnvVar[] = [{ name: "ARM_SUBSCRIPTION_ID" }, { name: "ARM_TENANT_ID" }];
    if (has("environment") && config.environment !== "public") vars.push({ name: "ARM_ENVIRONMENT" });
    switch (method) {
      case "service_principal_secret":
        vars.push({ name: "ARM_CLIENT_ID" }, { name: "ARM_CLIENT_SECRET" });
        break;
      case "service_principal_certificate":
        vars.push({ name: "ARM_CLIENT_ID" }, { name: "ARM_CLIENT_CERTIFICATE", note: "base64 of the PEM, or the PFX as pasted" });
        if (secrets.has("certificate_password")) vars.push({ name: "ARM_CLIENT_CERTIFICATE_PASSWORD" });
        break;
      case "managed_identity":
        vars.push({ name: "ARM_USE_MSI", note: "=true" });
        if (has("client_id")) vars.push({ name: "ARM_CLIENT_ID" });
        break;
      case "oidc":
        vars.push({ name: "ARM_USE_OIDC", note: "=true" }, { name: "ARM_CLIENT_ID" });
        if (secrets.has("oidc_token")) vars.push({ name: "ARM_OIDC_TOKEN" });
        else if (has("oidc_token_file_path")) vars.push({ name: "ARM_OIDC_TOKEN_FILE_PATH" });
        break;
      case "cli":
        vars.push({ name: "ARM_USE_CLI", note: "=true" });
        break;
      default:
        break;
    }
    return vars;
  },
  gcp: ({ auth_method: method, config }, has) => {
    const vars: EnvVar[] = [{ name: "GOOGLE_PROJECT" }];
    if (has("region")) vars.push({ name: "GOOGLE_REGION" });
    if (has("zone")) vars.push({ name: "GOOGLE_ZONE" });
    switch (method) {
      case "service_account_key":
        vars.push({ name: "GOOGLE_CREDENTIALS", note: "the key JSON" });
        break;
      case "adc":
        if (has("credentials_file")) vars.push({ name: "GOOGLE_APPLICATION_CREDENTIALS" });
        break;
      case "impersonation":
        vars.push({ name: "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT" });
        if (config.base_method === "service_account_key") vars.push({ name: "GOOGLE_CREDENTIALS", note: "the base key JSON" });
        else if (has("credentials_file")) vars.push({ name: "GOOGLE_APPLICATION_CREDENTIALS" });
        break;
      case "workload_identity_federation":
        vars.push({ name: "GOOGLE_CREDENTIALS", note: "the credential configuration JSON" });
        break;
      default:
        break;
    }
    return vars;
  },
  openstack: ({ auth_method: method }, has) => {
    const vars: EnvVar[] = [];
    if (has("auth_url")) vars.push({ name: "OS_AUTH_URL" });
    if (has("region_name")) vars.push({ name: "OS_REGION_NAME" });
    if (has("interface")) vars.push({ name: "OS_INTERFACE" });
    switch (method) {
      case "password":
        vars.push(
          { name: "OS_USERNAME" },
          { name: "OS_PASSWORD" },
          { name: "OS_PROJECT_NAME" },
          { name: "OS_USER_DOMAIN_NAME" },
          { name: "OS_PROJECT_DOMAIN_NAME" },
          { name: "OS_IDENTITY_API_VERSION", note: "=3" },
        );
        break;
      case "application_credential":
        vars.push(
          { name: "OS_AUTH_TYPE", note: "=v3applicationcredential" },
          { name: "OS_APPLICATION_CREDENTIAL_ID" },
          { name: "OS_APPLICATION_CREDENTIAL_SECRET" },
          { name: "OS_IDENTITY_API_VERSION", note: "=3" },
        );
        break;
      case "clouds_yaml":
        vars.push({ name: "OS_CLOUD" });
        if (has("clouds_yaml_path")) vars.push({ name: "OS_CLIENT_CONFIG_FILE" });
        break;
      default:
        break;
    }
    return vars;
  },
};

/**
 * Terraform environment variable names for a connection: a list for known providers, null when
 * the method cannot drive Terraform, undefined when the provider is not in the map (see the
 * target's documentation).
 */
export function terraformEnvNames(connection: EnvConnection): EnvVar[] | null | undefined {
  const resolver = TERRAFORM_ENV[connection.provider];
  if (!resolver) return undefined;
  const secrets = new Set(connection.secret_fields ?? []);
  const has = (key: string) => {
    const value = connection.config[key];
    return value !== undefined && value !== null && String(value).trim() !== "";
  };
  return resolver(connection, has, secrets);
}
