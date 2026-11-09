import * as React from "react";
import { beforeAll, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConnectionForm } from "./ConnectionForm";
import { configPatch, initialValues, splitValues, validateValues, type FormValues } from "./form";
import { ALL_TYPES_METHOD, CATALOG, installDomPolyfills, makeConnection, renderWithProviders } from "./test-utils";

beforeAll(installDomPolyfills);

function CreateHarness() {
  const [values, setValues] = React.useState<FormValues>(() => initialValues(ALL_TYPES_METHOD.fields));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  return (
    <div>
      <ConnectionForm provider="test" method={ALL_TYPES_METHOD} values={values} onChange={(key, value) => setValues((current) => ({ ...current, [key]: value }))} errors={errors} />
      <button type="button" onClick={() => setErrors(validateValues("test", ALL_TYPES_METHOD, values))}>
        validate
      </button>
    </div>
  );
}

function EditHarness() {
  const method = CATALOG.aws.methods[0];
  const connection = makeConnection();
  const [values, setValues] = React.useState<FormValues>(() => initialValues(method.fields, connection.config));
  const [replacing, setReplacing] = React.useState<string[]>([]);
  return (
    <ConnectionForm
      provider="aws"
      method={method}
      values={values}
      onChange={(key, value) => setValues((current) => ({ ...current, [key]: value }))}
      mode="edit"
      storedSecrets={connection.secret_fields}
      replacing={replacing}
      onReplace={(key, on) => setReplacing((current) => (on ? [...current, key] : current.filter((item) => item !== key)))}
    />
  );
}

