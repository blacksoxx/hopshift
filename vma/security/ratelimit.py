"""Per-IP token-bucket throttling for the credential endpoints (login, setup).

Pure ASGI middleware so it sits in front of everything else and costs nothing on other paths.
Over-limit requests get 429 with a Retry-After header. Evidence for CIS Control 6.2 / SOC 2 CC6.1
(brute-force resistance) alongside the per-user lockout in the service.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

DEFAULT_PATHS: tuple[str, ...] = ("/api/auth/login", "/api/auth/setup")


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class TokenBucketLimiter:
    """`rate_per_minute` sustained requests per key, bursting up to `burst` (defaults to the rate)."""

    rate_per_minute: float = 20.0
    burst: float | None = None
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_prune: float = field(default_factory=time.monotonic)

    @property
    def capacity(self) -> float:
        return float(self.burst if self.burst is not None else self.rate_per_minute)

    def acquire(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Take one token for `key`. Returns (allowed, retry_after_seconds)."""
        moment = time.monotonic() if now is None else now
        refill_per_second = self.rate_per_minute / 60.0
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity, updated=moment)
                self._buckets[key] = bucket
            else:
                bucket.tokens = min(self.capacity, bucket.tokens + (moment - bucket.updated) * refill_per_second)
                bucket.updated = moment
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                allowed, retry_after = True, 0
            else:
                allowed = False
                retry_after = max(1, int((1.0 - bucket.tokens) / refill_per_second + 0.999))
            if moment - self._last_prune > 300:
                self._prune(moment)
        return allowed, retry_after

    def _prune(self, moment: float) -> None:
        stale = [key for key, bucket in self._buckets.items() if moment - bucket.updated > 600]
        for key in stale:
            del self._buckets[key]
        self._last_prune = moment


def client_ip(scope: dict[str, Any]) -> str:
    headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers") or []}
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


class RateLimitMiddleware:
    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        limiter: TokenBucketLimiter | None = None,
        paths: Iterable[str] = DEFAULT_PATHS,
        methods: Iterable[str] = ("POST",),
    ) -> None:
        self.app = app
        self.limiter = limiter or TokenBucketLimiter()
        self.paths = frozenset(paths)
        self.methods = frozenset(method.upper() for method in methods)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("method", "").upper() in self.methods and scope.get("path") in self.paths:
            allowed, retry_after = self.limiter.acquire(client_ip(scope))
            if not allowed:
                body = json.dumps({"detail": "too many requests; try again later"}).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 429,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode("ascii")),
                            (b"retry-after", str(retry_after).encode("ascii")),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
