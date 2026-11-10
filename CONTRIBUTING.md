# Contributing

Thanks for helping make migrations boring. This page gets you from clone to green
tests in a few minutes.

## Development setup

Requirements: Python 3.12, Node 22, and for validation and deployments the `terraform`,
`tflint` and `opa` binaries on your PATH (versions pinned in the Dockerfile). Docker is
optional and only needed for the MCP documentation retriever and the container build.

```bash
git clone https://github.com/blacksoxx/hopshift.git
cd hopshift

# Python (the lock files under requirements/ are hash-pinned; CI and the image use them)
python3.12 -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements/dev.txt && pip install --no-deps -e .
pre-commit install          # ruff, gitleaks and sanity hooks run on every commit

# UI
cd ui && npm ci && cd ..

# Run the platform (API + UI) on http://127.0.0.1:8080
export HOPSHIFT_SECRET_KEY=$(hopshift secrets generate-key)
hopshift serve
```

During UI work run `cd ui && npm run dev` for Vite with hot reload (it proxies `/api` to
port 8080).

## Tests

```bash
pytest -q --ignore=tests/integration      # unit: pipeline, CIM, sources, targets, policies, platform services, API
pytest -q tests/integration               # real terraform validate + tflint + OPA on every built-in target
cd ui && npx vitest run && npx tsc --noEmit && npm run build
cd ui && npx playwright test               # end-to-end against a real server
ruff check .
```

Every pull request runs these in CI together with dependency, secret, static-analysis and
container scans, posts a coverage comment, checks the title format and reviews new
dependencies. `All checks passed` is the required status on `main`. The full list is in
[docs/ci.md](docs/ci.md).

## Dependencies

Declared in `pyproject.toml`; resolved and hash-pinned in `requirements/prod.txt` and
`requirements/dev.txt` (universal, Python 3.12+). After changing `pyproject.toml`, refresh both:

```bash
uv pip compile pyproject.toml --universal --generate-hashes --python-version 3.12 -o requirements/prod.txt
uv pip compile pyproject.toml --extra dev --universal --generate-hashes --python-version 3.12 -o requirements/dev.txt
```

Dependabot keeps the pins current.

## Conventions

- Deterministic core: anything that can be computed must not call a model. The LLM is used
  only for review notes and the optional `llm`/`hybrid` generation modes.
- The CIM is the boundary: sources never see a target resource type, targets never see a
  source field name. Both are resolved through the registries in `hopshift/sources/registry.py`
  and `hopshift/targets/registry.py`; do not hardcode a target name in the deterministic path.
- Security rules in `AGENTS.md` are non-negotiable (no public ingress, encrypted volumes,
  required tags, no code-execution constructs in generated Terraform).
- Services raise `hopshift.services.errors` exceptions; the API maps them to status codes. Never
  log or return secret values.
- New API areas get their own router in `hopshift/api/routes/` and their own service package in
  `hopshift/services/`.
- Type hints everywhere, `ruff` clean, tests next to the feature (`tests/<area>/`).
- Line endings are LF everywhere (enforced by `.gitattributes`).
- Commit messages and pull request titles: `type(scope): summary` with a lowercase subject
  (feat, fix, docs, test, chore, refactor, ci, build, perf, security).

## Adding things

The plugin guide ([docs/plugins.md](docs/plugins.md)) has the full contract; the tier a new
source or target lands in is defined in [docs/support-matrix.md](docs/support-matrix.md).

- **A target**: a package with `network`, `compute`, `storage`, `placement`, `runtime` and
  `sizing_table` modules, registered as a `TargetSpec` (built in: `hopshift/targets/__init__.py`;
  external: a `hopshift.targets` entry point). For deployments add catalog entries in
  `hopshift/services/connections/models.py`; for compliance add OPA controls in
  `hopshift/validation/policies/compliance/` and `Control` entries in
  `hopshift/services/compliance/controls.py`; add an integration test case and
  `docs/targets/<name>.md`.
- **A source**: a translator producing the CIM, registered as a `SourceSpec` keyed by the
  discovery `schema_name` (built in: `hopshift/sources/__init__.py`; external: a
  `hopshift.sources` entry point), blockers in `hopshift/cim/blockers.py` if its flags differ, a
  fixture, a translator test and `docs/sources/<name>.md`.
- **A compliance control**: add the rego rule and the catalog entry in
  `hopshift/services/compliance/controls.py` with CIS, SOC 2 and HIPAA references, then a policy
  test.

## Pull requests

Describe the behaviour change, link an issue when there is one, add screenshots for UI
changes, and make sure CI is green. Small, focused PRs are reviewed faster.
