# Multi-Agent Collaboration

This document describes the agent workflow used by the smart-home simulation platform.

## Architecture

The current system is a center-orchestrated, role-based multi-agent workflow. It is not a decentralized autonomous negotiation system.

```text
natural-language command
-> semantic parsing
-> task planning
-> action execution
-> environment update
-> feedback evaluation
-> optional correction
```

## Roles

| Role | Main module | Responsibility |
| --- | --- | --- |
| Orchestrator | `backend/app/experiments/task_runner.py` | Calls each stage and returns the final response. |
| Semantic agent | `backend/app/agents/semantic_agent.py` | Converts a user command into structured semantic JSON. |
| Planning agent | `backend/app/agents/planning_agent.py` | Builds a device action plan from semantic intent and current state. |
| Execution agent | `backend/app/agents/execution_agent.py` | Applies virtual device actions to the simulated environment. |
| Feedback agent | `backend/app/agents/feedback_agent.py` | Evaluates whether the target state was reached and proposes corrections. |
| LLM client | `backend/app/agents/llm_client.py` | Provides mock or real semantic parsing through a configurable provider. |

## Runtime Flow

1. The frontend or API client sends `POST /api/agent/command`.
2. `TaskRunner` reads the current `SmartHomeState`.
3. The semantic agent parses intent, room, scope, target ranges, and candidate devices.
4. The planning agent generates virtual device actions.
5. The execution agent updates devices and environment state.
6. The feedback agent evaluates lighting, temperature, humidity, comfort, and obvious waste.
7. If feedback is not satisfied, the orchestrator may run correction actions.
8. The response includes semantic, planning, execution, feedback, action, and final state data.

The correction loop is capped at 3 rounds to keep runs predictable.

## Implementation Boundary

The real LLM path is currently used mainly for semantic parsing. Planning, execution, feedback, and correction are implemented with deterministic, explainable program logic. This keeps local testing reproducible and makes experiment results easier to inspect.

## Response Shape

The API returns a structured `agent_output` object with:

- `semantic_result`
- `planning_result`
- `execution_result`
- `feedback_result`
- `actions`
- `final_state`

Frontend rendering is implemented in `frontend/src/components/AgentOutputPanel.tsx`, with TypeScript types in `frontend/src/types/state.ts`.

## Extension Points

Possible future roles include:

- energy optimization agent
- safety constraint agent
- policy review agent
- user preference agent
- experiment comparison agent

Before adding a new role, define its input, output, call position, failure behavior, and evaluation metrics.
