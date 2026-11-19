"""
Redis-backed brute-force protection for login endpoints.

Tracks failed login attempts per email address using Redis counters
with automatic TTL expiry. Accounts are locked after a configurable
number of failures within a time window.

Usage in router:
    from app.core.brute_force import BruteForceProtector

    protector = BruteForceProtector()

    # Before checking password:
    await protector.check_locked(email)

    # On successful login:
    await protector.record_success(email)

    # On failed login:
    await protector.record_failure(email)
"""

import time
from typing import Optional

import redis.asyncio as redis

from app.core.config import get_settings

_settings = get_settings()

# Module-level Redis connection (shared with rate limiter)
_redis: Optional[redis.Redis] = None


async def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(
            _settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis


class BruteForceProtector:
    """
    Per-email brute-force protector backed by Redis.

    Parameters
    ----------
    max_failures : int | None
        Number of failed attempts before lockout. Defaults to config.
    lockout_seconds : int | None
        How long the lockout lasts (in seconds). Defaults to config.
    window_seconds : int | None
        Time window for counting failures (sliding). Defaults to config.
    """

    def __init__(
        self,
        max_failures: Optional[int] = None,
        lockout_seconds: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ):
        self.max_failures = max_failures or _settings.BF_MAX_FAILURES
        self.lockout_seconds = lockout_seconds or _settings.BF_LOCKOUT_SECONDS
        self.window_seconds = window_seconds or _settings.BF_WINDOW_SECONDS

    def _failure_key(self, email: str) -> str:
        return f"bf:fail:{email.lower()}"

    def _lockout_key(self, email: str) -> str:
        return f"bf:lock:{email.lower()}"

    async def is_locked(self, email: str) -> bool:
        """Check if the account is currently locked."""
        r = await _get_redis()
        lock_val = await r.get(self._lockout_key(email))
        return lock_val is not None

    async def check_locked(self, email: str) -> None:
        """
        Raise if the account is locked. Call this BEFORE password verification.

        Raises
        ------
        LockedException
            If the account is locked. The exception carries the remaining
            seconds until auto-unlock.
        """
        r = await _get_redis()
        lock_key = self._lockout_key(email)
        ttl = await r.ttl(lock_key)
        if ttl > 0:
            raise LockedException(
                email=email,
                retry_after=ttl,
            )

    async def record_failure(self, email: str) -> dict:
        """
        Record a failed login attempt. Returns lockout status.

        Returns
        -------
        dict with keys:
            locked: bool — whether the account is now locked
            attempts: int — number of failures in the current window
            remaining: int — attempts left before lockout (0 if locked)
        """
        r = await _get_redis()
        email_lower = email.lower()
        failure_key = self._failure_key(email_lower)
        lock_key = self._lockout_key(email_lower)
        now = int(time.time())
        window_start = now - self.window_seconds

        pipe = r.pipeline()
        # Clean old entries outside the window
        pipe.zremrangebyscore(failure_key, 0, window_start)
        # Add this failure
        pipe.zadd(failure_key, {f"{now}:{time.monotonic_ns()}": now})
        # Count failures in window
        pipe.zcard(failure_key)
        # Set TTL on failure key
        pipe.expire(failure_key, self.window_seconds + 60)
        results = await pipe.execute()

        attempt_count = results[2]

        # Check if we should lock
        if attempt_count >= self.max_failures:
            # Lock the account
            await r.setex(lock_key, self.lockout_seconds, "locked")
            # Set expiry on failure key too
            await r.expire(failure_key, self.lockout_seconds + 60)
            return {
                "locked": True,
                "attempts": attempt_count,
                "remaining": 0,
            }

        return {
            "locked": False,
            "attempts": attempt_count,
            "remaining": max(0, self.max_failures - attempt_count),
        }

    async def record_success(self, email: str) -> None:
        """
        Clear failure history on successful login.
        The lockout key (if any) is also removed.
        """
        r = await _get_redis()
        email_lower = email.lower()
        await r.delete(self._failure_key(email_lower), self._lockout_key(email_lower))

    async def get_status(self, email: str) -> dict:
        """
        Get current lockout/failure status for an email.
        Used by admin endpoints and diagnostics.
        """
        r = await _get_redis()
        email_lower = email.lower()
        failure_key = self._failure_key(email_lower)
        lock_key = self._lockout_key(email_lower)

        pipe = r.pipeline()
        pipe.ttl(lock_key)
        pipe.zcard(failure_key)
        results = await pipe.execute()

        lock_ttl = results[0]
        failure_count = results[1]

        return {
            "email": email_lower,
            "locked": lock_ttl > 0,
            "lockout_remaining_seconds": max(0, lock_ttl),
            "failures_in_window": failure_count,
            "max_failures": self.max_failures,
        }

    async def unlock(self, email: str) -> dict:
        """
        Manually unlock an account and clear failure history.
        Returns the status after unlocking.
        """
        r = await _get_redis()
        email_lower = email.lower()
        await r.delete(self._failure_key(email_lower), self._lockout_key(email_lower))
        return await self.get_status(email)


class LockedException(Exception):
    """Raised when a brute-force lockout is active."""

    def __init__(self, email: str, retry_after: int):
        self.email = email
        self.retry_after = retry_after
        super().__init__(
            f"Account {email} is locked. Try again in {retry_after} seconds."
        )
