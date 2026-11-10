# Compliance-as-code

The generated Terraform is checked against a catalog of controls before anything is written.
Each control has an id, a level, framework references and remediation text; the result is a
per-control report (`compliance_report.json` / `compliance_report.md`) that ships with every run.

## How it works

1. The validator parses the generated `.tf` files with `validation/hcl_parser.py` and evaluates
   the whole policy bundle (`hopshift/validation/policies`) with OPA, exactly as before. Nothing changed in
   how `deny` messages are collected.
2. The controls live in `hopshift/validation/policies/compliance/*.rego`, package
   `hopshift.compliance` (one file per cloud plus `common.rego`). Every rule emits a
   `violations` entry:

   ```json
   {"control": "AWS-EC2-IMDSV2", "level": "enforce", "resource": "aws_instance.web_01",
    "file": "aws-migration/compute_web-01.tf", "message": "metadata_options block is missing; IMDSv2 must be required"}
   ```

   - `enforce` violations are also emitted as `deny` messages
     (`compliance <ID>: <message> (<resource>)`), so they fail the existing gate in both validation
     phases (the hcl_generator loop and the final validator).
   - `advisory` violations are reported only. They cover settings that need account-level resources
     or subscription features the platform does not create (flow-log destinations, KMS keys,
     EncryptionAtHost registration, a dedicated service account).
   - `evaluated` lists the control ids that applied to the input. The cloud is detected from the
     provider types present (`aws_*`, `azurerm_*`, `google_*`, `openstack_*`, plus the `provider`
     and `required_providers` blocks).
3. `validation/opa_client.py` returns the violations and the evaluated ids on
   `OPAEvaluationResult.violations` / `.evaluated` (binary and server mode), next to the unchanged
   `passed` / `errors` / `deny_messages`.
4. `agent/nodes/validator.py` calls `vma.compliance.report.build_report(cloud, violations,
   evaluated, validation_result)` and stores the result in state as `compliance_result`. This
   happens for every outcome: when OPA is disabled or unavailable the report lists every control as
   `not_applicable` and carries a warning, and `validation_result.warnings` says so too.
5. `agent/nodes/reporter.py` writes `compliance_report.json` and `compliance_report.md` into
   `output.base_dir`, next to `quarantine_report.json`, for passed and failed runs alike
   (`output.write_compliance_report`, default `true`; nothing is written with `output.dry_run`).
6. The run service (`agent/runtime.py`) adds `compliance_failed` and `compliance_advisory` to the
   per-node event summaries so the API/UI can show them without reading the report.

The catalog (`vma/compliance/controls.py`) and the bundle must agree: a test evaluates
`data.hopshift.compliance.controls` with the real `opa` binary and compares ids and levels
with the Python catalog.

## Secure-by-default renderers

The deterministic renderers (`providers/*/`) emit output that passes every `enforce` control on all
four clouds; `tests/integration/test_terraform_validate.py` proves it with the real policy bundle
and keeps `terraform validate` + `tflint` green. What the renderers now emit:

| Cloud | Hardening |
| --- | --- |
| AWS | `aws_instance`: `metadata_options { http_endpoint = "enabled", http_tokens = "required", http_put_response_hop_limit = 1 }`, `associate_public_ip_address = false`, `ebs_optimized = true`, `root_block_device { encrypted = true }`; `aws_ebs_volume` encrypted; one `aws_default_security_group` per VPC with no rules; security group ingress limited to `10.0.0.0/8`. |
| Azure | NICs without `public_ip_address_id`; NSG SSH rule sourced from `VirtualNetwork` only; `boot_diagnostics {}` (managed storage) on each VM. `encryption_at_host_enabled` stays advisory because it needs the `Microsoft.Compute/EncryptionAtHost` subscription feature. |
| GCP | `google_compute_instance`: no `access_config`, `can_ip_forward = false`, `shielded_instance_config` with secure boot / vTPM / integrity monitoring, `metadata { enable-oslogin = "TRUE", block-project-ssh-keys = "TRUE", serial-port-enable = "FALSE" }`, `service_account` with logging/monitoring/read-only storage scopes and `email` from the new `var.service_account_email` (empty keeps the default Compute Engine account, with the limited scopes); every `google_compute_subnetwork` has `log_config` and `private_ip_google_access = true`. Imported images must carry the `UEFI_COMPATIBLE` guest OS feature for Shielded VM. |
| OpenStack | Security group rules sourced from `10.0.0.0/8`; volumes use `var.encrypted_volume_type` (default `encrypted`). |

