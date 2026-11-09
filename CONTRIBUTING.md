# Contributing

Thanks for helping make VMware migrations boring. This page gets you from clone to green
tests in a few minutes.

## Development setup

Requirements: Python 3.12, Node 22, and for validation and deployments the `terraform`,
`tflint` and `opa` binaries on your PATH (versions pinned in the Dockerfile). Docker is
optional and only needed for the MCP documentation retriever and the container build.

```bash
git clone https://github.com/blacksoxx/vmware-migration-agent.git
cd vmware-migration-agent

# Python
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# UI
cd ui && npm ci && cd ..

# Run the platform (API + UI) on http://127.0.0.1:8080
export VMA_SECRET_KEY=$(vma secrets generate-key)
vma serve
```

During UI work run `cd ui && npm run dev` for Vite with hot reload (it proxies `/api` to
port 8080).

## Tests

```bash
pytest -q --ignore=tests/integration      # unit: pipeline, CIM, policies, platform services, API
pytest -q tests/integration               # real terraform validate + tflint + OPA on all four clouds
cd ui && npx vitest run && npx tsc --noEmit && npm run build
cd ui && npx playwright test               # end-to-end against a real server
ruff check .
```

Every pull request runs these in CI together with dependency, secret and container scans.

## Conventions

- Deterministic core: anything that can be computed must not call a model. The LLM is used
  only for review notes and the optional `llm`/`hybrid` generation modes.
- Security rules in `AGENTS.md` are non-negotiable (no public ingress, encrypted volumes,
  required tags, no code-execution constructs in generated Terraform).
- Services raise `vma.errors` exceptions; the API maps them to status codes. Never log or
  return secret values.
- New API areas get their own router in `api/routes/` and their own service package in `vma/`.
- Type hints everywhere, `ruff` clean, tests next to the feature (`tests/<area>/`).
- Line endings are LF everywhere (enforced by `.gitattributes`).
- Commit messages: `type(scope): summary` (feat, fix, docs, test, chore, refactor).

## Adding things

- **A cloud provider**: implement `providers/<name>/{compute,network,storage,placement,runtime}.py`,
  a sizing table, OPA controls in `validation/policies/compliance/`, catalog entries in
  `vma/connections/models.py`, and an integration test case.
- **A source hypervisor**: add a translator under `cim/translators/` keyed by the discovery
  `schema_name`, and blockers in `cim/blockers.py`.
- **A compliance control**: add the rego rule and the catalog entry in `vma/compliance/controls.py`
  with CIS, SOC 2 and HIPAA references, then a policy test.

## Pull requests

Describe the behaviour change, link an issue when there is one, add screenshots for UI
changes, and make sure CI is green. Small, focused PRs are reviewed faster.
