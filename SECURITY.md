# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems.

Use GitHub's private vulnerability reporting:
https://github.com/blacksoxx/hopshift/security/advisories/new (the repository's
**Security** tab, **Report a vulnerability**). If that form is unavailable to you, contact the
maintainer through the GitHub profile at https://github.com/blacksoxx and ask for a private
channel before sharing details. You will get an acknowledgement within 3 working days and a fix
or mitigation plan within 14 days for confirmed issues. Credit is given in the release notes
unless you prefer otherwise.

Include what you can: affected version or commit, the component (API, UI, CLI, generated
Terraform, policies, container image), reproduction steps, impact, and a suggested fix.

## Supported versions

The `main` branch and the latest tagged release receive security fixes.

## What is in scope

- The platform API, UI and CLI (`api/`, `ui/`, `cli/`, `vma/`).
- The pipeline and the Terraform it generates (`agent/`, `cim/`, `providers/`): a generated
  configuration that violates the documented security controls is a vulnerability.
- The OPA policies in `hopshift/validation/policies/` and the compliance mapping in `vma/compliance/`.
- The container image and compose file.

## Security design in one paragraph

Authentication is required by default (local accounts with argon2id hashes, optional TOTP
second factor and OIDC single sign-on); roles are viewer, operator and admin. Every mutating
action is written to a hash-chained audit log. Cloud credentials are stored only encrypted at
rest with a key that lives in the environment. The generated Terraform passes through terraform
validate, tflint and OPA policies that implement CIS Benchmark, SOC 2 and HIPAA technical
controls before anything is written; apply and destroy require an explicit, typed approval.
See `docs/security.md` and `docs/compliance.md` for the full picture.