File names, variables and the flat module layout are unchanged apart from the added GCP variable.

## Control matrix

Benchmark versions: CIS Amazon Web Services Foundations v3.0, CIS Microsoft Azure Foundations v3.0,
CIS Google Cloud Platform Foundation v3.0 (CIS publishes no OpenStack benchmark). SOC 2 references
are Trust Services Criteria ids; HIPAA references are 45 CFR Part 164 Security Rule paragraphs. A
reference means the control is technical evidence for that criterion; check the numbering against
the benchmark revision your assessor uses.

| ID | Title | Clouds | Level | CIS | SOC 2 TSC | HIPAA |
| --- | --- | --- | --- | --- | --- | --- |
| `ALL-TAGS-REQUIRED` | Required ownership tags on every resource | all | enforce | - | CC6.1, CC3.2 | 164.308(a)(1)(ii)(A), 164.310(d)(1) |
| `AWS-EC2-IMDSV2` | EC2 instances require IMDSv2 | aws | enforce | AWS 5.6 | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `AWS-EC2-NO-PUBLIC-IP` | EC2 instances have no public IP | aws | enforce | - | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `AWS-EC2-EBS-OPTIMIZED` | EC2 instances are EBS-optimized | aws | enforce | - | A1.1 | - |
| `AWS-EBS-ENCRYPTED` | EBS volumes and root devices are encrypted | aws | enforce | AWS 2.2.1 | CC6.1, CC6.7 | 164.312(a)(2)(iv), 164.312(e)(2)(ii) |
| `AWS-VPC-DEFAULT-SG-RESTRICTED` | Default security group of every VPC restricts all traffic | aws | enforce | AWS 5.4 | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `AWS-SG-NO-OPEN-INGRESS` | No security group ingress from the internet | aws | enforce | AWS 5.2, AWS 5.3 | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `AWS-VPC-FLOW-LOGS` | VPC flow logs enabled | aws | advisory | AWS 3.7 | CC7.1, CC7.2 | 164.312(b), 164.308(a)(1)(ii)(D) |
| `AWS-EBS-ENCRYPTION-BY-DEFAULT` | Account-level EBS encryption by default | aws | advisory | AWS 2.2.1 | CC6.1, CC6.7 | 164.312(a)(2)(iv), 164.312(e)(2)(ii) |
| `AWS-EC2-DETAILED-MONITORING` | EC2 detailed monitoring | aws | advisory | - | CC7.1, CC7.2 | 164.312(b), 164.308(a)(1)(ii)(D) |
| `AZ-NIC-NO-PUBLIC-IP` | Network interfaces have no public IP | azure | enforce | - | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `AZ-NSG-NO-OPEN-MGMT-PORTS` | No SSH/RDP from the internet in network security groups | azure | enforce | Azure 7.1, Azure 7.2 | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `AZ-STORAGE-SECURE-TRANSPORT` | Storage accounts require TLS 1.2 and HTTPS | azure | enforce | Azure 4.1, Azure 4.15 | CC6.7 | 164.312(e)(1), 164.312(e)(2)(ii) |
| `AZ-STORAGE-NO-PUBLIC-ACCESS` | Storage accounts block public access | azure | enforce | Azure 4.6, Azure 4.17 | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `AZ-VM-ENCRYPTION-AT-HOST` | Encryption at host for virtual machines | azure | advisory | Azure 8.9 | CC6.1, CC6.7 | 164.312(a)(2)(iv), 164.312(e)(2)(ii) |
| `AZ-VM-BOOT-DIAGNOSTICS` | Boot diagnostics enabled | azure | advisory | - | CC7.1, CC7.2 | 164.312(b), 164.308(a)(1)(ii)(D) |
| `AZ-DISK-CMK` | Managed disks use customer-managed keys | azure | advisory | Azure 8.3 | CC6.1, CC6.7 | 164.312(a)(2)(iv), 164.312(e)(2)(ii) |
| `AZ-NSG-FLOW-LOGS` | NSG flow logs enabled | azure | advisory | Azure 7.6 | CC7.1, CC7.2 | 164.312(b), 164.308(a)(1)(ii)(D) |
| `GCP-VM-NO-EXTERNAL-IP` | Compute instances have no external IP | gcp | enforce | GCP 4.9 | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `GCP-VM-SHIELDED` | Shielded VM enabled | gcp | enforce | GCP 4.8 | CC6.8, CC7.1 | 164.312(c)(1) |
| `GCP-VM-OSLOGIN` | OS Login enabled | gcp | enforce | GCP 4.4 | CC6.1, CC6.2, CC6.3 | 164.312(a)(1), 164.312(d) |
| `GCP-VM-SERIAL-PORT-DISABLED` | Serial port access disabled | gcp | enforce | GCP 4.5 | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `GCP-VM-BLOCK-PROJECT-SSH-KEYS` | Project-wide SSH keys blocked | gcp | enforce | GCP 4.3 | CC6.1, CC6.2 | 164.312(a)(1), 164.312(d) |
| `GCP-VM-NO-IP-FORWARD` | IP forwarding disabled | gcp | enforce | GCP 4.6 | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `GCP-VM-LIMITED-SCOPES` | Service account scopes limited | gcp | enforce | GCP 4.2 | CC6.1, CC6.3 | 164.312(a)(1), 164.308(a)(4)(ii)(B) |
| `GCP-VM-DEDICATED-SA` | Dedicated service account per workload | gcp | advisory | GCP 4.1 | CC6.1, CC6.3 | 164.308(a)(3)(i), 164.308(a)(4)(ii)(B) |
| `GCP-SUBNET-FLOW-LOGS` | Subnetwork flow logs enabled | gcp | enforce | GCP 3.8 | CC7.1, CC7.2 | 164.312(b), 164.308(a)(1)(ii)(D) |
| `GCP-SUBNET-PRIVATE-GOOGLE-ACCESS` | Private Google Access enabled | gcp | enforce | - | CC6.1, CC6.6 | 164.312(e)(1) |
| `GCP-FW-NO-OPEN-MGMT-PORTS` | No SSH/RDP from the internet in firewall rules | gcp | enforce | GCP 3.6, GCP 3.7 | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `GCP-DISK-CMEK` | Persistent disks use customer-managed keys | gcp | advisory | GCP 4.7 | CC6.1, CC6.7 | 164.312(a)(2)(iv), 164.312(e)(2)(ii) |
| `OS-SG-NO-OPEN-MGMT-PORTS` | No SSH/RDP from the internet in security group rules | openstack | enforce | - | CC6.1, CC6.6 | 164.312(a)(1), 164.312(e)(1) |
| `OS-VOLUME-ENCRYPTED-TYPE` | Volumes use an encryption-backed volume type | openstack | advisory | - | CC6.1, CC6.7 | 164.312(a)(2)(iv), 164.312(e)(2)(ii) |

