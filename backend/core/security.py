from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

from .config import settings


class TokenData(BaseModel):
    user_id: UUID
    org_id: UUID
    email: str
    role: str


# bcrypt's hard 72-byte input limit applies to every hash/verify call.
# Truncate up front rather than letting bcrypt raise: matches passlib's
# historical behavior and avoids silently-locking-out edge-case users.
_BCRYPT_MAX = 72


def _truncate(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX]


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_truncate(password), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(plain), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash on disk — treat as verification failure, don't crash.
        return False


def create_access_token(data: TokenData, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(data.user_id),
        "org_id": str(data.org_id),
        "email": data.email,
        "role": data.role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return TokenData(
            user_id=UUID(payload["sub"]),
            org_id=UUID(payload["org_id"]),
            email=payload["email"],
            role=payload["role"],
        )
    except (JWTError, KeyError, ValueError) as exc:
        raise ValueError("Invalid or expired token") from exc
