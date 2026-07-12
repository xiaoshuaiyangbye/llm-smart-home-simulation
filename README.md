# llm-smart-home-simulation

`llm-smart-home-simulation` is a local smart-home simulation platform for testing natural-language device control, rule-based planning, virtual device execution, and closed-loop environment feedback.

The project does not control real home devices. It provides a reproducible software sandbox with a FastAPI backend, a React 3D frontend, virtual rooms/devices, energy and comfort models, and optional OpenAI-compatible LLM semantic parsing.

## Features

- Backend: Python + FastAPI for state management, virtual device control, environment simulation, agent orchestration, and CSV log export.
- Frontend: React + TypeScript + Vite + `@react-three/fiber` for a 3D smart-home control panel.
- Agent flow: semantic parsing, task planning, action execution, feedback evaluation, and up to 3 correction rounds.
- Multi-agent RAG flow: local knowledge retrieval, comfort analysis, energy review, safety review, critic review, execution, and feedback are written to an inspectable blackboard.
- LLM mode: supports `mock` mode for deterministic local testing and `real` mode for an OpenAI-compatible chat completion endpoint.
- Experiments: includes reusable batch tasks, reproduction experiments, life simulation scripts, and summary/report generation.
- Safety: `.env`, runtime folders, dependency folders, build output, logs, and generated results are excluded from Git.

## Project Layout

```text
backend/    FastAPI backend, simulation models, schemas, agents, and experiment runners
frontend/   React/Vite frontend and 3D scene components
deploy/     Docker Compose, Nginx, and cloud deployment environment templates
scripts/    setup, startup, validation, and experiment scripts
data/       sample task definitions; generated logs/results are ignored
docs/       system, startup, collaboration, and standards notes
```

## Quick Start

### One-click startup on Windows

Double-click `start.bat`, or run this from the project root:

```powershell
.\start.ps1
```

The launcher now uses the Docker Compose deployment path by default. It creates
`deploy/.env` and `deploy/backend.env` from their examples when needed, builds
and starts the backend and frontend containers, waits for the Nginx health
check, then opens:

```text
http://localhost
```

Make sure Docker Desktop is installed and running before using the one-click
launcher.

### 1. Local development backend

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

### 2. Local development frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend URL:

```text
http://localhost:5173
```

### 3. Docker deployment

The same Docker Compose stack is used locally and on a cloud server:

```bash
cp deploy/backend.env.example deploy/backend.env
cp deploy/.env.example deploy/.env
cd deploy
docker compose up -d --build
```

By default, the frontend container serves the React build on port `80` and
proxies `/api/*` plus `/health` to the backend container. Local Python/Node
scripts under `scripts/` are kept only as development utilities.

If Docker Hub image pulls time out, set a mirror prefix in `deploy/.env`:

```env
DOCKER_HUB_PREFIX=m.daocloud.io/docker.io/library/
```

### 4. VS Code Task

Open the project in VS Code, press `Ctrl+Shift+B`, and choose:

```text
启动智能家居仿真实验平台
```

## LLM Configuration

