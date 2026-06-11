"""Authentication endpoints — register and obtain a bearer token.

These exist so owner-scoped routes (notably the cross-case link graph) have a
real authenticated identity to bind to instead of a client-supplied `owner_id`.
A token minted here is what lets a legitimate owner — and only the owner — query
or export their own cases.

No fallbacks: bad credentials fail loud with 401; a duplicate email fails with
409. Login deliberately returns the same 401 for unknown-email and wrong-password
so the endpoint is not a user-enumeration oracle.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from database import get_session
from db_setup import User
from ingest.services.auth_service import (
    create_access_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


class SignupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    # A full RFC-5322 validator is out of scope (no extra dep); a non-empty
    # string with an '@' is enough to key the account, and uniqueness is enforced
    # by the DB constraint.
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(req: SignupRequest, session: Session = Depends(get_session)) -> TokenResponse:
    """Register a new investigating officer and return a bearer token."""
    existing = session.exec(select(User).where(User.email == req.email)).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that email already exists.",
        )
    user = User(
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info("auth: registered user %s", user.id)
    return TokenResponse(access_token=create_access_token(user.id), user_id=str(user.id))


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    """Verify credentials and return a bearer token."""
    user = session.exec(select(User).where(User.email == req.email)).first()
    # Same response for unknown email and wrong password — no enumeration oracle.
    if user is None or not verify_password(req.password, user.password_hash):
        logger.warning("auth: failed login for %s", req.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    logger.info("auth: login for user %s", user.id)
    return TokenResponse(access_token=create_access_token(user.id), user_id=str(user.id))
