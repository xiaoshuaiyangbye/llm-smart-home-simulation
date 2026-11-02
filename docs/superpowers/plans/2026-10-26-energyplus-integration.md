# EnergyPlus Integration Implementation Plan

**Goal:** Deploy an optional local EnergyPlus single-zone research backend with Python control, auditable Harness actions, frontend experiments, calibration input and paired simulation runs.

**Architecture:** Keep the existing lightweight simulator unchanged. A separate EnergyPlus runner uses the official Runtime/Data Transfer API in a worker process, writes timestamped observations/actions and immutable input hashes, and is managed by an authenticated FastAPI router. A lazy frontend workbench starts and inspects experiments. The model-training project remains independent; model availability is explicit.

**Tech Stack:** EnergyPlus26.2.0 Windows x86_64 official release, Python ctypes API, existing FastAPI/Pydantic and React/TypeScript/Vite.

## Global Constraints

- User authorized full local deployment and experiment integration on2026-10-26. No physical devices or public hosting.
- Preserve all pre-existing uncommitted source and existing experiment meaning. No commits/pushes.
- Example building/weather and default electric-lighting response are uncalibrated. Record their provenance separately from user measurements.
- Keep simulated time, wall-clock model latency, warmup and control intervals distinct; compare equal horizons, weather and occupancy.
- Invalid actuator handles or unavailable actual models must fail explicitly, never masquerade as successful real control.
- Thermal loads, modeled electrical consumption and measured power are separate metrics. No field-savings claim.

## Delivery steps

- [x] Install the fixed official runtime under `.runtime/energyplus/`, verify release SHA where provided and persist install manifest. Run `energyplus --version`.
- [x] Create `backend/app/energyplus/` with explicit input/output contracts, model builder, runner, job service and router. Use copied official single-zone input and weather as source references, not private building claims.
- [x] Expose real zone temperature, humidity, CO2 and daylight reference outputs; record electric-light contribution as an explicitly modeled or calibrated quantity. Bind light/HVAC/ventilation actuators by enumerating actual available handles.
- [x] Validate schema, parameter ranges, time-ordering, callback state readiness/warmup, energy units and independent-run isolation with targeted tests. Run real EnergyPlus runs and inspect `.err`, actuator list, SQLite and complete logs.
- [x] Add rule, manual schedule and Harness controllers with traceable command-to-action mapping. Connect the local real-model endpoint, record model revision/adapter hash and reject an invalid unavailable planner.
- [x] Add a lazy `EnergyPlusPanel` with job state, controls, time-series, provenance/calibration labels and downloads. Keep styles component-scoped.
- [x] Provide a calibration-data JSON contract and fit/holdout diagnostics. No original measured dataset was found in the repository; defaults stay labeled uncalibrated.
- [x] Add matched-run experiments with common weather/occupancy/horizon, comfort violations, separately typed energy quantities, raw predictions and model/controller timing. Run a 48-call real DeepSeek one-day EnergyPlus Harness example.
- [x] Deploy native loopback backend/frontend and model endpoint. Verify health/API paths, targeted backend checks, production build, bundle budget, in-app browser, RAG and claim gates.
- [x] Audit resulting claims; synchronize roadmap, backlog and claim matrix. Keep RQ5 blocked for external semantic review and do not claim real-home energy savings.

## Acceptance checks

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_energyplus*.py -q
backend/.venv/Scripts/python.exe -m ruff check backend/app/energyplus scripts/run_energyplus_experiment.py
backend/.venv/Scripts/python.exe scripts/run_energyplus_experiment.py --help
```

From frontend run targeted Vitest and production build, then the existing bundle gate. A mock-only test does not pass the real-engine gate; no actual-model or hardware gate is marked complete from software tests.
