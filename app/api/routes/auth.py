"""Registration, login, and current-user authentication endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password_or_dummy,
)
from app.db.session import get_db_session
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserPublic,
)


router = APIRouter(prefix="/auth", tags=["authentication"])


def _is_username_unique_violation(error: IntegrityError) -> bool:
    """Recognize only PostgreSQL's named username uniqueness violation."""
    original_error = error.orig
    diagnostic = getattr(original_error, "diag", None)
    return (
        getattr(original_error, "sqlstate", None) == "23505"
        and getattr(diagnostic, "constraint_name", None)
        == "uq_users_username"
    )


def _invalid_credentials_error() -> HTTPException:
    """Return one response for unknown usernames and incorrect passwords."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Register a user account",
)
def register_user(
    registration: RegisterRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> UserPublic:
    """Hash a password and explicitly create a least-privileged user."""
    user = User(
        username=registration.username,
        password_hash=hash_password(registration.password.get_secret_value()),
        role="user",
    )
    session.add(user)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if _is_username_unique_violation(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username is already registered",
            ) from exc
        raise

    session.refresh(user)
    return UserPublic.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange credentials for an access token",
)
def login(
    credentials: LoginRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Verify credentials and issue a short-lived signed bearer token."""
    user = session.scalar(
        select(User).where(User.username == credentials.username)
    )
    stored_hash = user.password_hash if user is not None else None
    password_is_valid = verify_password_or_dummy(
        credentials.password.get_secret_value(),
        stored_hash,
    )
    if user is None or not password_is_valid:
        raise _invalid_credentials_error()

    access_token = create_access_token(user_id=user.id, settings=settings)
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Return the authenticated user",
)
def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserPublic:
    """Return only the safe public representation of the token's user."""
    return UserPublic.model_validate(current_user)
