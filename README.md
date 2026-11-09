<p align="center">
  <img src="ui/public/favicon.svg" width="72" alt="" />
</p>

<h1 align="center">VMware Migration Agent</h1>

<p align="center">
  Turn vSphere discovery into validated, compliant Terraform for AWS, Azure, GCP or OpenStack,<br/>
  review it with your team, and deploy it with human approval.
</p>

<p align="center">
  <a href="https://github.com/blacksoxx/vmware-migration-agent/actions/workflows/ci.yml"><img src="https://github.com/blacksoxx/vmware-migration-agent/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/blacksoxx/vmware-migration-agent/actions/workflows/codeql.yml"><img src="https://github.com/blacksoxx/vmware-migration-agent/actions/workflows/codeql.yml/badge.svg" alt="CodeQL" /></a>
  <a href="https://scorecard.dev/viewer/?uri=github.com/blacksoxx/vmware-migration-agent"><img src="https://api.scorecard.dev/projects/github.com/blacksoxx/vmware-migration-agent/badge" alt="OpenSSF Scorecard" /></a>
  <a href="https://github.com/blacksoxx/vmware-migration-agent/tree/python-coverage-comment-action-data"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/blacksoxx/vmware-migration-agent/python-coverage-comment-action-data/endpoint.json" alt="Coverage" /></a>
  <a href="https://github.com/blacksoxx/vmware-migration-agent/releases"><img src="https://img.shields.io/github/v/release/blacksoxx/vmware-migration-agent?color=4f46e5" alt="Release" /></a>
  <a href="https://github.com/blacksoxx/vmware-migration-agent/pkgs/container/vmware-migration-agent"><img src="https://img.shields.io/badge/ghcr.io-image-2496ED?logo=docker&logoColor=white" alt="Container image" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-4f46e5.svg" alt="MIT" /></a>
  <img src="https://img.shields.io/badge/python-3.12-3776ab.svg" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/terraform-1.17-7b42bc.svg" alt="Terraform 1.17" />
  <img src="https://img.shields.io/badge/OPA-policies-1e90ff.svg" alt="OPA" />
</p>

<p align="center">
  <img src="docs/images/dashboard.png" alt="Dashboard" width="900" />
</p>

---

Lift-and-shift migrations fail in the details: the VM nobody noticed was encrypted, the
security group someone opened to the world, the disk that was never encrypted, the change that
was applied without review. This project makes the boring path the default.

- **Deterministic core.** A discovery JSON becomes a canonical model, then Terraform rendered
  from templates. Same input, same output, every time. Diffable, reviewable, testable.
- **Validated before it exists.** Every run passes `terraform validate`, `tflint` and OPA
  policies before a single file is written. Blocked VMs are quarantined with reasons.
- **Compliant by construction.** The generated infrastructure is checked against controls
  mapped to CIS Benchmarks, SOC 2 and HIPAA, and the renderers are hardened so it passes.
- **Humans decide.** Runs pause for CIM review and output approval. Apply and destroy require a
  typed confirmation. Everything lands in a tamper-evident audit log.
- **A platform, not a script.** Accounts and roles, MFA and single sign-on, encrypted cloud
  connections with every sign-in method, Terraform plan and apply with live logs, a UI people
  actually like.
- **AI where it helps.** Optional model-written review notes and generation modes. Never in the
  gate, never with your credentials.

## Quick start

```bash
git clone https://github.com/blacksoxx/vmware-migration-agent.git
cd vmware-migration-agent
cp .env.example .env
docker compose run --rm --no-deps agent python -m cli.main secrets generate-key   # put it in .env as VMA_SECRET_KEY
docker compose up -d --build
```

Open http://localhost:8080, create the administrator, upload a discovery JSON and start a run.
Without Docker: `pip install -e ".[dev]"`, build the UI with `npm ci && npm run build` in `ui/`,
then `vma serve`. Details in [docs/setup.md](docs/setup.md).

Command-line only, no UI:

```bash
vma terragen --input discovery.json --cloud aws --environment prod --owner platform-team
vma assess   --input discovery.json --cloud azure
```

## How it works

```
discovery.json ─▶ ingest ─▶ blockers ─▶ enrich ─▶ CIM ─▶ size ─▶ generate ─▶ validate ─▶ report
                                                   │                           │
                                             review & edit               terraform · tflint · OPA
                                             (pause point)             CIS · SOC 2 · HIPAA controls
                                                                              │
                                        connections (encrypted) ─▶ plan ─▶ approve ─▶ apply
```

1. **Discover** with the Ansible playbook; the output is a JSON file with VMs, disks, networks,
   clusters and the facts that block a migration (encryption, RDM, shared disks, templates).
2. **Translate** into the Canonical Infrastructure Model. Translators are per source hypervisor;
   providers are per target cloud; neither knows about the other.
3. **Generate** a flat Terraform root module per cloud: VPC/VNet, subnets, security groups,
   instances, disks, placement groups, with Environment/Owner/MigratedFrom tags everywhere.
