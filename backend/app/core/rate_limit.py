"""
Redis-backed rate limiter for FastAPI endpoints.

Uses a sliding-window counter per client IP. Returns HTTP 429 with
Retry-After header when the limit is exceeded.

Bypass conditions (checked before hitting Redis):
  - Admin users (is_admin=True via JWT)
  - Explicitly exempted direct client IPs
  - Explicitly exempted paths

Usage:
    from app.core.rate_limit import RateLimiter

    @router.post("/login", dependencies=[Depends(RateLimiter("5/minute"))])
    async def login(...): ...
"""

import time
from ipaddress import IPv6Address, ip_address
from typing import Optional
from uuid import uuid4

import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request, status
from jwt.exceptions import PyJWTError
from starlette.responses import Response

from app.core.config import get_settings
from app.core.security import verify_token_claims

_settings = get_settings()

# Module-level Redis connection (created lazily)
_redis: Optional[redis.Redis] = None

# Paths that are always exempt from rate limiting
_EXEMPT_PATHS: set[str] = {
    "/api/v1/health",
}


def _canonical_ip(value: str) -> str | None:
    value = value.strip()
    if "%" in value:  # Scoped addresses are ambiguous across interfaces.
        return None
    try:
        address = ip_address(value)
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(address)


_TRUSTED_PROXIES = {ip for value in _settings.RATE_LIMIT_TRUSTED_PROXY_IPS if (ip := _canonical_ip(value))}
_BYPASS_IPS = {ip for value in _settings.RATE_LIMIT_BYPASS_IPS if (ip := _canonical_ip(value))}


async def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(
            _settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis


def _parse_rate(rate_str: str) -> tuple[int, int]:
    """Parse '5/minute' -> (5, 60). Supports minute, hour, day."""
    count, period = rate_str.strip().split("/")
    count = int(count)
    period = period.lower()
    windows = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
    }
    if period not in windows:
        raise ValueError(f"Unknown rate period: {period!r}. Use second/minute/hour/day.")
    return count, windows[period]


def _get_client_ip(request: Request) -> str:
    """Resolve one X-Forwarded-For chain from an explicitly trusted socket peer."""
    peer = _canonical_ip(request.client.host) if request.client else None
    if peer is None or peer not in _TRUSTED_PROXIES:
        return peer or "unknown"

    forwarded = request.headers.getlist("x-forwarded-for")
    if len(forwarded) != 1:
        return peer
    hops = [_canonical_ip(part) for part in forwarded[0].split(",")]
    # Trust only the suffix vouched for by known proxies. The first
    # non-proxy address from the right is the client for rate limiting.
    if None in hops:
        return peer
    for hop in reversed(hops):
        if hop is not None and hop not in _TRUSTED_PROXIES:
            return hop
    return peer


def _is_admin_user(request: Request) -> bool:
    """Check if the request carries a valid admin JWT token.

    Inspects the Authorization header without hitting the DB —
    we only check the ``is_admin`` claim that should be added
    to tokens at creation time (see identity/router.py).
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    token = auth_header.removeprefix("Bearer ").strip()
    if not token or _settings.JWT_ADMIN_BYPASS is False:
        return False
    try:
        payload = verify_token_claims(token)
    except PyJWTError:
        return False
    return (
        payload.get("type") == "access"
        and bool(payload.get("sub"))
        and payload.get("is_admin") is True
    )


class RateLimiter:
    """
    FastAPI dependency that enforces a per-IP rate limit.

    Parameters
    ----------
    rate : str
        Rate limit string, e.g. ``"5/minute"`` or ``"3/hour"``.
    key_prefix : str
        Redis key prefix to namespace different endpoints.
    bypass_admin : bool
        If True, skip rate limiting for admin JWT holders.
    """

    def __init__(
        self,
        rate: str = "60/minute",
        key_prefix: str = "rl",
        bypass_admin: bool = True,
    ):
        self.max_requests, self.window_seconds = _parse_rate(rate)
        self.key_prefix = key_prefix
        self.bypass_admin = bypass_admin

    async def __call__(self, request: Request, response: Response) -> None:
        # --- Bypass checks (no Redis round-trip) ---

        # 1. Exempt paths (health check, etc.)
        path = request.url.path.rstrip("/")
        if path in _EXEMPT_PATHS:
            return

        # 2. Only an explicitly exempt direct client can bypass by address.
        client_ip = _get_client_ip(request)
        if (
            client_ip in _BYPASS_IPS
            and client_ip not in _TRUSTED_PROXIES
            and request.client
            and client_ip == _canonical_ip(request.client.host)
        ):
            return

        # 3. Admin user bypass
        if self.bypass_admin and _is_admin_user(request):
            return

        # --- Rate limit check ---
        r = await _get_redis()
        key = f"{self.key_prefix}:{client_ip}:{path}"
        now = int(time.time())
        window_start = now - self.window_seconds

        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        pipe.zadd(key, {uuid4().hex: now})
        pipe.expire(key, self.window_seconds + 10)
        results = await pipe.execute()

        current_count = results[1]

        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, self.max_requests - current_count - 1)
        )
        response.headers["X-RateLimit-Reset"] = str(now + self.window_seconds)

        if current_count >= self.max_requests:
            retry_after = self.window_seconds
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )
