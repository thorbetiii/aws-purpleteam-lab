# AWS Cloud Security Purple Team Lab

Phase 3, version 0.3.0, adds a small first-party authentication layer to the FastAPI and PostgreSQL foundation from Phases 1 and 2. Users can register, log in for a short-lived JWT access token, and use that bearer token to retrieve their current public user record. Passwords are hashed with Argon2 through `pwdlib[argon2]`; PyJWT signs and validates access tokens.

The Phase 2 PostgreSQL, SQLAlchemy, Psycopg, Alembic, and Docker development workflow remains in place. `GET /health` also retains its Phase 1 liveness-only behavior. Phase 3 does not add file operations, S3 or other AWS infrastructure, RDS provisioning, Terraform, CI/CD, readiness checks, refresh tokens, OAuth providers, admin endpoints, or purple-team functionality.

## Architecture

- `app/core/config.py` owns typed `APP_*` settings. The PostgreSQL URL and JWT signing secret are required; the secret uses Pydantic's secret type and is excluded from normal settings representations.
- `app/core/security.py` contains the password hashing and verification helpers plus JWT creation and decoding. It has no database responsibility.
- `app/schemas/auth.py` defines the registration and login inputs, the safe public-user output, and the access-token output. Authentication inputs reject undeclared fields such as `role`.
- `app/api/routes/auth.py` implements `POST /auth/register`, `POST /auth/login`, and `GET /auth/me`. It coordinates validation, security helpers, and the existing SQLAlchemy session.
- `app/api/dependencies.py` provides the reusable current-user dependency: extract a bearer token, validate it, parse its user ID, and load that user from PostgreSQL.
- `app/api/errors.py` preserves useful `422` validation details while redacting submitted password values before they can be reflected in an API response.
- `app/db/session.py` continues to provide a request-scoped SQLAlchemy session backed by one lazily created process-wide engine and connection pool.
- `app/models/user.py` maps the existing `users` table. Its public API representation includes only `id`, `username`, `role`, and `created_at`; `password_hash` is never serialized.
- `alembic/` remains the sole owner of schema creation and changes. The existing Phase 2 schema already contains the required user identity, password-hash, role, and timestamp columns, so Phase 3 does not add a meaningless migration and the application still never calls `Base.metadata.create_all()`.
- `compose.yaml` continues to run only PostgreSQL and persist its cluster in the named `postgres_data` volume.

PostgreSQL stores user identities and file metadata. File bytes remain deliberately absent from the schema because object storage belongs to a later phase.

## Authentication flows

### Registration

`POST /auth/register` validates the JSON input, trims surrounding whitespace from the username, converts it to lowercase, hashes the password, and inserts the user through the existing SQLAlchemy session. The transaction commits explicitly. If PostgreSQL reports the username uniqueness conflict, the transaction is rolled back and the API returns a clean `409 Conflict`.

Self-registration always writes the `user` role. The request schema does not expose a role field and rejects extra input, so a client that submits `"role": "admin"` receives a validation error rather than an administrator account. The response is the safe public-user representation and never contains `password_hash`.

### Login

`POST /auth/login` applies the same username normalization, loads the user from PostgreSQL, and verifies the submitted password against the stored Argon2 hash. An unknown username and an incorrect password produce the same generic `401 Unauthorized` response so the endpoint does not disclose which credential was wrong. The unknown-user path performs a dummy Argon2 verification as well, reducing the timing difference between those two failures.

Successful login returns a signed access token, the `bearer` token type, and its lifetime in seconds. This is a direct JSON API login; Phase 3 does not introduce an external OAuth provider, authorization-code flow, or refresh token.

### Authenticated requests

`GET /auth/me` requires `Authorization: Bearer <access-token>`. The reusable dependency extracts the token, verifies its signature with an explicit algorithm allowlist, checks expiration, parses the immutable database user ID from the `sub` claim, and loads the current user from PostgreSQL. Missing, malformed, tampered, expired, or unknown-user tokens are rejected. A valid token returns the same safe public-user representation as registration.

The database lookup is intentional: a correctly signed token alone does not establish that its subject still maps to a current user.

## Security decisions

### Usernames and passwords

Usernames must be 3–64 ASCII characters after surrounding whitespace is removed and are stored in lowercase. They may contain lowercase letters, digits, periods, underscores, and hyphens, and must start and end with a letter or digit. Consequently, `Alice`, ` alice `, and `ALICE` all resolve to `alice`. The ordinary PostgreSQL unique constraint can therefore enforce one account per normalized username without a case-insensitive extension or extra database infrastructure.

Passwords must be 12–128 characters, cannot consist only of whitespace, and are not normalized or trimmed. The 12-character minimum encourages passphrases and raises the floor for weak choices; the 128-character maximum still permits long password-manager values while bounding request and password-hashing work. Plaintext passwords must never be stored, logged, or included in tokens or responses.

