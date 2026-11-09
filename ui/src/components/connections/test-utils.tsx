import * as React from "react";
import { MemoryRouter } from "react-router-dom";
import { render, type RenderOptions } from "@testing-library/react";
import { ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Connection, ConnectionCatalog, ConnectionMethod } from "@/types";

/** jsdom lacks a few DOM APIs the Radix primitives call. */
export function installDomPolyfills() {
  if (typeof window === "undefined") return;
  if (!("ResizeObserver" in window)) {
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    Object.assign(window, { ResizeObserver });
  }
  const proto = Element.prototype as Element & { hasPointerCapture?: () => boolean; setPointerCapture?: () => void; releasePointerCapture?: () => void; scrollIntoView?: () => void };
  if (!proto.hasPointerCapture) proto.hasPointerCapture = () => false;
  if (!proto.setPointerCapture) proto.setPointerCapture = () => {};
  if (!proto.releasePointerCapture) proto.releasePointerCapture = () => {};
  if (!proto.scrollIntoView) proto.scrollIntoView = () => {};
}

export function renderWithProviders(ui: React.ReactElement, options: RenderOptions & { route?: string } = {}) {
  const { route = "/", ...rest } = options;
  return render(
    <TooltipProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </ToastProvider>
    </TooltipProvider>,
    rest,
  );
}

/** A synthetic method with one field of every catalog type. */
export const ALL_TYPES_METHOD: ConnectionMethod = {
  key: "all_types",
  label: "Every field type",
  description: "Fixture",
  terraform_ready: true,
  device_flow: false,
  fields: [
    { key: "name_text", label: "Text field", type: "text", required: true, secret: false, help: "Some help", placeholder: "type here" },
    { key: "pw", label: "Password field", type: "password", required: true, secret: true },
    { key: "pem", label: "Textarea field", type: "textarea", required: false, secret: true, help: "PEM or JSON" },
    {
      key: "choice",
      label: "Select field",
      type: "select",
      required: true,
      secret: false,
      options: [
        { value: "a", label: "Option A" },
        { value: "b", label: "Option B" },
      ],
    },
    { key: "flag", label: "Boolean field", type: "boolean", required: false, secret: false, default: false },
    { key: "count", label: "Number field", type: "number", required: false, secret: false },
  ],
};

const AWS_REGION = { key: "region", label: "Region", type: "text" as const, required: true, secret: false, placeholder: "eu-west-1", help: "Default region for Terraform (AWS_REGION)." };
const AWS_ENDPOINT = { key: "endpoint_url", label: "Endpoint URL", type: "text" as const, required: false, secret: false, help: "Optional." };

/** A trimmed copy of the real catalog (shape of GET /api/connections/methods). */
export const CATALOG: ConnectionCatalog = {
  aws: {
    label: "Amazon Web Services",
    methods: [
      {
        key: "access_keys",
        label: "Access keys",
        description: "A long-lived or temporary access key pair.",
        terraform_ready: true,
        device_flow: false,
        fields: [
          { key: "access_key_id", label: "Access key ID", type: "text", required: true, secret: false, placeholder: "AKIA..." },
          { key: "secret_access_key", label: "Secret access key", type: "password", required: true, secret: true },
          { key: "session_token", label: "Session token", type: "password", required: false, secret: true, help: "Optional. Only for temporary credentials." },
          AWS_REGION,
          AWS_ENDPOINT,
        ],
      },
      {
        key: "environment",
        label: "Process environment",
        description: "Credentials the process already has: environment variables, an instance role, ECS task role or IRSA.",
        terraform_ready: true,
        device_flow: false,
        fields: [AWS_REGION, AWS_ENDPOINT],
      },
      {
        key: "sso",
        label: "IAM Identity Center (SSO)",
        description: "Device authorization through sso-oidc.",
        terraform_ready: true,
        device_flow: true,
        fields: [
          { key: "start_url", label: "Start URL", type: "text", required: true, secret: false },
          { key: "sso_region", label: "SSO region", type: "text", required: true, secret: false },
          { key: "account_id", label: "Account ID", type: "text", required: true, secret: false },
          { key: "role_name", label: "Permission set / role name", type: "text", required: true, secret: false },
          AWS_REGION,
          AWS_ENDPOINT,
        ],
      },
    ],
  },
  azure: {
    label: "Microsoft Azure",
    methods: [
      {
        key: "device_code",
        label: "Device code sign-in",
        description: "Interactive sign-in with a user account. Verifies access only.",
        terraform_ready: false,
        device_flow: true,
        fields: [
          { key: "subscription_id", label: "Subscription ID", type: "text", required: true, secret: false },
          { key: "tenant_id", label: "Tenant ID", type: "text", required: true, secret: false },
          {
            key: "environment",
            label: "Cloud environment",
            type: "select",
            required: false,
            secret: false,
            default: "public",
            options: [
              { value: "public", label: "Azure public cloud" },
              { value: "usgovernment", label: "Azure US Government" },
            ],
          },
          { key: "client_id", label: "Client ID", type: "text", required: false, secret: false, default: "04b07795-8ddb-461a-bbee-02f9e1bf7b46" },
        ],
      },
    ],
  },
};

export function makeConnection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: "c1",
    name: "lab",
    provider: "aws",
    auth_method: "access_keys",
    provider_label: "Amazon Web Services",
    method_label: "Access keys",
    config: { access_key_id: "AKIAEXAMPLE", region: "eu-west-1" },
    status: "unverified",
    last_checked_at: null,
    last_check: null,
    created_by: "admin",
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    has_secret: true,
    secret_fields: ["secret_access_key"],
    terraform_ready: true,
    device_flow: false,
    ...overrides,
  };
}
