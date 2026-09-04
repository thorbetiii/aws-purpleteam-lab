"""Test-process configuration established before application module imports."""

import os


# app.main validates settings while creating its module-level FastAPI instance.
# Port 1 is intentionally unreachable: liveness tests must not contact PostgreSQL.
os.environ["APP_DATABASE_URL"] = (
    "postgresql+psycopg://test_user:test_password@127.0.0.1:1/test_db"
)
os.environ["APP_JWT_SECRET"] = (
    "test-only-jwt-signing-secret-never-use-in-a-real-environment"
)
