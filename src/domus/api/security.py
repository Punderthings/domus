"""Password hashing, opaque tokens, and login rate limiting."""

import hashlib
import secrets
import threading
import time
from collections import deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

SESSION_COOKIE = "domus_session"
CSRF_COOKIE = "domus_csrf"
CSRF_HEADER = "x-csrf-token"
TOKEN_PREFIX = "domus_pat_"  # noqa: S105 - a public prefix, not a secret
MIN_PASSWORD_LENGTH = 12

# A real hash, so a login for an unknown email costs the same time as a wrong password.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except VerificationError, InvalidHashError:
        return False


def new_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Tokens are high-entropy, so a fast hash is enough; only hashes are stored."""
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


class LoginRateLimiter:
    """Counts failed logins per key in a sliding window (in memory, per process)."""

    def __init__(self, max_failures: int, window_seconds: float) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, time.monotonic())) >= self.max_failures

    def fail(self, key: str) -> None:
        with self._lock:
            self._prune(key, time.monotonic()).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
