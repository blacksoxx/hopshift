import { describe, expect, it } from "vitest";
import { CATALOG } from "./test-utils";
import { identitySummary, isKnownProvider, monogram, providerMeta, sortProviders, terraformEnvNames } from "./providers";

describe("providerMeta", () => {
  it("keeps the hand-written tint and blurb for known providers and takes the label from the catalog", () => {
    const aws = providerMeta("aws", CATALOG);
    expect(aws.known).toBe(true);
    expect(aws.label).toBe("Amazon Web Services");
    expect(aws.tile).toContain("#ff9900");
    expect(aws.blurb).toMatch(/Access keys/);
    expect(providerMeta("aws", { ...CATALOG, aws: { ...CATALOG.aws, label: "AWS (GovCloud)" } }).label).toBe("AWS (GovCloud)");
  });

  it("renders providers it does not know from the key and the catalog", () => {
    const proxmox = providerMeta("proxmox", CATALOG);
    expect(proxmox.known).toBe(false);
    expect(proxmox.label).toBe("Proxmox VE");
    expect(proxmox.short).toBe("Pr");
    expect(proxmox.blurb).toBe("API token.");
    expect(proxmox.tile).not.toMatch(/#[0-9a-f]{6}/i);

    const bare = providerMeta("nutanix_prism");
    expect(bare.label).toBe("Nutanix Prism");
    expect(bare.short).toBe("NP");
    expect(bare.blurb).toMatch(/catalog/);
    expect(isKnownProvider("nutanix_prism")).toBe(false);
  });

  it("derives a two-character monogram from any key", () => {
    expect(monogram("proxmox")).toBe("Pr");
    expect(monogram("k8s")).toBe("K8");
    expect(monogram("vmware-cloud")).toBe("VC");
    expect(monogram("x")).toBe("X");
    expect(monogram("")).toBe("?");
  });

  it("sorts known providers first, then unknown ones alphabetically", () => {
    expect(sortProviders(["zz", "proxmox", "gcp", "aws"])).toEqual(["aws", "gcp", "proxmox", "zz"]);
  });
});

describe("identitySummary", () => {
  it("uses the provider's telling key when it knows the provider", () => {
    expect(identitySummary({ provider: "aws", last_check: { identity: { account: "123", arn: "arn:aws:iam::123:user/x" } } })).toBe("arn:aws:iam::123:user/x");
    expect(identitySummary({ provider: "gcp", last_check: { identity: { principal: "sa@p.iam", project_id: "p" } } })).toBe("p");
  });

  it("falls back to the first two scalar values for unknown providers", () => {
    expect(identitySummary({ provider: "proxmox", last_check: { identity: { cluster: { name: "lab" }, node: "pve1", version: "8.2", nodes: 3 } } })).toBe("pve1 · 8.2");
    expect(identitySummary({ provider: "proxmox", last_check: { identity: { only: "one" } } })).toBe("one");
    expect(identitySummary({ provider: "proxmox", last_check: { identity: { nested: { a: 1 } } } })).toBeNull();
    expect(identitySummary({ provider: "proxmox", last_check: null })).toBeNull();
  });
});

describe("terraformEnvNames", () => {
  it("lists the variables for known providers and methods", () => {
    const names = (terraformEnvNames({ provider: "aws", auth_method: "access_keys", config: { region: "eu-west-1" }, secret_fields: ["secret_access_key", "session_token"] }) ?? []).map((item) => item.name);
    expect(names).toEqual(["AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]);
    expect(terraformEnvNames({ provider: "azure", auth_method: "device_code", config: {}, secret_fields: [] })).toBeNull();
    expect((terraformEnvNames({ provider: "openstack", auth_method: "clouds_yaml", config: { cloud: "lab" }, secret_fields: [] }) ?? []).map((item) => item.name)).toEqual(["OS_CLOUD"]);
  });

  it("returns undefined for providers that are not in the map", () => {
    expect(terraformEnvNames({ provider: "proxmox", auth_method: "api_token", config: { host: "x" }, secret_fields: ["secret"] })).toBeUndefined();
  });
});
