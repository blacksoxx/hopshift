"""OpenID Connect sign-in: discovery, PKCE (S256), state and nonce, JWKS verification of the
id_token and claim-to-role mapping.

All HTTP goes through `OIDCClient.http()` which builds an `httpx.Client` with an optional
transport, so tests inject `httpx.MockTransport` (or monkeypatch `make_http_client`). Discovery
and JWKS documents are cached in memory; the JWKS is refetched once when a key id is unknown.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import warnings
from typing import Any, Callable

import httpx
from loguru import logger

from vma.errors import Forbidden, Invalid, Unavailable

with warnings.catch_warnings():
    # authlib installs an "always" filter for its own deprecation warning at import time; load that
    # module first so our "ignore" filter ends up in front of it, then import the (deprecated but
    # supported) jose API. The context restores the process-wide filters afterwards.
    from authlib.deprecate import AuthlibDeprecationWarning

    warnings.simplefilter("ignore", AuthlibDeprecationWarning)
    from authlib.jose import JsonWebKey, jwt
    from authlib.jose.errors import JoseError

__all__ = ["OIDCClient", "OIDCConfig", "JsonWebKey", "jwt", "make_http_client", "pkce_pair", "STATE_TTL_MINUTES"]

DISCOVERY_PATH = "/.well-known/openid-configuration"
CACHE_SECONDS = 3600
HTTP_TIMEOUT = 10.0
STATE_TTL_MINUTES = 10
DEFAULT_SCOPES = ("openid", "profile", "email")
ROLES = ("viewer", "operator", "admin")


def make_http_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Factory for the HTTP client used by OIDC calls; tests monkeypatch this or pass a transport."""
    return httpx.Client(timeout=HTTP_TIMEOUT, transport=transport, follow_redirects=False)


