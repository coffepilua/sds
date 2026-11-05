import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from .models import RefreshSession, User

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./medical_navigator.db")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
MEDIA_BASE_URL = os.getenv("CLOUD_MEDIA_BASE_URL", "").rstrip("/")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
ACCESS_TTL, REFRESH_DAYS, MAX_FILE = 900, 7, 10 * 1024 * 1024

engine = create_engine(
    DATABASE_URL,
    **({"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {"pool_pre_ping": True}),
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db


class ApiError(Exception):
    def __init__(self, status, code, message="", details=None):
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def utcnow():
    return datetime.now(timezone.utc)


# --- пароли и токены -------------------------------------------------------
_ph = PasswordHasher()


def hash_pw(p):
    return _ph.hash(p)


def check_pw(h, p):
    try:
        return _ph.verify(h, p)
    except (VerifyMismatchError, InvalidHashError):
        return False


def access_token(u):
    exp = utcnow() + timedelta(seconds=ACCESS_TTL)
    return jwt.encode({"sub": str(u.id), "role": u.role, "exp": exp}, SECRET_KEY, "HS256")


def sha(t):
    return hashlib.sha256(t.encode()).hexdigest()


# --- refresh-сессия: она же серверная сессия для HTML-дашбордов --------------
def new_session(db, user):
    raw = secrets.token_urlsafe(32)
    db.add(RefreshSession(user_id=user.id, token_hash=sha(raw), expires_at=utcnow() + timedelta(days=REFRESH_DAYS)))
    return raw


def session_user(db, raw):
    if not raw:
        return None
    s = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == sha(raw), RefreshSession.revoked.is_(False)))
    if not s:
        return None
    exp = s.expires_at if s.expires_at.tzinfo else s.expires_at.replace(tzinfo=timezone.utc)
    if exp < utcnow():
        return None
    u = db.get(User, s.user_id)
    return u if u and u.is_active else None


def end_session(db, raw):
    s = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == sha(raw))) if raw else None
    if s:
        s.revoked = True
        db.commit()


def set_cookie(resp, raw):
    resp.set_cookie("refresh", raw, httponly=True, secure=COOKIE_SECURE, samesite="lax",
                    max_age=REFRESH_DAYS * 86400, path="/")


def media_url(u):
    if not u:
        return None
    if u.startswith(("http://", "https://")):
        return u
    return f"{MEDIA_BASE_URL}/{u.lstrip('/')}" if MEDIA_BASE_URL else None


# --- зависимости -----------------------------------------------------------
def current_user(request: Request, db=Depends(get_db)):
    h, u = request.headers.get("authorization", ""), None
    if h.lower().startswith("bearer "):
        try:
            u = db.get(User, int(jwt.decode(h[7:], SECRET_KEY, algorithms=["HS256"])["sub"]))
        except Exception:
            u = None
    elif request.method == "GET":  # cookie-сессия допустима только для чтения (скачивание файлов, чат)
        u = session_user(db, request.cookies.get("refresh"))
    if not u or not u.is_active:
        raise ApiError(401, "UNAUTHORIZED", "Требуется вход")
    return u


def require(*roles):
    def dep(u=Depends(current_user)):
        if u.role not in roles:
            raise ApiError(403, "FORBIDDEN", "Нет доступа")
        return u
    return dep
