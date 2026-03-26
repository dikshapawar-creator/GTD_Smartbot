import bcrypt
import hmac
import hashlib
import secrets
import string
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Union, Optional
from jose import jwt
from app.core.config import settings

def validate_password(password: str) -> bool:
    """
    Enforce:
    - Minimum 8 characters
    - At least 1 uppercase, 1 lowercase, 1 number, 1 special character
    """
    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False
    return True

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its hash."""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    """Generate a bcrypt hash of the password."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def create_access_token(
    user_id: int, 
    email: str, 
    role_name: str, 
    role_level: int, 
    tenant_id: int,           # Kept for backward compat — equals primary_tenant_id
    token_version: int,
    primary_tenant_id: int = None,
    tenant_ids: list = None,
    is_super_admin: bool = False,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a short-lived JWT access token with full multi-tenant metadata."""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "exp": expire,
        "sub": str(user_id),
        "email": email,
        "role": role_name,
        "role_level": role_level,
        "tenant_id": tenant_id,                              # backward compat
        "primary_tenant_id": primary_tenant_id or tenant_id, # new
        "tenant_ids": tenant_ids or [tenant_id],             # new: list of accessible tenants
        "is_super_admin": is_super_admin,                    # new: bypass flag
        "token_version": token_version,
        "jti": secrets.token_hex(16),
        "type": "access",
        "iat": datetime.now(timezone.utc)
    }
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT access token."""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        return None

def hash_token(token: str) -> str:
    """Harden refresh/reset tokens by storing SHA256 hashes."""
    return hashlib.sha256(token.encode()).hexdigest()

def secure_compare(val1: str, val2: str) -> bool:
    """Constant-time comparison for security tokens."""
    return hmac.compare_digest(val1, val2)

def generate_tenant_key(length: int = 10) -> str:
    """Generate a short, URL-safe tenant identifier (e.g. 'gtd_7a2b9c')."""
    # Using lowercase and digits for maximum URL compatibility and readability
    characters = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(characters) for _ in range(length))