In Docker mode, the backend reads configuration from `deploy/backend.env`.
For local development without Docker, it reads `backend/.env`.

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
API_AUTH_TOKEN=
API_RATE_LIMIT_PER_MINUTE=120
```

Modes:

- `LLM_MODE=mock`: deterministic local semantic parsing, suitable for setup and demos.
- `LLM_MODE=real`: calls an OpenAI-compatible HTTP endpoint for semantic parsing.

Keep API keys only in `backend/.env`. Do not commit real credentials.

For Docker deployment, keep API keys only in `deploy/backend.env`.

Validate real LLM connectivity:

```powershell
python scripts\verify_real_llm.py
```

## Useful Scripts

Run the deterministic research-runtime demo:

```powershell
.\backend\.venv\Scripts\python.exe scripts\run_research_demo.py
```

Replay a research JSONL log:

```powershell
.\backend\.venv\Scripts\python.exe scripts\replay_research_log.py data\logs\research_demo.jsonl
```

Run a small batch experiment:

```powershell
python scripts\run_batch_experiments.py --limit 5
```

Run reproduction experiments:

```powershell
python scripts\run_reproduction_experiments.py --limit 3 --real-mode mock
```

For a versioned local-Ollama semantic benchmark against the Docker deployment,
select its environment explicitly; the generated CSV/report records the model
revision and non-secret runtime fingerprint, and an unversioned real run must
not be read as version-specific performance evidence:

```powershell
.\backend\.venv\Scripts\python.exe scripts\run_reproduction_experiments.py `
  --groups real_semantic_planning --limit 3 --real-mode real --env-file deploy\backend.env
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
- `GET /api/rag/sources`: list indexed local RAG sources.
- `POST /api/rag/reindex`: rebuild the local RAG index.
- `POST /api/rag/query`: retrieve local knowledge chunks for a query.
- `POST /api/state/reset`: reset the current simulation session state.
- `GET /api/logs/export`: export CSV logs.

## Production Safety and Continuous Improvement

For every public deployment, set a strong `API_AUTH_TOKEN` in `deploy/backend.env`.
The web app then presents an access-token screen and stores the validated token in
an HTTP-only, strict same-site API cookie; API clients may instead send it in the
`X-API-Key` header. The frontend also sends an `X-Simulation-Session` header so
browser sessions have isolated simulation state.

The repository runs a verification workflow for backend tests, frontend builds,
dependency consistency, and high-severity npm advisories. The bounded discovery,
verification, persistence, and stop rules used for follow-up improvements are in
[`docs/loop_engineering.md`](docs/loop_engineering.md).

Run the same bounded quality loop locally with:

```powershell
.\backend\.venv\Scripts\python.exe scripts\run_quality_loop.py
```

It records test/build evidence and deterministic follow-up recommendations under
`data/results/quality/`; it never edits source or deploys automatically.

## Personalized Multi-Objective Research Mode

The research panel exposes a virtual resident's temperature, illuminance, and
energy preferences plus deterministic sensor/actuator disturbances. The command
pipeline adapts targets to the profile and logs comfort, energy, safety,
stability, and estimated satisfaction as a multi-objective utility.

Run the reproducible ablation set with:

```powershell
.\backend\.venv\Scripts\python.exe scripts\run_personalization_experiments.py
```

For a versioned real local-Ollama semantic run against the Docker deployment,
use its explicit runtime configuration rather than relying on host-shell
variables. Set `REAL_LLM_MODEL_REVISION` to the immutable Ollama model digest
and keep the resulting artifact separate from the default mock baseline:

```powershell
.\backend\.venv\Scripts\python.exe scripts\run_personalization_experiments.py `
  --semantic-mode real --env-file deploy\backend.env
```

## Multi-Agent + RAG Upgrade

The default command path now keeps the original API shape while adding a richer
multi-agent blackboard:

```text
user command
-> context memory
-> KnowledgeAgent local RAG retrieval
-> SemanticAgent intent parsing
-> ComfortAgent state review
-> EnergyAgent waste review
-> PlanningAgent action generation
-> SafetyAgent action guardrails
-> CriticAgent plan review
-> ExecutionAgent virtual device execution
-> FeedbackAgent closed-loop evaluation
```

RAG sources currently include `docs/*.md`, `backend/app/config/*.yaml`, and
`data/tasks/*.json`. The built-in retriever uses deterministic local lexical
vectors so the project runs without a separate vector database. You can later
replace `backend/app/rag/document_store.py` with FAISS, Chroma, or a local
embedding model while keeping the same `query()` interface.

Run a RAG smoke query:

```powershell
python scripts\inspect_rag.py "sleep mode comfort energy safety" --top-k 5
```

Run baseline vs multi-agent RAG ablation:

```powershell
python scripts\run_multi_agent_rag_experiments.py --limit 5
```

Disable the upgraded review path for a batch run:

```powershell
python scripts\run_batch_experiments.py --limit 5 --disable-multi-agent
```

## Notes

This project is intended for software simulation, prototyping, and reproducible experiments. The environment, energy, lighting, humidity, and comfort models are simplified approximations and should not be used as real building design, inspection, or home automation logic.

## Research Runtime

The repository now includes a deterministic, event-driven simulation runtime under `backend/app/runtime`, with modular `world`, `tools`, `memory`, and schema-validated structured agents. See `docs/research_runtime_architecture.md` for the architecture diagram, replay contract, and demo flow.

Research API endpoints:

- `POST /api/research/run`
- `GET /api/research/logs`
- `POST /api/research/replay`
