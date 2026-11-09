import type { Connection, ConnectionMethod } from "@/types";

/** The connections guide in the repository (the API does not serve the docs folder). */
export const DOCS_URL = "https://github.com/blacksoxx/vmware-migration-agent/blob/main/docs/connections.md";

export interface ProviderMeta {
  key: string;
  label: string;
  /** Short monogram for the icon tile. */
  short: string;
  blurb: string;
  /** Brand tint for the icon tile only; every other colour comes from the theme tokens. */
  tile: string;
}

export const PROVIDERS: ProviderMeta[] = [
  {
    key: "aws",
    label: "Amazon Web Services",
    short: "aws",
    blurb: "Access keys, a named profile, an assumed role, IAM Identity Center or the instance role.",
    tile: "bg-[#ff9900]/15 text-[#8a5200] dark:text-[#ffb547]",
  },
  {
    key: "azure",
    label: "Microsoft Azure",
    short: "Az",
    blurb: "Service principals, managed identity, workload identity federation, the Azure CLI or device-code sign-in.",
    tile: "bg-[#0078d4]/12 text-[#005ea6] dark:text-[#62b3ff]",
  },
  {
    key: "gcp",
    label: "Google Cloud",
    short: "G",
    blurb: "Service account keys, application default credentials, impersonation or workload identity federation.",
    tile: "bg-[#4285f4]/12 text-[#2a67cc] dark:text-[#8ab4ff]",
  },
  {
    key: "openstack",
    label: "OpenStack",
    short: "OS",
    blurb: "A Keystone password, an application credential or a named cloud from clouds.yaml.",
    tile: "bg-[#ed1944]/12 text-[#b8102f] dark:text-[#ff6b86]",
  },
];

export function providerMeta(key: string): ProviderMeta {
  return PROVIDERS.find((item) => item.key === key) ?? { key, label: key.toUpperCase(), short: key.slice(0, 2), blurb: "", tile: "bg-muted text-muted-foreground" };
}

/** Sort provider keys in catalog order (AWS, Azure, GCP, OpenStack, then anything unknown). */
export function sortProviders(keys: string[]): string[] {
  const order = new Map(PROVIDERS.map((item, index) => [item.key, index]));
  return [...keys].sort((a, b) => (order.get(a) ?? 99) - (order.get(b) ?? 99) || a.localeCompare(b));
}

/** The most telling identity key per provider, in order of preference. */
const IDENTITY_KEYS: Record<string, string[]> = {
  aws: ["arn", "account"],
  azure: ["subscription_name", "subscription_id"],
  gcp: ["project_id", "principal"],
  openstack: ["project_name", "project_id"],
};

export function identitySummary(connection: Pick<Connection, "provider" | "last_check">): string | null {
  const identity = connection.last_check?.identity;
  if (!identity) return null;
  for (const key of IDENTITY_KEYS[connection.provider] ?? []) {
    const value = identity[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  const first = Object.values(identity).find((value) => typeof value === "string" && value.trim());
  return typeof first === "string" ? first : null;
}

export function hasDeviceFlow(connection: Pick<Connection, "auth_method" | "device_flow">): boolean {
  return connection.device_flow === true || connection.auth_method === "sso" || connection.auth_method === "device_code";
}

export function methodNeedsSecrets(method: Pick<ConnectionMethod, "fields">): boolean {
  return method.fields.some((field) => field.secret);
}

export const NOT_TERRAFORM_READY =
  "Device-code sign-in verifies access but cannot hand credentials to Terraform. Plan and apply need a service principal, managed identity, workload identity or CLI login.";

export interface EnvVar {
  name: string;
  note?: string;
}

/**
 * Names of the environment variables Terraform receives from a connection (values are resolved on
 * the server at plan/apply time and never shown). Mirrors `terraform_env` in vma/connections/*.
 * Returns null for methods that cannot drive Terraform.
 */
export function terraformEnvNames(connection: Pick<Connection, "provider" | "auth_method" | "config" | "secret_fields">): EnvVar[] | null {
  const { provider, auth_method: method, config } = connection;
  const secrets = new Set(connection.secret_fields ?? []);
  const has = (key: string) => {
    const value = config[key];
    return value !== undefined && value !== null && String(value).trim() !== "";
  };
  const temporary = (source: string): EnvVar[] => [
    { name: "AWS_ACCESS_KEY_ID", note: `temporary, ${source}` },
    { name: "AWS_SECRET_ACCESS_KEY", note: "temporary" },
    { name: "AWS_SESSION_TOKEN", note: "temporary" },
  ];

  switch (provider) {
    case "aws": {
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
    }
    case "azure": {
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
    }
    case "gcp": {
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
    }
    case "openstack": {
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
    }
    default:
      return [];
  }
}