The pre-existing gate rules (`no_open_ingress`, `no_public_s3`, `encryption_at_rest`,
`tags_required`, `no_code_execution`) are unchanged and still run. `ALL-TAGS-REQUIRED` and
`AWS-SG-NO-OPEN-INGRESS` mirror two of them so the report can show their status; when they fail,
both the original rule and the control emit a deny.

## Report format

`compliance_report.json`:

```json
{
  "generated_at": "2026-11-09T12:00:00Z",
  "cloud": "aws",
  "gate_passed": true,
  "summary": {"controls": 10, "passed": 7, "failed": 0, "advisory": 3, "not_applicable": 0},
  "controls": [
    {
      "id": "AWS-EC2-IMDSV2",
      "title": "EC2 instances require IMDSv2",
      "description": "...",
      "level": "enforce",
      "status": "pass",
      "frameworks": {"cis": ["AWS 5.6"], "soc2": ["CC6.1", "CC6.6"], "hipaa": ["164.312(a)(1)", "164.312(e)(1)"]},
      "resources": [],
      "messages": [],
      "remediation": "Add a metadata_options block ..."
    }
  ],
  "frameworks": {
    "cis":   {"controls": 6, "passed": 4, "failed": 0, "advisory": 2, "not_applicable": 0},
    "soc2":  {"controls": 10, "passed": 7, "failed": 0, "advisory": 3, "not_applicable": 0},
    "hipaa": {"controls": 9, "passed": 6, "failed": 0, "advisory": 3, "not_applicable": 0}
  },
  "warnings": [],
  "note": "SOC 2 and HIPAA are organisational attestations ..."
}
```

