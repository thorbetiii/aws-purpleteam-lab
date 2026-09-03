# AWS Cloud Security Purple Team Lab

Phase 2 extends the Phase 1 FastAPI foundation with a local PostgreSQL data layer. PostgreSQL runs in Docker, while FastAPI continues to run directly from the local Python environment. SQLAlchemy supplies the models, connection pool, and request-scoped sessions; Psycopg connects SQLAlchemy to PostgreSQL; and Alembic owns all schema creation and later schema changes.

The only custom HTTP endpoint remains `GET /health`. Authentication, password hashing, file transfer, S3 integration, AWS infrastructure, CI/CD, and purple-team behavior are intentionally outside this phase.

## Data architecture

- `app/core/config.py` requires one typed `APP_DATABASE_URL`. Database credentials are not embedded in Python code.
- `app/db/base.py` contains the shared SQLAlchemy declarative base established in Phase 1.
- `app/db/session.py` lazily creates one process-wide engine and session factory, yields one session per FastAPI dependency scope, closes each session afterward, and disposes the connection pool when FastAPI stops.
- `app/models/` defines `User` and `FileMetadata`. One user can own many file-metadata rows. The foreign key restricts deleting a user while their metadata still exists.
- `alembic/` contains the migration environment and ordered schema revisions. The application does not call `Base.metadata.create_all()` at startup.
- `compose.yaml` runs only PostgreSQL and persists its database cluster in the named `postgres_data` volume.

PostgreSQL stores only file metadata. File bytes are deliberately absent from the schema because a later phase will store object content outside the database.

## Prerequisites

- Python 3.11 or newer
- Docker Desktop or another Docker Engine with Docker Compose

All commands below are PowerShell commands run from the repository root.

## 1. Prepare Python and local configuration

Create and activate a virtual environment, then install the application and development dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Create the ignored local environment file once:

```powershell
Copy-Item .env.example .env
```

The values in `.env.example` are disposable development examples, not real credentials. Before starting PostgreSQL, review `.env` and keep these values consistent:

- `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` initialize the local container.
- `POSTGRES_PORT` selects the loopback host port exposed by Compose.
- `APP_DATABASE_URL` is the required SQLAlchemy/Psycopg URL used by both the application and Alembic. Its database, username, password, and port must match the local PostgreSQL values.

If a password contains URL-reserved characters, percent-encode it in `APP_DATABASE_URL`. Never commit `.env`; it is excluded by both Git and the Docker build context.

## 2. Start PostgreSQL and confirm health

Start only the database service:

```powershell
docker compose up --detach postgres
```

Check Compose health status, then ask PostgreSQL itself whether it is accepting connections:

```powershell
docker compose ps postgres
docker compose exec postgres sh -c 'pg_isready --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"'
```

The Compose status should become `healthy`, and `pg_isready` should report `accepting connections`.

## 3. Apply and inspect migrations

Create the Phase 2 schema through Alembic:

```powershell
python -m alembic upgrade head
python -m alembic current
```

List the resulting tables directly in PostgreSQL:

```powershell
docker compose exec postgres sh -c 'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --command "\dt"'
```

The expected application tables are `users` and `file_metadata`; Alembic also maintains `alembic_version`.

To verify that the application configuration, SQLAlchemy, Psycopg, and PostgreSQL work together, run:

```powershell
@'
from sqlalchemy import text

from app.db import get_engine

with get_engine().connect() as connection:
    database_name = connection.scalar(text("SELECT current_database()"))
    print(f"Connected to PostgreSQL database: {database_name}")
'@ | python -
```

## 4. Run tests

The focused unit tests validate required URL handling, startup validation, lazy engine/session behavior, cleanup, model constraints and relationships, and PostgreSQL-dialect DDL without substituting SQLite for PostgreSQL behavior:

```powershell
python -m pytest
```

The database commands in the previous sections provide the real PostgreSQL migration and connectivity smoke test without making every unit-test run depend on Docker.

## 5. Start FastAPI and verify Phase 1 health behavior

Start FastAPI locally:

```powershell
python -m uvicorn app.main:app --reload
```

In a second terminal, verify the process health endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json
```

Generated API documentation remains available at `http://127.0.0.1:8000/docs` in local and development environments, and remains disabled in test and production.

`/health` intentionally remains a process-health check rather than a database readiness check. A valid `APP_DATABASE_URL` is required to configure and start the application, but `/health` does not open a database connection. Use the explicit connectivity command above when diagnosing the database layer.

## 6. Stop PostgreSQL

Stop the local database while preserving its named volume:

```powershell
docker compose down
```

Only when a complete local reset is intentional, remove the database volume as well. This permanently deletes the local database contents:

```powershell
docker compose down --volumes
```

## Verify the existing application image

Compose does not containerize FastAPI in Phase 2. The existing application image can still be built and its `/health` endpoint checked independently (port `8001` avoids colliding with a locally running server):

```powershell
docker build --tag aws-purple-team-lab:phase2-check .
docker run --detach --rm `
    --name aws-purple-team-lab-phase2-check `
    --env "APP_DATABASE_URL=postgresql+psycopg://healthcheck:unused@127.0.0.1:1/healthcheck" `
    --publish 127.0.0.1:8001:8000 `
    aws-purple-team-lab:phase2-check
Invoke-RestMethod http://127.0.0.1:8001/health | ConvertTo-Json
docker stop aws-purple-team-lab-phase2-check
```

The verification URL is syntactically valid but intentionally unreachable from the container. A successful `/health` response therefore confirms liveness without turning the endpoint into a PostgreSQL readiness check.

## Later RDS transition

The persistence code depends on PostgreSQL rather than on Docker. A later RDS phase can supply an RDS endpoint, credentials from the selected secret mechanism, and required TLS options through `APP_DATABASE_URL`, then apply these same Alembic revisions. The SQLAlchemy models and session dependency should not need environment-specific rewrites. No RDS resources are provisioned in Phase 2.

## Configuration behavior

Settings are read from environment variables beginning with `APP_`. `APP_DATABASE_URL` is required and must use the `postgresql+psycopg` scheme; missing or invalid configuration prevents the application from starting. The application also refuses to start when `APP_ENVIRONMENT=production` and `APP_DEBUG=true` are combined. PostgreSQL reachability is deliberately not part of `/health`; a separate dependency-readiness endpoint will be added before deployment.
