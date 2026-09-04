"""HTTP error handling that prevents credential reflection."""

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request


_REDACTED = "[redacted]"


def _redact_password_values(value: Any) -> Any:
    """Recursively replace values carried under password-shaped keys."""
    if isinstance(value, dict):
        return {
            key: (
                _REDACTED
                if isinstance(key, str) and key.lower() == "password"
                else _redact_password_values(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_password_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_password_values(item) for item in value)
    return value


async def request_validation_error_handler(
    _: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return normal validation details without echoing submitted passwords."""
    sanitized_errors: list[dict[str, Any]] = []
    for error in exc.errors():
        sanitized_error = dict(error)
        location = sanitized_error.get("loc", ())
        if "password" in location:
            sanitized_error["input"] = _REDACTED
        elif "input" in sanitized_error:
            sanitized_error["input"] = _redact_password_values(
                sanitized_error["input"]
            )
        sanitized_errors.append(sanitized_error)

    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(sanitized_errors)},
    )
