"""Authentication — identity verification for owner-scoped endpoints.

The repo historically had no session layer: any caller could hit any route and,
for the cross-case link graph, pass an arbitrary `owner_id` (or none) and learn
whether an identifier appears across cases — a PII / membership oracle. This
module closes that hole by turning a bearer credential into an *authenticated
user identity*, which owner-scoped endpoints bind their `owner_id` to instead of
trusting a client-supplied value.

Mechanism (no fallbacks, fail loud):
- Passwords are hashed with PBKDF2-HMAC-SHA256 + a per-user random salt
  (`hash_password` / `verify_password`), stored in a self-describing
  `pbkdf2_sha256$iterations$salt$hash` string — stdlib only, no native build.
- A successful login mints a short-lived JWT (HS256) signed with `SECRET_KEY`;
  the token's `sub` is the user id.
- `require_user` is a FastAPI dependency: it parses `Authorization: Bearer
  <token>`, verifies the signature + expiry, loads the user, and returns it.
  A missing, malformed, expired, or unknown-subject token is rejected with 401 —
  never silently treated as anonymous.

`SECRET_KEY` is required for both signing and verifying. If it is absent the
auth path raises rather than degrading to an unsigned/again-oracle mode.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import secrets
import uuid
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from database import get_session
from db_setup import User

# PBKDF2 parameters. Iteration count is high enough to make offline cracking
# costly; encoded into the hash string so it can be raised later without breaking
# existing hashes.
_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 600_000
_SALT_BYTES = 16

_ALGORITHM = "HS256"
# Token lifetime. Short enough to bound a leaked token's blast radius; long
# enough for an interactive analyst session. Tune per deployment.
ACCESS_TOKEN_TTL = datetime.timedelta(hours=12)

# Bearer extractor. auto_error=False so we raise our own loud, contextual 401
# (with WWW-Authenticate) rather than FastAPI's terse default.
_bearer = HTTPBearer(auto_error=False)


def _secret_key() -> str:
    """The HMAC key for signing/verifying tokens. Required — fail loud."""
    key = os.getenv("SECRET_KEY")
    if not key:
        raise RuntimeError(
            "SECRET_KEY is not configured — cannot issue or verify auth tokens."
        )
    return key


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 hash of a plaintext password, with a random salt.

    Returns a self-describing string: `pbkdf2_sha256$iterations$salt_hex$hash_hex`.
    """
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"{_PBKDF2_ALGO}${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """True iff `password` matches `password_hash` (constant-time compare).

    Returns False (not an exception) for an empty input or a non-PBKDF2/legacy
    hash, so seeded demo users with placeholder hashes simply fail to
    authenticate — they are never granted access on a malformed hash.
    """
    if not password or not password_hash:
        return False
    try:
        algo, iterations_s, salt_hex, expected_hex = password_hash.split("$")
        if algo != _PBKDF2_ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations_s),
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(dk.hex(), expected_hex)


def create_access_token(user_id: uuid.UUID | str) -> str:
    """Mint a signed JWT whose subject is `user_id`."""
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, _secret_key(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Verify a JWT and return its subject user id.

    Raises `HTTPException(401)` on any failure (bad signature, expiry, missing or
    non-UUID subject) — an invalid token must never resolve to a valid identity.
    """
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return uuid.UUID(str(sub))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is not a valid user id.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    session: Session = Depends(get_session),
) -> User:
    """FastAPI dependency: resolve the authenticated user or reject with 401.

    A missing/empty Authorization header, a non-Bearer scheme, an invalid token,
    or a token whose subject no longer maps to a user are all rejected — there is
    no anonymous path through this dependency.
    """
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: supply a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_access_token(creds.credentials)
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject does not correspond to a known user.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
