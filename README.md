# AWS Cloud Security Purple Team Lab

Phase 1 provides a small local FastAPI foundation for the later AWS security lab. Its only custom API endpoint is `GET /health`; generated API documentation is available in local and development environments and disabled in test and production. Authentication, file handling, PostgreSQL connectivity, AWS integration, infrastructure, and security tooling are intentionally deferred.

## Prerequisites

- Python 3.11 or newer
- Docker Desktop or another Docker Engine (for container execution)

## Run locally

From PowerShell in the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

In a second terminal, test the endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json
```

Run the automated test suite with:

```powershell
python -m pytest
```

## Run with Docker

```powershell
docker build --tag aws-purple-team-lab:phase1 .
docker run --rm --name aws-purple-team-lab --publish 127.0.0.1:8000:8000 aws-purple-team-lab:phase1
```

Test `http://127.0.0.1:8000/health` from a second terminal. Stop the foreground container with `Ctrl+C`.

## Configuration

Settings are read from environment variables beginning with `APP_`. For local development, copy `.env.example` to `.env`. The real `.env` file is ignored by both Git and Docker build context so local values are not committed or baked into the image. The application refuses to start when `APP_ENVIRONMENT=production` and `APP_DEBUG=true` are combined.
