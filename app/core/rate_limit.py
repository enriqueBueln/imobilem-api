"""Lightweight in-process login rate limiter.

Protects POST /auth/login from two abuses that the Argon2 cost alone does not stop:
- online password brute force against predictable B2B emails, and
- CPU exhaustion (every attempt forces a full Argon2 hash on the server).

This is a per-IP sliding-window counter kept in memory. It is intentionally
dependency-free for the initial phase. It does NOT survive a restart and is NOT
shared across multiple worker processes — for production-scale, per-account lockout
and a shared store (Redis) are the documented next step.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

# Max login attempts allowed per client IP within the window.
_MAX_ATTEMPTS = 10
_WINDOW_SECONDS = 60.0

# Per-IP timestamps (monotonic seconds) of recent attempts.
_attempts: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    client = request.client
    return client.host if client is not None else "unknown"


def enforce_login_rate_limit(request: Request) -> None:
    """Record this attempt and raise 429 if the client IP exceeded the window budget.

    Counts every attempt (not just failures) so a single source cannot fan out
    unlimited Argon2 verifications. The 429 is generic and never reveals whether
    the targeted account exists.
    """
    now = time.monotonic()
    bucket = _attempts[_client_ip(request)]

    cutoff = now - _WINDOW_SECONDS
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()

    if len(bucket) >= _MAX_ATTEMPTS:
        retry_after = max(1, int(_WINDOW_SECONDS - (now - bucket[0])))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espera un momento e intenta de nuevo.",
            headers={"Retry-After": str(retry_after)},
        )

    bucket.append(now)


def reset_login_rate_limit() -> None:
    """Clear all counters. For tests only."""
    _attempts.clear()