`pwdlib`'s recommended password hasher uses Argon2, a salted, deliberately memory-intensive one-way password-hashing algorithm. Each hash encodes the salt and work parameters needed for later verification. Login hashes/checks the supplied plaintext under those parameters and compares it to the stored result; it does not decrypt the database value. Because hashing uses a random salt, the stored value differs from the plaintext and two registrations using the same password need not produce identical hashes.

### JWT access tokens

PyJWT signs access tokens with HS256. A token contains only the database user ID in `sub` and the standard expiration claim needed for this flow. The default lifetime is 15 minutes.

A JWT signature detects token modification and lets this API authenticate the issuer; it does not encrypt the claims. A JWT also does not hide data from its holder, protect a stolen bearer token, revoke a token before expiration, or replace the current-user database lookup. Keep access tokens out of source files, URLs, logs, and tracked documentation. Phase 3 intentionally has no refresh-token or revocation mechanism.

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

The values in `.env.example` are disposable development examples, not real credentials. Replace its JWT placeholder in the ignored `.env` with a new random secret. For example, generate 32 random bytes and encode them as text:

```powershell
$jwtSecretBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($jwtSecretBytes)
[Convert]::ToBase64String($jwtSecretBytes)
```

Copy the command's output to `APP_JWT_SECRET` in `.env`. Do not put that value in `.env.example`, README examples, source code, container images, or Git. Use a different secret for each environment, obtain deployed secrets from an appropriate secret manager, and replace a secret immediately if it is exposed. Changing the signing secret invalidates outstanding tokens.

Review these settings before starting the application:

| Setting | Requirement and behavior |
| --- | --- |
| `APP_DATABASE_URL` | Required SQLAlchemy/Psycopg URL. It must use `postgresql+psycopg`, and its local database, username, password, and port must agree with the Compose values. |
| `APP_JWT_SECRET` | Required JWT signing secret of at least 32 characters. It is loaded as `SecretStr` and must be supplied from the environment, never hardcoded. |
| `APP_JWT_ALGORITHM` | Explicit signing algorithm. Phase 3 supports and defaults to `HS256`. |
| `APP_JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime in minutes. It defaults to `15` and accepts values from 1 through 60. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT` | Local Compose database initialization and port settings. |

If a database password contains URL-reserved characters, percent-encode it in `APP_DATABASE_URL`. Never commit `.env`; it is excluded by both Git and the Docker build context.

## 2. Start PostgreSQL and confirm database health

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

Create or update the local schema through Alembic:

```powershell
python -m alembic upgrade head
python -m alembic current
```

List the resulting tables directly in PostgreSQL:

```powershell
docker compose exec postgres sh -c 'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --command "\dt"'
```

The expected application tables are `users` and `file_metadata`; Alembic also maintains `alembic_version`.

To verify that application configuration, SQLAlchemy, Psycopg, and PostgreSQL work together, run:

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

Run the complete suite:

```powershell
python -m pytest
```

The suite covers configuration, session cleanup, PostgreSQL schema semantics, unchanged health behavior, username normalization, Argon2 hashing and verification, JWT creation and rejection, registration rules, duplicate users, generic login failures, and authenticated `/auth/me` requests.

Most tests remain fast and isolated. When `APP_TEST_DATABASE_URL` is absent, the real-PostgreSQL authentication integration test is reported as skipped. Create the disposable test database once while the Compose PostgreSQL service is running:

```powershell
docker compose exec postgres sh -c 'createdb --username "$POSTGRES_USER" --owner "$POSTGRES_USER" purple_team_lab_test'
```

Then open a separate PowerShell window for the test database, so the normal application terminal keeps its development-database configuration. Alembic reads `APP_DATABASE_URL`, while the opt-in integration fixture reads `APP_TEST_DATABASE_URL`, so set both to the same test-only URL before migrating and running the complete suite:

```powershell
$testDatabaseUrl = "postgresql+psycopg://purple_team_app:local-dev-only-change-me@127.0.0.1:5432/purple_team_lab_test"
$env:APP_DATABASE_URL = $testDatabaseUrl
$env:APP_TEST_DATABASE_URL = $testDatabaseUrl

python -m alembic upgrade head
python -m alembic current
python -m pytest

Remove-Item Env:APP_TEST_DATABASE_URL
Remove-Item Env:APP_DATABASE_URL
```

If `createdb` reports that the database already exists, do not recreate it; proceed with `alembic upgrade head`. The URL must use `postgresql+psycopg` and the database must contain the Alembic-managed `users` table. The integration test creates uniquely named users and removes those exact rows afterward, but it is still safest never to point `APP_TEST_DATABASE_URL` at a database containing data you need. The test suite does not silently substitute SQLite for PostgreSQL-specific persistence behavior.

## 5. Start FastAPI and verify liveness

Start FastAPI locally:

