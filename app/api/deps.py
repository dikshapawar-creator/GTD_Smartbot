from typing import Generator
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy.orm import Session, joinedload
from app.core.config import settings
from app.core.dependencies import get_db
from app.schemas.auth import TokenData
from app.models.auth import User

import logging
logger = logging.getLogger(__name__)

# HTTPBearer shows a clean "Bearer token" input box in Swagger UI /docs
bearer_scheme = HTTPBearer()

async def get_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> str:
    """Extract raw token string from Authorization: Bearer <token> header."""
    return credentials.credentials

async def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(get_token)
) -> User:
    """
    Validate JWT and return User with:
    - Active check
    - Token version check
    - Multi-tenant data ready
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        token_version: int = payload.get("token_version")
        if user_id is None or token_version is None:
            logger.warning(f"JWT context missing user_id or token_version. Payload: {payload}")
            raise credentials_exception
    except Exception as e:
        logger.error(f"JWT Decode failed: {str(e)} | Token starts with: {token[:10]}...")
        raise credentials_exception
        
    user = db.query(User).options(joinedload(User.role)).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
        
    # Security Validation
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")
        
    if user.token_version != token_version:
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")
        
    return user

def require_role(min_level: int):
    """
    Enforce numeric role hierarchy.
    Usage: Depends(require_role(2)) # Requires Admin or higher
    """
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role.level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Minimum level {min_level} required."
            )
        return current_user
    return role_checker
