# llm-smart-home-simulation

`llm-smart-home-simulation` is a local smart-home simulation platform for testing natural-language device control, rule-based planning, virtual device execution, and closed-loop environment feedback.

The project does not control real home devices. It provides a reproducible software sandbox with a FastAPI backend, a React 3D frontend, virtual rooms/devices, energy and comfort models, and optional OpenAI-compatible LLM semantic parsing.

## Features

- Backend: Python + FastAPI for state management, virtual device control, environment simulation, agent orchestration, and CSV log export.
- Frontend: React + TypeScript + Vite + `@react-three/fiber` for a 3D smart-home control panel.
- Agent flow: semantic parsing, task planning, action execution, feedback evaluation, and up to 3 correction rounds.
- LLM mode: supports `mock` mode for deterministic local testing and `real` mode for an OpenAI-compatible chat completion endpoint.
- Experiments: includes reusable batch tasks, reproduction experiments, life simulation scripts, and summary/report generation.
- Safety: `.env`, runtime folders, dependency folders, build output, logs, and generated results are excluded from Git.

## Project Layout

```text
backend/    FastAPI backend, simulation models, schemas, agents, and experiment runners
frontend/   React/Vite frontend and 3D scene components
scripts/    setup, startup, validation, and experiment scripts
data/       sample task definitions; generated logs/results are ignored
docs/       system, startup, collaboration, and standards notes
```

## Quick Start

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Backend health check:

```text
http://localhost:8000/health
```

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend URL:

```text
http://localhost:5173
```

### 3. VS Code Task

Open the project in VS Code, press `Ctrl+Shift+B`, and choose:

```text
启动智能家居仿真实验平台
```

## LLM Configuration

The backend reads configuration from `backend/.env`.

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

Modes:

- `LLM_MODE=mock`: deterministic local semantic parsing, suitable for setup and demos.
- `LLM_MODE=real`: calls an OpenAI-compatible HTTP endpoint for semantic parsing.

Keep API keys only in `backend/.env`. Do not commit real credentials.

Validate real LLM connectivity:

```powershell
python scripts\verify_real_llm.py
```

## Useful Scripts

Run a small batch experiment:

```powershell
python scripts\run_batch_experiments.py --limit 5
```

Run reproduction experiments:

```powershell
python scripts\run_reproduction_experiments.py --limit 3 --real-mode mock
```

Run a short life simulation:

```powershell
python scripts\run_weekly_life_simulation.py --duration day
```

Run seasonal life simulation:

```powershell
python scripts\run_seasonal_life_simulation.py
```

Generated logs and reports are written under `data/logs/` and `data/results/`, which are ignored by Git.

## API Overview

- `GET /health`: backend health check.
- `GET /api/state`: current smart-home state.
- `POST /api/agent/command`: run the semantic-planning-execution-feedback flow for a natural-language command.
- `POST /api/reset`: reset the simulation state.
- `GET /api/logs/export`: export CSV logs.

## Notes

This project is intended for software simulation, prototyping, and reproducible experiments. The environment, energy, lighting, humidity, and comfort models are simplified approximations and should not be used as real building design, inspection, or home automation logic.
