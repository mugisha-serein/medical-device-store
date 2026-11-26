"""
Redis-backed rate limiter for FastAPI endpoints.

Uses a fixed-window counter per client IP. Returns HTTP 429 with
Retry-After header when the limit is exceeded.

Bypass conditions (checked before hitting Redis):
  - Admin users (is_admin=True via JWT)
  - Trusted proxy IPs (e.g. internal load balancer)
  - Explicitly exempted paths

Usage:
    from app.core.rate_limit import RateLimiter

    @router.post("/login", dependencies=[Depends(RateLimiter("5/minute"))])
    async def login(...): ...
"""

import time
from typing import Optional
from uuid import uuid4

import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request, status
from starlette.responses import Response

from app.core.config import get_settings

_settings = get_settings()

# Module-level Redis connection (created lazily)
_redis: Optional[redis.Redis] = None

# Paths that are always exempt from rate limiting
_EXEMPT_PATHS: set[str] = {
    "/api/v1/health",
}

# Trusted proxy IPs that are exempt (e.g. internal LB, monitoring)
_TRUSTED_PROXIES: set[str] = set(_settings.RATE_LIMIT_BYPASS_IPS)


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
    """Extract client IP, respecting X-Forwarded-For behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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
        from jose import jwt as jose_jwt
        payload = jose_jwt.decode(
            token,
            _settings.JWT_SECRET_KEY,
            algorithms=[_settings.JWT_ALGORITHM],
        )
        return payload.get("is_admin") is True
    except Exception:
        return False


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

        # 2. Trusted proxy IPs
        client_ip = _get_client_ip(request)
        if client_ip in _TRUSTED_PROXIES:
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
