"""Security posture checks served by GET /settings/posture.

Each check is `{id, title, status (pass|warn|fail), detail, frameworks}` so the UI renders them
generically and auditors can map them to SOC 2 TSC, HIPAA Security Rule and CIS Controls.
"""
from __future__ import annotations

from typing import Any

from api.middleware import is_https
from vma.security.store import SecurityStore


def _section(config: dict[str, Any], *path: str) -> dict[str, Any]:
    node: Any = config
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _check(check_id: str, title: str, status: str, detail: str, frameworks: list[str]) -> dict[str, Any]:
    return {"id": check_id, "title": title, "status": status, "detail": detail, "frameworks": frameworks}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def posture_checks(platform: Any, request: Any) -> list[dict[str, Any]]:
    config = platform.effective_config()
    security = _section(config, "security")
    auth = _section(security, "auth")
    oidc = _section(auth, "oidc")
    retention = _section(security, "retention")
    deploy = _section(config, "deploy")
    auth_enabled = platform.auth_mode != "disabled"
    https = bool(is_https(request)) if request is not None else False
    verification = platform.audit.verify()
    store = SecurityStore(platform.db)

    checks: list[dict[str, Any]] = [
        _check(
            "auth.enforced", "Authentication enforced", "pass" if auth_enabled else "fail",
            f"auth mode is {platform.auth_mode}"
            + ("" if auth_enabled else " (local development only; every caller is an anonymous admin)"),
            ["SOC2 CC6.1", "HIPAA 164.312(d)", "CIS 6.3"],
        ),
        _check(
            "secrets.key", "Secrets encryption key configured", "pass" if platform.secrets.available else "fail",
            f"{platform.secrets.env_var} {'set' if platform.secrets.available else 'missing'}",
            ["SOC2 CC6.1", "HIPAA 164.312(a)(2)(iv)"],
        ),
        _check(
            "audit.chain", "Audit log integrity", "pass" if verification.ok else "fail",
            f"{verification.entries} entries, {verification.message}", ["SOC2 CC7.2", "HIPAA 164.312(b)", "CIS 8.2"],
        ),
        _check(
            "transport.tls", "TLS in use", "pass" if https else "warn",
            "request arrived over HTTPS" if https else "request arrived over plain HTTP; terminate TLS in front of the API",
            ["SOC2 CC6.7", "HIPAA 164.312(e)(1)", "CIS 3.10"],
        ),
        _check(
            "retention.runs", "Run retention configured", "pass" if _int(retention.get("runs_days"), 0) > 0 else "warn",
            f"runs_days={retention.get('runs_days') or 0}", ["SOC2 CC6.5", "HIPAA 164.310(d)(2)(i)"],
        ),
    ]

    # ── additions from the security workstream ────────────────────────────────
    mfa_policy = str(auth.get("mfa") or "optional")
    checks.append(
        _check(
            "mfa.policy", "MFA policy", "pass" if mfa_policy == "required" else "warn",
            f"security.auth.mfa={mfa_policy}"
            + ("" if mfa_policy == "required" else "; set to required so every local account enrols a second factor"),
            ["SOC2 CC6.1", "HIPAA 164.312(d)", "CIS 6.5"],
        )
    )
    if auth_enabled:
        without = store.count_users_without_mfa()
        checks.append(
            _check(
                "mfa.coverage", "Users without MFA", "pass" if without == 0 else "warn",
                f"{without} active password account(s) without MFA", ["SOC2 CC6.1", "CIS 6.5"],
            )
        )
    else:
        checks.append(
            _check("mfa.coverage", "Users without MFA", "warn", "not applicable while authentication is disabled", ["SOC2 CC6.1", "CIS 6.5"])
        )
    plaintext = store.count_plaintext_mfa_secrets()
    checks.append(
        _check(
            "mfa.secrets_encrypted", "MFA secrets encrypted at rest", "pass" if plaintext == 0 else "fail",
            "all TOTP secrets are stored encrypted" if plaintext == 0
            else f"{plaintext} TOTP secret(s) stored unencrypted: set {platform.secrets.env_var} and run `vma secrets rotate`",
            ["SOC2 CC6.1", "HIPAA 164.312(a)(2)(iv)"],
        )
    )
    oidc_enabled = bool(oidc.get("enabled")) and bool(oidc.get("issuer")) and bool(oidc.get("client_id"))
    checks.append(
        _check(
            "oidc.configured", "Single sign-on (OIDC) configured", "pass" if oidc_enabled else "warn",
            f"issuer {oidc.get('issuer')}" if oidc_enabled else "no identity provider configured; local passwords only",
            ["SOC2 CC6.1", "CIS 6.7"],
        )
    )
    docs_exposed = bool(security.get("api_docs", True))
    checks.append(
        _check(
            "api.docs", "API documentation exposed", "warn" if docs_exposed else "pass",
            "Swagger UI and the OpenAPI schema are served at /docs; set security.api_docs: false in production"
            if docs_exposed else "API docs disabled",
            ["CIS 4.8", "SOC2 CC6.6"],
        )
    )
    session_hours = _int(auth.get("session_hours"), 12)
    idle_minutes = _int(auth.get("idle_minutes"), 60)
    sane = 1 <= session_hours <= 24 and 5 <= idle_minutes <= 120
    checks.append(
        _check(
            "session.lifetime", "Session lifetime and idle timeout", "pass" if sane else "warn",
            f"session_hours={session_hours}, idle_minutes={idle_minutes}"
            + ("" if sane else "; recommended: at most 24 h absolute and 120 min idle"),
            ["SOC2 CC6.1", "HIPAA 164.312(a)(2)(iii)", "CIS 4.3"],
        )
    )
    threshold = _int(auth.get("lockout_threshold"), 0)
    lock_minutes = _int(auth.get("lockout_minutes"), 0)
    lockout_ok = 3 <= threshold <= 10 and lock_minutes >= 5
    checks.append(
        _check(
            "auth.lockout", "Login lockout configured", "pass" if lockout_ok else "warn",
            f"lockout_threshold={threshold}, lockout_minutes={lock_minutes}"
            + ("" if lockout_ok else "; recommended: 3-10 failures, at least 5 minutes"),
            ["SOC2 CC6.1", "CIS 6.2"],
        )
    )
    encrypt_inputs = bool(security.get("encrypt_run_inputs", False))
    if encrypt_inputs and platform.secrets.available:
        inputs_status, inputs_detail = "pass", "discovery.json is stored encrypted"
    elif encrypt_inputs:
        inputs_status, inputs_detail = "warn", "encrypt_run_inputs is on but no key is configured"
    else:
        inputs_status, inputs_detail = "warn", "security.encrypt_run_inputs=false; inventory data is stored in clear text under output/runs"
    checks.append(
        _check("runs.encrypt_inputs", "Run inputs encrypted at rest", inputs_status, inputs_detail, ["HIPAA 164.312(a)(2)(iv)", "SOC2 CC6.1", "CIS 3.11"])
    )
    allow_destroy = bool(deploy.get("allow_destroy", True))
    checks.append(
        _check(
            "deploy.allow_destroy", "Terraform destroy disabled", "pass" if not allow_destroy else "warn",
            "deploy.allow_destroy=false" if not allow_destroy else "deploy.allow_destroy=true; destructive applies are possible from the platform",
            ["SOC2 CC8.1", "CIS 4.1"],
        )
    )
    audit_days = _int(retention.get("audit_days"), 0)
    checks.append(
        _check(
            "retention.audit", "Audit retention configured", "pass" if audit_days > 0 else "warn",
            f"audit_days={audit_days}" + ("" if audit_days > 0 else " (entries are kept forever)"),
            ["SOC2 CC7.2", "HIPAA 164.316(b)(2)(i)", "CIS 8.10"],
        )
    )
    return checks
