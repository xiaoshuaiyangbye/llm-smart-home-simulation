# Reliable Control Four-Stage Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current session, using a failing regression, minimal implementation, and verification checkpoint for each stage. Preserve the existing dirty worktree. The user requested stages 1–4 in order; do not stop for another execution-choice confirmation.

**Goal:** Connect complete simulation episodes, applicable semantic metrics, attributable agent interventions, and inspectable decision replay.

**Architecture:** Run matched methods through the existing TaskRunner and save independently checked outcomes with provenance. Add explicit parameter applicability without rewriting historical labels, capture action changes at their actual stages, and expose saved evidence alongside live decision traces.

**Tech Stack:** Existing Python/FastAPI/Pydantic, pytest/Ruff, React/TypeScript/Vite/Vitest, local Edge or in-app browser. No new runtime dependencies.

## Global Constraints

- User authorization: “请把1-4按顺序完善” on 2026-09-07; implement the four recommendations sequentially.
- Preserve all pre-existing modifications; no commit, push, external deployment, secret changes, or user-data deletion.
- Software simulation, mock semantics, real model calls, and physical-device evidence remain separate.
- Historical results and reference labels remain available; new evaluation semantics carry a new version and denominator.
- Independent human review remains external and may not be fabricated.
- Backend commands use `backend\.venv\Scripts\python.exe`; frontend commands run from `frontend/`.

## Stage 1: Matched end-to-end episodes

**Files:** Create `backend/app/experiments/episode_benchmark.py`, `scripts/run_e1_episode_benchmark.py`, `backend/tests/test_e1_episode_benchmark.py`, and a versioned fixture under `data/research/`. Update the E1 specification/validator and roadmap only with verified status.

**Interfaces:** `build_episodes(matrix: str) -> list[dict]`; `run_episode(episode: dict, method: str, repeat_seed: int, ...) -> dict`; `summarize_episodes(records: list[dict]) -> dict`.

- [x] Add a regression proving shared initial-state fingerprints and distinct execution records for all four methods, plus final-state failure even when the runtime reports success.

```python
assert len({row['initial_state_fingerprint'] for row in records}) == 1
assert {row['method'] for row in records} == {'single_agent', 'multi_agent_static', 'personalized', 'full'}
assert failed['runtime_success'] is True
assert failed['final_state_success'] is False
```

- [x] Run `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_e1_episode_benchmark.py` and verify the expected missing implementation failure.
- [x] Implement fresh environments, shared evaluation profiles, fixed observation horizons, independent state predicates, explicit semantic provenance, fixture/source fingerprints, and task-cluster comparisons. Emit full traces separately from compact records.
- [x] Run the targeted tests and the small matrix before the larger matrix. Report base-scenario and configuration counts separately; no significance claim from repeated templates.
- [x] Record the actual artifact directory and remaining scope in the evidence ledger.

## Stage 2: Applicable semantic targets and explicit constraints

**Files:** Create `backend/app/experiments/semantic_targets.py` and `backend/tests/test_semantic_targets.py`; extend `scripts/run_reproduction_experiments.py`, semantic normalization tests, and the narrow responsible parser code. Add a diagnostic script/fixture for historical re-scoring without replacing historical artifacts.

**Interfaces:** `evaluate_applicable_targets(command: str, expected_targets: dict, predicted_targets: dict) -> dict` returns applicable/excluded fields, denominator, matches, and a versioned boundary.

- [x] Add regressions for curtains with irrelevant temperature defaults, explicit temperature/ranges, absent predictions, negation, and malformed parameters.

```python
assert evaluate_applicable_targets('把书房窗帘打开一些', {'temperature_c_range': [20, 30]}, {'temperature_c_range': [18, 29]})['applicable'] is False
assert evaluate_applicable_targets('把空调设为26度', {'temperature_c_range': [26, 26]}, {'temperature_c_range': [24, 24]})['exact_match'] is False
```

- [x] Run the new tests red; implement additive applicability metrics with explicit N/A and unreviewed-label status.
- [x] Reproduce a concrete explicit-parameter defect before changing normalization; keep regression fixtures separate from frozen evaluation data.
- [x] Run semantic/reproduction regressions and generate a fresh diagnostic report. Retain the independent-review blocker.

## Stage 3: Agent intervention evidence

**Files:** Create `backend/app/agents/decision_trace.py` and `backend/tests/test_decision_trace.py`; minimally extend `backend/app/experiments/task_runner.py` and the episode summary.

**Interfaces:** A `decision_trace_v1` payload records stage, before/after actions, state changes, observed duration, and actual execution/feedback outcome. Agent stages with no action changes must remain distinguishable from interventions.

- [x] Add regressions for a real safety change, critic revision, unchanged ordinary task, and feedback correction.

```python
assert safety_event['actions_changed'] is True
assert ordinary_event['actions_changed'] is False
assert safety_event['before_actions'] != safety_event['after_actions']
```

- [x] Run tests red; capture actual stage inputs/outputs and measured durations, including correction iterations.
- [x] Verify matched end-to-end effects and report non-discriminative cases explicitly. Do not equate role presence with benefit.
- [x] Run affected collaboration, workflow, feedback, and benchmark regressions; record evidence.

## Stage 4: Decision comparison and saved replay

**Files:** Create `frontend/src/components/DecisionTracePanel.tsx` and its tests; extend `AgentOutputPanel.tsx`, state types, and scoped CSS. Add `scripts/build_decision_demos.py` with tests and generated public demo records.

**Interfaces:** The panel consumes `decision_trace_v1` for live results and versioned saved demo records. Saved replay changes the inspected record only; it must never execute device actions.

- [x] Add UI regressions for before/after actions, replay selection, empty/malformed data, and the saved-simulation label.
- [x] Implement readable state/action differences, stage selection, and three source-backed scenarios: stale snapshot, confirmed feedback, conflicting knowledge.
- [x] Generate demos from actual isolated simulator/service calls and save source provenance plus replay checks.
- [x] Run targeted Vitest, frontend build, backend replay tests, and browser checks. Check both documented health endpoints and the actual local development endpoints when applicable.
- [x] Run applicable research validators/RAG gate, update the roadmap and evidence ledger, and provide the final four-stage status with any genuine external blockers.

## Plan self-review

All four requested stages have implementation and validation tasks. New metrics are additive, live and saved records share an explicit version, and experiment counts preserve their inference boundary. Each stage is verified before moving to the next.

## Completion checkpoint — 2026-09-09

All four stages completed within the authorized software scope. See `docs/four_stage_completion_20260909.md`: final E1 7200 records, role removal 300 records, preserved historical semantic audit, 3 replay-checked demos, 232 backend tests, 12 frontend tests, build/Ruff/governance/RAG gates and live in-app browser evidence. Final-state success is only the declared developer state contract; simulator accounting and independent-human/field limitations remain explicit.
