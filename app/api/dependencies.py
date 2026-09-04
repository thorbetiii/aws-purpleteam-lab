"""Reusable FastAPI dependencies for bearer-authenticated requests."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import AuthenticationTokenError, decode_access_token
from app.db.session import get_db_session
from app.models import User


bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


def _authentication_error() -> HTTPException:
    """Build the uniform failure returned for every bearer-token problem."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """Validate a bearer token and load its current PostgreSQL user."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_error()

    try:
        user_id = decode_access_token(credentials.credentials, settings=settings)
    except AuthenticationTokenError as exc:
        raise _authentication_error() from exc

    user = session.get(User, user_id)
    if user is None:
        raise _authentication_error()
    return user