def pkce_pair() -> tuple[str, str]:
    """A PKCE code verifier (86 url-safe chars) and its S256 challenge."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class OIDCConfig:
    def __init__(self, raw: dict[str, Any] | None) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self.enabled = bool(raw.get("enabled", False))
        self.issuer = str(raw.get("issuer") or "").strip().rstrip("/")
        self.client_id = str(raw.get("client_id") or "").strip()
        self.client_secret_env = str(raw.get("client_secret_env") or "VMA_OIDC_CLIENT_SECRET").strip()
        scopes = raw.get("scopes") if isinstance(raw.get("scopes"), list) else list(DEFAULT_SCOPES)
        self.scopes = [str(item) for item in scopes if str(item).strip()] or list(DEFAULT_SCOPES)
        if "openid" not in self.scopes:
            self.scopes.insert(0, "openid")
        self.allowed_domains = [str(item).strip().lower().lstrip("@") for item in (raw.get("allowed_domains") or []) if str(item).strip()]
        default_role = str(raw.get("default_role") or "viewer").strip().lower()
        self.default_role = default_role if default_role in ROLES else "viewer"
        self.admin_groups = [str(item) for item in (raw.get("admin_groups") or []) if str(item).strip()]
        self.groups_claim = str(raw.get("groups_claim") or "groups").strip() or "groups"
        self.redirect_uri = str(raw.get("redirect_uri") or "").strip() or None

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.issuer) and bool(self.client_id)


class OIDCClient:
    def __init__(
        self,
        config: OIDCConfig,
        *,
        client_secret: Callable[[], str | None],
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._client_secret = client_secret
        self.transport = transport
        self._lock = threading.Lock()
        self._discovery: tuple[float, dict[str, Any]] | None = None
        self._jwks: tuple[float, dict[str, Any]] | None = None

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def http(self) -> httpx.Client:
        return make_http_client(self.transport)

    def discover(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            cached = self._discovery
            if cached is not None and not force and time.monotonic() - cached[0] < CACHE_SECONDS:
                return cached[1]
        url = self.config.issuer + DISCOVERY_PATH
        try:
            with self.http() as client:
                response = client.get(url)
                response.raise_for_status()
                document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise Unavailable(f"OIDC discovery failed for {self.config.issuer}: {exc.__class__.__name__}") from exc
        if not isinstance(document, dict) or not document.get("authorization_endpoint") or not document.get("token_endpoint"):
            raise Unavailable("OIDC discovery document is missing the authorization or token endpoint")
        if str(document.get("issuer") or "").rstrip("/") != self.config.issuer:
            raise Unavailable("OIDC discovery document issuer does not match security.auth.oidc.issuer")
        with self._lock:
            self._discovery = (time.monotonic(), document)
        return document

    def jwks(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            cached = self._jwks
            if cached is not None and not force and time.monotonic() - cached[0] < CACHE_SECONDS:
                return cached[1]
        document = self.discover()
        jwks_uri = document.get("jwks_uri")
        if not jwks_uri:
            raise Unavailable("OIDC discovery document has no jwks_uri")
        try:
            with self.http() as client:
                response = client.get(str(jwks_uri))
                response.raise_for_status()
                keys = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise Unavailable(f"OIDC JWKS fetch failed: {exc.__class__.__name__}") from exc
        if not isinstance(keys, dict) or not isinstance(keys.get("keys"), list):
            raise Unavailable("OIDC JWKS document is malformed")
        with self._lock:
            self._jwks = (time.monotonic(), keys)
        return keys

    # ── flow ──────────────────────────────────────────────────────────────────

    def authorization_url(self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
        document = self.discover()
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return str(httpx.URL(str(document["authorization_endpoint"]), params=params))

    def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> dict[str, Any]:
        document = self.discover()
        secret = self._client_secret()
        if not secret:
            raise Unavailable(f"OIDC client secret is not set: export {self.config.client_secret_env}")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.config.client_id,
            "client_secret": secret,
            "code_verifier": code_verifier,
        }
        try:
            with self.http() as client:
                response = client.post(str(document["token_endpoint"]), data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise Unavailable(f"OIDC token exchange failed: {exc.__class__.__name__}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise Invalid("OIDC token endpoint returned a non-JSON response") from exc
        if response.status_code >= 400 or not isinstance(payload, dict) or not payload.get("id_token"):
            error = payload.get("error") if isinstance(payload, dict) else None
            logger.warning("oidc: token exchange rejected ({}): {}", response.status_code, error or "no id_token")
            raise Invalid("OIDC token exchange was rejected by the identity provider")
        return payload

    def verify_id_token(self, id_token: str, *, nonce: str) -> dict[str, Any]:
        claims_options = {
            "iss": {"essential": True, "values": [self.config.issuer, self.config.issuer + "/"]},
            "aud": {"essential": True, "value": self.config.client_id},
            "exp": {"essential": True},
            "nonce": {"essential": True, "value": nonce},
        }
        last_error: Exception | None = None
        for attempt in range(2):
            key_set = self.jwks(force=attempt == 1)  # a JWKS document; authlib picks the key by `kid`
            try:
                claims = jwt.decode(id_token, key_set, claims_options=claims_options)
                claims.validate(leeway=60)
                return dict(claims)
            except (JoseError, ValueError) as exc:
                last_error = exc
                message = str(exc).lower()
                if attempt == 0 and ("kid" in message or "key" in message):
                    continue  # unknown key id: refetch the JWKS once (key rotation at the provider)
                break
        logger.warning("oidc: id_token rejected: {}", last_error.__class__.__name__ if last_error else "unknown")
        raise Invalid("OIDC id_token failed verification")

    def userinfo(self, access_token: str) -> dict[str, Any]:
        document = self.discover()
        endpoint = document.get("userinfo_endpoint")
        if not endpoint or not access_token:
            return {}
        try:
            with self.http() as client:
                response = client.get(str(endpoint), headers={"Authorization": f"Bearer {access_token}"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    # ── claims to identity ────────────────────────────────────────────────────

    def identity_from_claims(self, claims: dict[str, Any]) -> dict[str, Any]:
        """Extract subject, username, email, name, role; enforce allowed_domains."""
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise Invalid("OIDC id_token has no subject")
        email = str(claims.get("email") or "").strip().lower() or None
        preferred = str(claims.get("preferred_username") or "").strip().lower() or None
        username = email or preferred
        if not username:
            raise Invalid("OIDC id_token carries neither email nor preferred_username; add the email scope")
        if self.config.allowed_domains:
            domain = (email or "").rsplit("@", 1)[-1] if email and "@" in email else ""
            if domain not in self.config.allowed_domains:
                raise Forbidden("your email domain is not allowed to sign in")
        groups_raw = claims.get(self.config.groups_claim)
        if isinstance(groups_raw, str):
            groups = [groups_raw]
        elif isinstance(groups_raw, list):
            groups = [str(item) for item in groups_raw]
        else:
            groups = []
        role = "admin" if any(group in self.config.admin_groups for group in groups) else self.config.default_role
        name = str(claims.get("name") or "").strip() or username
        return {
            "subject": subject,
            "username": username,
            "email": email,
            "name": name,
            "role": role,
            "groups": groups,
            "email_verified": bool(claims.get("email_verified", False)),
        }
