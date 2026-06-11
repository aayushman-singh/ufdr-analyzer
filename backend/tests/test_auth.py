"""E2E + unit tests for authentication (signup/login -> bearer token).

These prove the issuance side of the owner-scoping fix: a real credential
(password) is required to obtain a token, the token round-trips through
`require_user`, and bad credentials fail loud (401) without leaking which half
was wrong.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("CROSS_CASE_SALT", "test-cross-case-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import db_setup  # noqa: E402,F401
from db_setup import User  # noqa: E402
from ingest.services.auth_service import (  # noqa: E402
    create_access_token,
    decode_access_token,
    hash_password,
    require_user,
    verify_password,
)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _client(session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from database import get_session
    from ingest.routers import auth_router

    app = FastAPI()
    app.include_router(auth_router.router)
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app, raise_server_exceptions=False)


# -- password hashing --------------------------------------------------------
def test_hash_and_verify_roundtrip():
    h = hash_password("correct horse battery staple")
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_salted_unique():
    assert hash_password("same") != hash_password("same")  # random salt


def test_verify_rejects_legacy_placeholder_hash():
    # Seeded demo users carry "hashed_password_N" placeholders — never a match.
    assert verify_password("anything", "hashed_password_1") is False
    assert verify_password("anything", "") is False


def test_empty_password_rejected():
    with pytest.raises(ValueError):
        hash_password("")


# -- token round-trip --------------------------------------------------------
def test_token_roundtrip():
    uid = uuid.uuid4()
    assert decode_access_token(create_access_token(uid)) == uid


def test_decode_garbage_token_401():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        decode_access_token("garbage.token.here")
    assert ei.value.status_code == 401


def test_token_signed_with_other_key_is_rejected(monkeypatch):
    import jwt

    bad = jwt.encode({"sub": str(uuid.uuid4())}, "different-key", algorithm="HS256")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        decode_access_token(bad)
    assert ei.value.status_code == 401


# -- require_user dependency -------------------------------------------------
def test_require_user_resolves_known_user(session):
    u = User(username="IO", email="io@x.gov", password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)
    from fastapi.security import HTTPAuthorizationCredentials

    creds = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=create_access_token(u.id)
    )
    assert require_user(creds=creds, session=session).id == u.id


def test_require_user_no_credentials_401(session):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        require_user(creds=None, session=session)
    assert ei.value.status_code == 401


# -- signup / login routes ---------------------------------------------------
def test_signup_then_login_flow(session):
    c = _client(session)
    su = c.post(
        "/auth/signup",
        json={"username": "Io", "email": "io@x.gov", "password": "s3cretpw!"},
    )
    assert su.status_code == 201
    tok = su.json()
    assert tok["token_type"] == "bearer" and tok["access_token"]
    assert decode_access_token(tok["access_token"]) == uuid.UUID(tok["user_id"])

    li = c.post("/auth/login", json={"email": "io@x.gov", "password": "s3cretpw!"})
    assert li.status_code == 200
    assert decode_access_token(li.json()["access_token"]) == uuid.UUID(tok["user_id"])


def test_signup_duplicate_email_409(session):
    c = _client(session)
    body = {"username": "Io", "email": "dup@x.gov", "password": "s3cretpw!"}
    assert c.post("/auth/signup", json=body).status_code == 201
    assert c.post("/auth/signup", json=body).status_code == 409


def test_login_wrong_password_401(session):
    c = _client(session)
    c.post(
        "/auth/signup",
        json={"username": "Io", "email": "io@x.gov", "password": "s3cretpw!"},
    )
    res = c.post("/auth/login", json={"email": "io@x.gov", "password": "nope-nope"})
    assert res.status_code == 401


def test_login_unknown_email_401_same_as_wrong_password(session):
    c = _client(session)
    res = c.post("/auth/login", json={"email": "ghost@x.gov", "password": "whatever1"})
    assert res.status_code == 401  # no user-enumeration distinction


def test_signup_short_password_422(session):
    c = _client(session)
    res = c.post(
        "/auth/signup", json={"username": "Io", "email": "io@x.gov", "password": "短"}
    )
    assert res.status_code == 422  # min_length enforced