describe("ConnectionForm", () => {
  it("renders every catalog field type with labels, help, placeholders and required markers", () => {
    renderWithProviders(<CreateHarness />);
    const text = screen.getByTestId("field-name_text");
    expect(text).toHaveAttribute("placeholder", "type here");
    expect(text).toHaveAttribute("autocomplete", "off");
    expect(screen.getByText("Some help")).toBeInTheDocument();

    const password = screen.getByTestId("field-pw");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "off");

    const textarea = screen.getByTestId("field-pem");
    expect(textarea.tagName).toBe("TEXTAREA");
    expect(textarea).toHaveAttribute("rows", "8");
    expect(textarea).toHaveAttribute("spellcheck", "false");

    expect(screen.getByTestId("field-choice")).toHaveAttribute("role", "combobox");
    expect(screen.getByTestId("field-flag")).toHaveAttribute("role", "switch");
    expect(screen.getByTestId("field-count")).toHaveAttribute("type", "number");

    // Required markers on the three required fields only.
    expect(screen.getAllByText("*")).toHaveLength(3);
    // Secret fields carry the lock.
    expect(screen.getAllByLabelText("stored encrypted")).toHaveLength(2);
  });

  it("toggles password visibility without ever enabling autocomplete", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CreateHarness />);
    const password = screen.getByTestId("field-pw");
    await user.type(password, "hunter2");
    expect(password).toHaveValue("hunter2");
    expect(password).toHaveAttribute("type", "password");
    await user.click(screen.getByTestId("field-pw-toggle"));
    expect(password).toHaveAttribute("type", "text");
    expect(password).toHaveAttribute("autocomplete", "off");
    await user.click(screen.getByTestId("field-pw-toggle"));
    expect(password).toHaveAttribute("type", "password");
  });

  it("validates required fields and shows the message under each input", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CreateHarness />);
    await user.click(screen.getByText("validate"));
    expect(screen.getByText("Text field is required.")).toBeInTheDocument();
    expect(screen.getByText("Password field is required.")).toBeInTheDocument();
    expect(screen.getByText("Select field is required.")).toBeInTheDocument();
    expect(screen.queryByText("Textarea field is required.")).not.toBeInTheDocument();
    expect(screen.queryByText("Number field is required.")).not.toBeInTheDocument();
    expect(screen.getByTestId("field-name_text")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByTestId("field-count")).not.toHaveAttribute("aria-invalid");
  });

  it("applies catalog defaults and rejects non-numeric numbers", () => {
    const values = initialValues(ALL_TYPES_METHOD.fields);
    expect(values).toEqual({ name_text: "", pw: "", pem: "", choice: "", flag: false, count: "" });
    const errors = validateValues("test", ALL_TYPES_METHOD, { ...values, name_text: "x", pw: "y", choice: "a", count: "abc" });
    expect(errors).toEqual({ count: "Enter a number." });
    const bad = validateValues("test", ALL_TYPES_METHOD, { ...values, name_text: "x", pw: "y", choice: "zzz" });
    expect(bad.choice).toBe("Choose one of the listed options.");
  });

  it("sends secret fields in `secret` and everything else in `config`", () => {
    const values: FormValues = { ...initialValues(ALL_TYPES_METHOD.fields), name_text: " hello ", pw: "s3cret", pem: "-----BEGIN KEY-----\nabc\n", choice: "a", flag: true, count: "7" };
    const { config, secret } = splitValues("test", ALL_TYPES_METHOD, values);
    expect(config).toEqual({ name_text: "hello", choice: "a", flag: true, count: 7 });
    expect(secret).toEqual({ pw: "s3cret", pem: "-----BEGIN KEY-----\nabc\n" });
    expect(Object.keys(config)).not.toContain("pw");
  });

  it("hides fields that do not apply to the chosen base method and requires the ones that do", () => {
    const method = {
      ...CATALOG.aws.methods[0],
      key: "assume_role",
      fields: [
        { key: "base_method", label: "Base credentials", type: "select" as const, required: true, secret: false, default: "access_keys", options: [{ value: "access_keys", label: "Access keys" }, { value: "profile", label: "Named profile" }] },
        { key: "access_key_id", label: "Access key ID", type: "text" as const, required: false, secret: false },
        { key: "secret_access_key", label: "Secret access key", type: "password" as const, required: false, secret: true },
        { key: "profile", label: "Profile", type: "text" as const, required: false, secret: false },
        { key: "role_arn", label: "Role ARN", type: "text" as const, required: true, secret: false },
      ],
    };
    const keys = initialValues(method.fields);
    expect(validateValues("aws", method, keys)).toEqual({ access_key_id: "Access key ID is required.", secret_access_key: "Secret access key is required.", role_arn: "Role ARN is required." });
    const profile = { ...keys, base_method: "profile", role_arn: "arn:aws:iam::1:role/x", access_key_id: "leftover" };
    expect(validateValues("aws", method, profile)).toEqual({ profile: "Profile is required." });
    expect(splitValues("aws", method, { ...profile, profile: "default" }).config).toEqual({ base_method: "profile", profile: "default", role_arn: "arn:aws:iam::1:role/x" });
  });

  it("never echoes stored secrets in edit mode and only sends replaced ones", async () => {
    const user = userEvent.setup();
    const method = CATALOG.aws.methods[0];
    const connection = makeConnection();
    expect(initialValues(method.fields, connection.config).secret_access_key).toBe("");

    renderWithProviders(<EditHarness />);
    expect(screen.getByTestId("field-access_key_id")).toHaveValue("AKIAEXAMPLE");
    expect(screen.queryByTestId("field-secret_access_key")).not.toBeInTheDocument();
    expect(screen.getByTestId("secret-secret_access_key")).toHaveTextContent("set");
    expect(screen.getByTestId("secret-session_token")).toHaveTextContent("not set");
    // No input anywhere carries a secret value.
    for (const input of document.querySelectorAll("input, textarea")) expect((input as HTMLInputElement).value).not.toMatch(/secret/i);

    await user.click(screen.getByTestId("replace-secret_access_key"));
    const replacement = screen.getByTestId("field-secret_access_key");
    expect(replacement).toHaveValue("");
    expect(replacement).toHaveAttribute("type", "password");
    await user.type(replacement, "new-secret");
    await user.click(screen.getByTestId("keep-secret_access_key"));
    expect(screen.queryByTestId("field-secret_access_key")).not.toBeInTheDocument();

    const kept = splitValues("aws", method, initialValues(method.fields, connection.config), { storedSecrets: connection.secret_fields, replacing: [] });
    expect(kept.secret).toEqual({});
    const replaced = splitValues("aws", method, { ...initialValues(method.fields, connection.config), secret_access_key: "new-secret" }, { storedSecrets: connection.secret_fields, replacing: ["secret_access_key"] });
    expect(replaced.secret).toEqual({ secret_access_key: "new-secret" });
    // A stored secret that is not being replaced satisfies the required rule.
    expect(validateValues("aws", method, initialValues(method.fields, connection.config), { storedSecrets: connection.secret_fields, replacing: [] })).toEqual({});
  });

  it("builds a config patch with cleared keys as null and nothing when unchanged", () => {
    const method = CATALOG.aws.methods[0];
    const connection = makeConnection({ config: { access_key_id: "AKIAEXAMPLE", region: "eu-west-1", endpoint_url: "http://localhost:4566" } });
    const values = initialValues(method.fields, connection.config);
    expect(configPatch("aws", method, values, connection.config)).toBeNull();
    expect(configPatch("aws", method, { ...values, endpoint_url: "", region: "us-east-1" }, connection.config)).toEqual({ endpoint_url: null, region: "us-east-1" });
  });
});
