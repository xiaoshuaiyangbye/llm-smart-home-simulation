# Whole-home EnergyPlus Implementation Plan

> **For agentic workers:** Execute inline in this session, respecting repository authorization and preserving existing changes.

**Goal:** Connect all nine designed spaces to one EnergyPlus simulation with independent room controls and observations.

**Architecture:** Read the existing floor-plan wall/opening coordinates and room/device inventory. Build non-overlapping thermal zones in a single engine model, bind room-specific schedules and variables, and expose room results beside facility energy accounting. Preserve historical single-room artifacts and explicitly label geometry assumptions.

**Tech Stack:** EnergyPlus 26.2, Python runtime API, FastAPI, React/TypeScript.

## Global Constraints

- No commits, deployment, data deletion, external model calls or secret changes.
- Preserve the dirty working tree and historical single-room runs.
- User authorized resolving region problems to approach the actual design; inferred parameters remain explicitly uncalibrated.
- Simulation results are uncalibrated software evidence.

### Task 1: Spatial model and controls

- [x] Read floorPlan.ts rooms, wallRuns and openings; validate nine room IDs against rooms.yaml.
- [x] Build paired interzone surfaces and exterior openings using the confirmed height and partition assumptions.
- [x] Add room-specific actuator bindings; route actions by the actual configured entity IDs.
- [x] Test bedroom actions cannot change living-room controls; unsupported entities remain rejected.

### Task 2: Runtime and accounting

- [x] Run all zones in one EnergyPlus state, with room-level environment and energy series.
- [x] Reconcile facility and room meters against SQLite; exclude warmup and preserve raw callbacks.
- [x] Verify 288 samples per room, matching shared-wall surfaces, distinct room responses, and whole-home electricity equal to the sum of room electricity.

### Task 3: User interface and evidence

- [x] Default new jobs to whole_home; retain explicit single_room support for historical reproduction.
- [x] Display covered spaces, room selection, room outcomes and whole-home energy; distinguish historical runs.
- [x] Run targeted pytest/Ruff, frontend tests/build/bundle, health probes and browser verification.
- [x] Record generated engine evidence in the backlog, roadmap and claim matrix; perform one bounded read-only claim audit.
