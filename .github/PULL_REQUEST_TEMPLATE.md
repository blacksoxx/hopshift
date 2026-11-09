## What

<!-- One or two sentences on the behaviour change. Link the issue if there is one. -->

## How to verify

<!-- Commands, a run to create, a screenshot for UI changes. -->

## Checklist

- [ ] Tests added or updated, `pytest` and `npx vitest run` green locally
- [ ] `ruff check .` and `npx tsc --noEmit` clean
- [ ] Generated Terraform still passes `pytest tests/integration` when renderers or policies changed
- [ ] Docs updated (`docs/`, README) when behaviour or configuration changed
- [ ] No secrets, hostnames or customer data in code, fixtures or screenshots