4. **Validate** with the real tools and with policy as code. Failures never reach the output.
5. **Review** the model and the files in the UI, compare with a previous run, approve.
6. **Deploy** through a stored cloud connection: plan, read the summary and the log, type the
   run id, apply. Destroy is gated the same way.

<p align="center">
  <img src="docs/images/run-detail.png" alt="Run detail with timeline, CIM review and compliance" width="900" />
</p>

## Security and compliance

The platform implements the technical controls auditors look for and produces evidence:

| Area | What you get |
|---|---|
| Access | Local accounts (argon2id), TOTP second factor with recovery codes, OIDC single sign-on, roles viewer / operator / admin, API tokens, lockout and throttling, session expiry |
| Audit | Hash-chained audit log of every action (actor, IP, agent, outcome), export, integrity verification |
| Secrets | Cloud credentials and MFA secrets encrypted at rest with a key that lives only in the environment; rotation; nothing secret in logs or responses |
| Transport and browser | Security headers, strict CSP, HSTS on TLS, same-origin checks for cookie-authenticated mutations |
| Output | OPA controls mapped to CIS Benchmarks (AWS, Azure, GCP), SOC 2 Trust Services Criteria and the HIPAA Security Rule; compliance report with every run |
| Change control | Pause points, typed confirmations for apply and destroy, plan/artifact integrity checks |
| Platform | Non-root, read-only container with capabilities dropped; posture page with live checks; retention policies |

SOC 2 and HIPAA are organisational attestations; no software is "certified" on its own. This
platform gives you the controls and the evidence. See [docs/security.md](docs/security.md) and
[docs/compliance.md](docs/compliance.md).

<p align="center">
  <img src="docs/images/compliance.png" alt="Compliance report" width="900" />
</p>

## Screenshots

| | |
|---|---|
| ![Runs](docs/images/runs.png) | ![CIM review](docs/images/cim.png) |
| ![Artifacts with highlighting and diff](docs/images/artifacts.png) | ![Deployments](docs/images/deploy.png) |
| ![Assessment](docs/images/assess.png) | ![Connections](docs/images/connections.png) |
| ![Security posture](docs/images/posture.png) | ![Audit log](docs/images/audit.png) |

Dark mode is a click away:

<p align="center">
  <img src="docs/images/dashboard-dark.png" alt="Dashboard, dark theme" width="900" />
</p>

## Cloud connections

Every sign-in method you are likely to meet, verified before use and resolved into the
environment Terraform expects:

| Cloud | Methods |
|---|---|
| AWS | access keys, named profile, assume role, environment (instance role / IRSA), IAM Identity Center (SSO device login), web identity; optional custom endpoint (LocalStack) |
| Azure | service principal (secret or certificate), managed identity, workload identity (OIDC), Azure CLI, device code |
| GCP | service account key, application default credentials, impersonation, workload identity federation |
| OpenStack | password, application credential, clouds.yaml |

See [docs/connections.md](docs/connections.md).

## Documentation

| | |
|---|---|
| [Architecture](docs/architecture.md) | How the pipeline, platform services, API and UI fit together |
| [Setup and operations](docs/setup.md) | Docker, local development, production checklist, backups |
| [Security](docs/security.md) | Accounts, MFA, SSO, tokens, headers, retention, threat model |
| [Compliance](docs/compliance.md) | The control matrix and the report format |
| [Connections](docs/connections.md) | Providers, methods, fields, Terraform environment mapping |
| [Deployments](docs/deployments.md) | Plan, apply, destroy, state, LocalStack recipe |
| [HTTP API](docs/api.md) | Every endpoint with roles and bodies |
| [UI](docs/ui.md) | Pages, keyboard shortcuts, building and testing |
| [CLI](docs/cli.md) | `vma` commands |
| [Pipeline](docs/pipeline.md) · [CIM](docs/cim-and-translation.md) · [Discovery schema](docs/discovery-schema.md) · [Configuration](docs/configuration.md) · [AI usage](docs/ai-usage.md) | The core |

## Development

```bash
pip install -e ".[dev]" && pre-commit install && (cd ui && npm ci)
pytest -q --ignore=tests/integration --cov    # fast unit suite with coverage
pytest -q tests/integration                   # real terraform/tflint/opa on all four clouds
cd ui && npx vitest run --coverage && npm run build && npx playwright test
```

Pull requests get the full treatment automatically: lint, unit tests on three Python
targets, integration, UI, end-to-end, secret and dependency scans, semgrep, trivy, CodeQL, a
coverage comment and a dependency review. Releases build a signed multi-arch image on GHCR.
See [docs/ci.md](docs/ci.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

Prefer the published image? `docker pull ghcr.io/blacksoxx/vmware-migration-agent:latest`
(linux/amd64 and linux/arm64, Sigstore-signed; see the release notes to verify).

## Roadmap

- Additional source hypervisors through the translator registry (Hyper-V, Nutanix, IBM PowerVC)
- Image import orchestration (VMDK to AMI / managed image / GCE image) feeding `image_overrides`
- Remote Terraform state and workspaces per environment from the UI
- Notifications (Slack, email) on pause points and deployment results

## License

MIT. Built by [@blacksoxx](https://github.com/blacksoxx).
