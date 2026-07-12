# System Description

This project is a local smart-home simulation platform for testing natural-language control flows and virtual environment feedback.

> Retrieval summary: simulated smart-home devices include lights, air conditioner (AC), curtains, fans, windows, sensors, rooms, weather, comfort, and energy models.

## System Scope

The system simulates rooms, virtual devices, outdoor conditions, comfort metrics, and energy use. It does not connect to real home devices and should not be used as production automation logic.

## Components

- `backend/app/main.py`: FastAPI application and API routes.
- `backend/app/simulation/`: device, lighting, thermal, humidity, weather, energy, and comfort models.
- `backend/app/agents/`: semantic parsing, planning, execution, feedback, and context memory.
- `backend/app/experiments/`: orchestration, logging, batch runs, and evaluation utilities.
- `frontend/src/`: React UI, API client, state types, panels, and 3D scene.
- `deploy/`: Docker Compose, Nginx, and cloud deployment environment templates.
- `scripts/`: startup, validation, and experiment entry points.

## Environment Model

The simulated home contains multiple rooms with:

- lighting level
- temperature
- humidity
- occupancy
- active scenario
- device state

Virtual devices include lights, curtains, air conditioners, fans, windows, and sensors. Outdoor state includes weather, time, illuminance, solar radiation, temperature, and humidity. When online weather data is unavailable, the backend falls back to local generated weather curves.

## Agent Workflow

`TaskRunner` is the central orchestrator. It calls:

1. `SemanticAgent`
2. `PlanningAgent`
3. `ExecutionAgent`
4. `FeedbackAgent`

The feedback stage can trigger correction actions, with at most 3 correction rounds. The LLM path is configurable and mainly used for semantic parsing; downstream planning and control are deterministic rules.

## Data and Metrics

The backend can write CSV logs and JSON/Markdown reports under `data/results/`. These generated files are ignored by Git.

Common metrics include:

- intent recognition result
- room and scope recognition result
- selected devices
- action count
- completion status
- feedback correction count
- response latency
- energy use
- comfort score

## Limitations

The simulation models are intentionally lightweight. They are useful for prototyping and repeatable tests, but they do not replace real building physics, calibrated sensors, safety systems, or production-grade device integrations.
