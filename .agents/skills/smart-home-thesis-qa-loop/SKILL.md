---
name: smart-home-thesis-qa-loop
description: Evidence-first, bounded quality and research-rigor workflow for this smart-home simulation repository. Use whenever the user asks to audit, diagnose, improve, validate, reproduce, compare, document, or make thesis claims about simulation behavior, multi-agent orchestration, RAG, personalization, autonomy, experiments, ablations, localhost UI, or real-versus-mock evidence. Use it even when the request does not explicitly say “QA”, whenever methodological validity or reproducibility could be affected.
---

# Smart-home thesis QA loop

Use this workflow to turn a request into one defensible, bounded engineering or research-quality result. The objective is not continuous autonomous modification: it is a reproducible evidence loop that stops when no confirmed issue remains.

## Scope and boundaries

- Read the root `AGENTS.md` first. It defines the persistent repository rules.
- Preserve the dirty worktree. Never overwrite unrelated changes.
- Do not commit, push, deploy, merge, delete data, alter secrets, or use external write actions without explicit user authorization.
- Treat software simulation, mock semantics, real-model calls, and field/device validation as distinct evidence classes.
- Keep Chinese explanations while preserving required English commands, APIs, paths, measurement identifiers, and RAG keywords.

## Classify before acting

Choose one route and state it briefly in progress reporting.

1. **Read-only diagnosis** — inspect code, logs, artifacts, and tests. Do not write when evidence does not establish a defect.
2. **Single-issue repair** — make the smallest change that closes one independently verifiable correctness, reproducibility, metric-validity, or claim-boundary gap.
3. **Research-design decision** — stop and ask for direction when the next step changes task fixtures, controls, metrics, hypotheses, or interpretation policy without a clearly implied choice.
4. **Ordinary product change** — follow the request, but retain the applicable validation and simulation-boundary checks.

## Evidence-first workflow

### 1. Preflight

1. Run `git status --short`.
2. Search `docs/improvement_backlog.md` for the task family and open only the relevant prior entries.
3. Identify the source of truth: task suite, schema, runner, API contract, generated artifact, or UI flow.
4. Define one acceptance criterion before editing. Name the evidence that could disprove the proposed change.

### 2. Diagnose

- Prefer targeted `rg` searches, focused file reads, tests, structured logs, and existing result artifacts over broad scans.
- For live-stack evidence, start with `http://localhost/health` and `http://localhost/api/agent/health`.
- For reproduction tasks, verify command and pre-context input contracts before interpreting outcome metrics.
- For experiment results, verify effective semantic mode, task-suite/runner provenance, applicability of each metric, and whether artifacts are fresh for the current protocol.

If the evidence does not establish a defect, report the checks and stop. Do not create speculative hardening or feature work.

### 3. Repair one issue

- Change the narrowest responsible layer.
- Add or update a regression test when the defect is deterministic and testable.
- Preserve existing interfaces, baselines, fixture meaning, and comparison conditions unless the user explicitly authorizes a research-design change.
- Do not claim a critic, review stage, or multi-agent role helped unless the artifact records an intervention that changed the relevant trajectory.

### 4. Validate proportionately

Select only the gates that cover the changed behavior.

| Change surface | Minimum validation |
| --- | --- |
| Backend Python | targeted pytest using `backend\.venv\Scripts\python.exe`; targeted Ruff when applicable |
| Frontend TypeScript/UI | targeted Vitest; `npm run build` from `frontend/`; browser evidence for user-visible behavior |
| Initial UI bundle or lazy loading | `npm run test:bundle` from `frontend/` |
| Broad documentation/RAG corpus | `scripts/evaluate_rag.py --min-recall 1.0` |
| Live agent/runtime behavior | `/health`, `/api/agent/health`, relevant API path, and Edge or in-app-browser evidence when the UI is in scope |
| Experiment protocol/artifacts | deterministic runner/test coverage plus artifact provenance, metric applicability, and claim-boundary checks |

Do not present an unrun check as passed. Distinguish a local smoke run from real-model, device, or field evidence.

### 5. Reflect and record

For thesis-facing or result-bearing work, use the `research_claim_critic` custom agent only after evidence exists and only for a bounded read-only audit. Do not fan out by default.

When a repair is validated, append a concise entry to `docs/improvement_backlog.md` with this structure:

```text
Problem:
Minimum fix:
Verification evidence:
Research implication:
Research boundary:
Residual risk:
```

When no repair is justified, report the negative result and the stopping reason instead of adding a backlog entry that implies a change.

## Delivery format

Lead with the outcome, then include:

1. changed files or explicitly state that no files changed;
2. evidence actually run and its result;
3. research implication and evidence boundary when relevant;
4. residual risk or the next decision that needs user authority.
