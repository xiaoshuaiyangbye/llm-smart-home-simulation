# Startup Guide

This guide explains how to run the project locally.

## Prerequisites

- Python 3.11+
- Node.js 18+
- npm

## Backend

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

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

## One-Command Startup

From the project root:

```powershell
.\scripts\start_backend.ps1
.\scripts\start_frontend.ps1
```

In VS Code, press `Ctrl+Shift+B` and choose:

```text
启动智能家居仿真实验平台
```

## Environment Variables

Copy `backend/.env.example` to `backend/.env`.

```env
APP_ENV=local
LLM_MODE=mock
REAL_LLM_API_KEY=
REAL_LLM_BASE_URL=
REAL_LLM_MODEL=
REAL_LLM_RESOURCE_ID=
REAL_LLM_TIMEOUT_SECONDS=12
REAL_LLM_MAX_TOKENS=600
REAL_LLM_STREAM=true
```

Use `LLM_MODE=mock` for deterministic local tests. Use `LLM_MODE=real` only after configuring a compatible chat completion endpoint and API key.

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

- Backend connection failed: confirm port `8000` is running.
- Frontend cannot load state: confirm `VITE_API_BASE_URL` or default `http://localhost:8000`.
- Real LLM validation failed: check `.env`, endpoint URL, model name, API key, and provider response format.
- No experiment output: check that the selected task JSON exists under `data/tasks/`.