- `status` is one of `pass`, `fail` (enforce control with findings), `advisory` (advisory control
  with findings) or `not_applicable` (the control was not evaluated: OPA disabled or failed).
- `resources` and `messages` list the offending addresses and `resource (file): message` lines.
- `frameworks` counts only the controls that carry a reference for that framework.
- `compliance_report.md` renders the same data: summary table, framework coverage, the control
  table (id, title, level, status, CIS, SOC 2, HIPAA), one findings section per failing or advisory
  control with remediation, warnings, and the attestation note.

Only the catalog controls for the target cloud appear in a report; controls the bundle reports
that are missing from the catalog are kept visible as `Unknown control <id>` so drift is noticed.

## Adding a control

1. Pick an id in the `<CLOUD>-<AREA>-<WHAT>` form (`AWS-`, `AZ-`, `GCP-`, `OS-`, or `ALL-`).
2. Add the rule to `hopshift/validation/policies/compliance/<cloud>.rego`: register the id and level in the
   `<cloud>_controls` map (that is what populates `controls` and `evaluated`) and write one or more
   `violations contains v if { ... v := <cloud>_violation("<ID>", r, "message") }` rules on
   `input.resources`. Use `object.get` with explicit defaults, and keep nested function calls inside
   `not ... in ...` always defined (Rego hoists them out of the negation). `common.rego` provides
   `port_spec_covers`, `open_cidrs`, `management_ports`, `provider_anchor` and
   `expression_backed_by_variable_default`.
3. Add the matching `Control(...)` to `vma/compliance/controls.py` with title, description, clouds,
   the same level, framework references and honest remediation text (say what the operator has to
   provide when the platform cannot create it).
4. If the control is `enforce`, make the renderers in `providers/<cloud>/` satisfy it; the
   integration test `test_deterministic_render_passes_every_enforce_compliance_control` fails
   otherwise.
5. Add cases to `tests/validation/test_compliance_policies.py` (a compliant and a violating
   snippet) and run `opa check hopshift/validation/policies` and `opa fmt --list hopshift/validation/policies/compliance`.

## What this is, and is not

SOC 2 and HIPAA are organisational attestations: an auditor assesses policies, procedures, risk
analysis, training, vendor management and the operation of controls over time. The Terraform this
platform generates cannot make an organisation compliant. What it does provide is technical
controls in the generated infrastructure and machine-readable evidence that they were in place at
generation time, mapped to the criteria they support. CIS references are closer to the ground (they
describe configuration), but the same caveat applies: passing every control here covers the
resources this platform renders, not the surrounding account, identity, logging and network estate.