```powershell
python -m uvicorn app.main:app --reload
```

In a second terminal, verify the process health endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json
```

Generated API documentation remains available at `http://127.0.0.1:8000/docs` in local and development environments, and remains disabled in test and production.

`/health` intentionally remains a process-liveness check rather than a database readiness check. Valid `APP_DATABASE_URL` and `APP_JWT_SECRET` settings are required to configure and start the application, but `/health` opens no database connection. Authentication endpoints do use PostgreSQL. Use the explicit connectivity command above when diagnosing the database layer. There is no `/ready` endpoint in Phase 3; dependency readiness remains deferred until before AWS deployment.

## 6. Register a user

Registration accepts JSON containing only `username` and `password`:

```json
{
  "username": " Alice ",
  "password": "local-demo-passphrase"
}
```

Send the request:

```powershell
$registration = @{
    username = " Alice "
    password = "local-demo-passphrase"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8000/auth/register `
    -ContentType "application/json" `
    -Body $registration | ConvertTo-Json
```

A successful registration returns `201 Created` and a response shaped like:

```json
{
  "id": 1,
  "username": "alice",
  "role": "user",
  "created_at": "2026-09-04T12:00:00Z"
}
```

The server always assigns `user`. A submitted `role` field is rejected, a duplicate normalized username returns `409 Conflict`, and no response includes a password or password hash.

## 7. Log in

Login also accepts JSON:

```json
{
  "username": "ALICE",
  "password": "local-demo-passphrase"
}
```

Capture the token response in PowerShell:

```powershell
$login = @{
    username = "ALICE"
    password = "local-demo-passphrase"
} | ConvertTo-Json

$token = Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8000/auth/login `
    -ContentType "application/json" `
    -Body $login

$token | ConvertTo-Json
```

A successful response is shaped like:

```json
{
  "access_token": "<signed-JWT>",
  "token_type": "bearer",
  "expires_in": 900
}
```

Incorrect usernames and passwords both return the same generic `401 Unauthorized` authentication failure.

## 8. Call `/auth/me` with the bearer token

Use the token only in the `Authorization` header:

```powershell
$headers = @{
    Authorization = "$($token.token_type) $($token.access_token)"
}

Invoke-RestMethod `
    -Method Get `
    -Uri http://127.0.0.1:8000/auth/me `
    -Headers $headers | ConvertTo-Json
```

The response is the safe public representation for the token's PostgreSQL user. Omitting the header or supplying an invalid, expired, malformed, or unknown-user token returns `401 Unauthorized`.

## 9. Stop PostgreSQL

Stop the local database while preserving its named volume:

```powershell
docker compose down
```

Only when a complete local reset is intentional, remove the database volume as well. This permanently deletes the local database contents:

```powershell
docker compose down --volumes
```

## Verify the application image

Compose still does not containerize FastAPI. Build the non-root application image and supply both required application settings when running it. The algorithm and lifetime are shown explicitly even though they have defaults:

```powershell
docker build --tag aws-purple-team-lab:phase3-check .
docker run --detach --rm `
    --name aws-purple-team-lab-phase3-check `
    --env "APP_DATABASE_URL=postgresql+psycopg://healthcheck:unused@127.0.0.1:1/healthcheck" `
    --env "APP_JWT_SECRET=disposable-container-check-secret-at-least-32-characters" `
    --env "APP_JWT_ALGORITHM=HS256" `
    --env "APP_JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15" `
    --publish 127.0.0.1:8001:8000 `
    aws-purple-team-lab:phase3-check
Invoke-RestMethod http://127.0.0.1:8001/health | ConvertTo-Json
docker stop aws-purple-team-lab-phase3-check
```

The example database URL is syntactically valid but intentionally unreachable from the container. A successful `/health` response therefore confirms image startup, its non-root runtime, required configuration, and liveness semantics without turning the endpoint into a PostgreSQL readiness check. To exercise authentication in a container, supply a reachable PostgreSQL URL instead. The displayed JWT secret is disposable test text; never reuse it outside this one local check.

## Later RDS transition

The persistence code depends on PostgreSQL rather than on Docker. A later RDS phase can supply an RDS endpoint, credentials from the selected secret mechanism, and required TLS options through `APP_DATABASE_URL`, then apply the same Alembic revisions. The SQLAlchemy models and session dependency should not need environment-specific rewrites. No RDS resources are provisioned in Phase 3.

## Configuration behavior

Settings are read from environment variables beginning with `APP_`. `APP_DATABASE_URL` is required and must use the `postgresql+psycopg` scheme; `APP_JWT_SECRET` is required and must contain at least 32 characters. Missing or invalid configuration prevents the application from starting. The application also refuses to start when `APP_ENVIRONMENT=production` and `APP_DEBUG=true` are combined. PostgreSQL reachability remains deliberately outside `/health`; a separate dependency-readiness endpoint will be added before deployment.
