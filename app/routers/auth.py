"""
Auth endpoints.

POST /api/auth/login   → { role, token, display_name }
POST /api/auth/logout  → { ok: true }
GET  /api/auth/me      → same as login response (uses bearer token)

Tokens are signed JWTs with an expiry time.
"""

import os
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from app.models.schema import LoginRequest, LoginResponse, UserRole
from app.data_store import USERS, VALID_DOMAINS
from app.database import SessionLocal, UserRow, consume_password_reset, create_password_reset
from sqlalchemy import select

router = APIRouter()
PASSWORD_HASH = PasswordHash.recommended()
JWT_SECRET = os.getenv('JWT_SECRET', 'change-this-development-secret')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRY_HOURS = 8


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


def _validate(email: str, password: str) -> tuple[bool, str | None, str | None]:
    """Returns (ok, error_message, display_name)."""
    parts = email.split('@')
    if len(parts) != 2 or parts[1] not in VALID_DOMAINS:
        return False, 'Email must use a BUA domain (@bua.edu.eg).', None
    if len(password) < 8:
        return False, 'Password must be at least 8 characters.', None
    # Access is granted only to configured accounts.
    for u in USERS:
        if u['email'].lower() == email.lower() and PASSWORD_HASH.verify(password, u['password']):
            return True, None, u['name']
    return False, 'Invalid email or password.', None


def _make_token(email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        'sub': email.lower(),
        'role': role,
        'iat': now,
        'exp': now + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _parse_token(token: str) -> tuple[str, str] | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email = payload.get('sub')
        role = payload.get('role')
        if not isinstance(email, str) or not isinstance(role, str):
            return None
        return email, role
    except jwt.PyJWTError:
        return None


def is_admin_authorization(authorization: str) -> bool:
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        return False
    parsed = _parse_token(token)
    if not parsed:
        return False
    email, role = parsed
    return role == 'admin' and any(
        u['email'].lower() == email.lower() and u['role'] == 'admin'
        for u in USERS
    )


def get_email_from_auth(authorization: str) -> str | None:
    """Return the JWT subject email, or None if missing/invalid."""
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        return None
    parsed = _parse_token(token)
    return parsed[0] if parsed else None


def require_admin(authorization: str) -> None:
    if not is_admin_authorization(authorization):
        raise HTTPException(status_code=403, detail='Only admins can perform this action.')


@router.post('/login', response_model=LoginResponse)
def login(body: LoginRequest):
    ok, err, name = _validate(body.email, body.password)
    if not ok:
        raise HTTPException(status_code=401, detail=err)
    user = next(u for u in USERS if u['email'].lower() == body.email.lower())
    role: UserRole = user['role']
    token = _make_token(body.email, role)
    return LoginResponse(role=role, token=token, display_name=name or body.email)


@router.post('/logout')
def logout():
    return {'ok': True}


@router.post('/forgot-password')
def forgot_password(body: ForgotPasswordRequest):
    email = body.email.strip().lower()
    with SessionLocal() as db:
        user_exists = db.scalar(select(UserRow.id).where(UserRow.email == email)) is not None
    if not user_exists:
        raise HTTPException(status_code=404, detail='No account found for this email.')
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    reset_token = create_password_reset(email, expires_at)
    return {'ok': True, 'reset_token': reset_token, 'expires_in_minutes': 15}


@router.post('/reset-password')
def reset_password(body: ResetPasswordRequest):
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail='Password must be at least 8 characters.')
    if not consume_password_reset(body.token.strip(), PASSWORD_HASH.hash(body.new_password)):
        raise HTTPException(status_code=400, detail='Invalid or expired reset token.')
    return {'ok': True}


@router.get('/me', response_model=LoginResponse)
def me(authorization: str = Header(default='')):
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise HTTPException(status_code=401, detail='Not authenticated')
    parsed = _parse_token(token)
    if not parsed:
        raise HTTPException(status_code=401, detail='Invalid token')
    email, role = parsed
    name = next((u['name'] for u in USERS if u['email'].lower() == email.lower()), email)
    return LoginResponse(role=role, token=token, display_name=name)  # type: ignore[arg-type]
