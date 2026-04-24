"""JWT authentication utilities.

Token lifecycle:
- Login: POST /api/v1/auth/token → returns {access_token, token_type}
- Protected routes: Depends(get_current_user) → validates Bearer token → returns User
- Tokens expire after 24 h; clock-skew tolerance is handled by python-jose
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db

_bearer = HTTPBearer(auto_error=False)

_ALGORITHM = "HS256"
_TOKEN_HOURS = 24


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=_TOKEN_HOURS),
    }
    return jwt.encode(payload, get_settings().SECRET_KEY, algorithm=_ALGORITHM)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: AsyncSession = Depends(get_db),
):
    """FastAPI dependency: validates Bearer JWT, returns the authenticated User.

    Raises HTTP 401 on missing/invalid/expired tokens.
    """
    from app.models.user import User

    _401 = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials:
        raise _401

    try:
        payload = jwt.decode(credentials.credentials, get_settings().SECRET_KEY, algorithms=[_ALGORITHM])
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise JWTError("missing sub")
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise _401
    return user
