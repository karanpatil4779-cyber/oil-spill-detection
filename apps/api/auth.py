"""JWT authentication utilities."""

import os
import hmac
import hashlib
import base64
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET", "oil-spill-sih2026-dev-secret-change-in-production")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

# Password hashing uses PBKDF2-HMAC-SHA256 from the standard library.
# This avoids the well-known passlib 1.7.4 <-> bcrypt >=4.x incompatibility
# that causes seeded demo credentials to silently fail to verify on some
# stacks (notably the lean Python 3.11 Render build).
_PBKDF2_ITERATIONS = 260_000
_PBKDF2_SALT_BYTES = 16
_HASH_ALGO = "sha256"


def _pbkdf2(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(_HASH_ALGO, password.encode("utf-8"), salt, iterations)


def hash_password(password: str) -> str:
    """Return a self-describing '$pbkdf2-sha256$iter$salt$hash' string."""
    salt = os.urandom(_PBKDF2_SALT_BYTES)
    dk = _pbkdf2(password, salt, _PBKDF2_ITERATIONS)
    return "$pbkdf2-sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(plain: str, stored: str) -> bool:
    if not stored or not stored.startswith("$pbkdf2-sha256$"):
        # Backwards-compatible fallback for any legacy bcrypt hashes that may
        # already be in the DB.
        try:
            from passlib.context import CryptContext
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            return pwd_context.verify(plain, stored)
        except Exception:  # noqa: BLE001
            return False
    try:
        _scheme, _algo, iterations_s, salt_b64, hash_b64 = stored.split("$")
        iterations = int(iterations_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = _pbkdf2(plain, salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:  # noqa: BLE001
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
