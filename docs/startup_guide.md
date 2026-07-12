# Startup Guide

This guide explains how to run the project with Docker by default, plus the
legacy local development commands when needed.

## Prerequisites

- Docker Desktop for the default one-command startup.
- Python 3.11+, Node.js 18+, and npm only when running the legacy local development commands.

## One-Command Docker Startup

From the project root:

```powershell
.\start.ps1
```

You can also double-click `start.bat` on Windows. The launcher creates
`deploy/.env` and `deploy/backend.env` from their examples when needed, runs
`docker compose up -d --build`, waits for `http://localhost/health`, and opens:

```text
http://localhost
```

Docker Desktop must be installed and running.

## Local Development Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Check:

```text
http://localhost:8000/health
```

## Local Development Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

## Manual Docker Commands

The same Docker Compose files are used by `start.ps1` and on cloud servers:

```bash
cp deploy/backend.env.example deploy/backend.env
cp deploy/.env.example deploy/.env
cd deploy
docker compose up -d --build
```

To stop the Docker deployment:

```bash
cd deploy
docker compose down
```

The old local development scripts are still available when you specifically
need hot-reload debugging without containers:

```powershell
.\scripts\start_backend.ps1
.\scripts\start_frontend.ps1
```

In VS Code, press `Ctrl+Shift+B` and choose:

```text
启动智能家居仿真实验平台
```

## Cloud Deployment

For cloud servers, use the same Docker Compose files in `deploy/`:

```bash
cp deploy/backend.env.example deploy/backend.env
cp deploy/.env.example deploy/.env
cd deploy
docker compose up -d --build
```

The frontend container exposes port `80` and proxies API traffic to the backend
container. This matches the default one-command startup path.

More details:

```text
docs/cloud_deployment.md
```

## Environment Variables

Docker mode uses `deploy/backend.env`, created automatically by `start.ps1`
from `deploy/backend.env.example`. Local development without Docker uses
`backend/.env`.

```env
APP_ENV=local
LLM_MODE=mock
BACKEND_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
REAL_LLM_API_KEY=
REAL_LLM_BASE_URL=
REAL_LLM_MODEL=
REAL_LLM_MODEL_REVISION=
REAL_LLM_RESOURCE_ID=
REAL_LLM_TIMEOUT_SECONDS=12
REAL_LLM_MAX_TOKENS=600
REAL_LLM_STREAM=true
```

Use `LLM_MODE=mock` for deterministic local tests. Use `LLM_MODE=real` only after configuring a compatible chat completion endpoint and API key.

The personalization ablation defaults to `backend/.env`. When validating the
Docker-served local model, pass `--env-file deploy/backend.env`; otherwise the
host-side experiment may not use the same semantic endpoint/model as the live
service. Record the immutable Ollama digest in `REAL_LLM_MODEL_REVISION` before
making a version-specific model claim.

## Validation

```powershell
python scripts\verify_real_llm.py
python scripts\run_batch_experiments.py --limit 5
python scripts\run_reproduction_experiments.py --limit 3 --real-mode mock
```

Generated files are written under:

```text
data/logs/
data/results/
```

These folders are ignored by Git except for `.gitkeep` files.

## Common Issues

- Docker engine not running: start Docker Desktop, wait until it is ready, then run `start.bat` again.
- Docker Hub pull timeout or `failed to fetch oauth token`: edit `deploy/.env` and set `DOCKER_HUB_PREFIX=m.daocloud.io/docker.io/library/`, then run `start.bat` again.
- Port `80` already in use: edit `deploy/.env` and set `FRONTEND_PORT` to another value such as `8080`.
- Frontend cannot load state in Docker mode: confirm `http://localhost/health` works and the backend container is healthy.
- Backend connection failed in local development mode: confirm port `8000` is running.
- Frontend cannot load state in local development mode: confirm `VITE_API_BASE_URL` or default `http://localhost:8000`.
- Real LLM validation failed: check `.env`, endpoint URL, model name, API key, and provider response format.
- No experiment output: check that the selected task JSON exists under `data/tasks/`.
