# Multi-Agent Collaboration

This document describes the agent workflow used by the smart-home simulation platform.

## Architecture

The current system is a center-orchestrated, role-based multi-agent workflow. It is not a decentralized autonomous negotiation system. The upgraded path records each role output on a shared blackboard so experiments and the frontend can inspect what each agent contributed.

```text
natural-language command
-> context memory
-> local RAG knowledge retrieval
-> semantic parsing
-> comfort analysis
-> energy review
-> task planning
-> safety review
-> critic review
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
| Knowledge agent | `backend/app/agents/knowledge_agent.py` | Retrieves local docs/config/task knowledge through RAG. |
| Comfort agent | `backend/app/agents/comfort_agent.py` | Reviews target room comfort gaps before planning. |
| Energy agent | `backend/app/agents/energy_agent.py` | Identifies active devices and unoccupied-room waste candidates. |
| Planning agent | `backend/app/agents/planning_agent.py` | Builds a device action plan from semantic intent and current state. |
| Safety agent | `backend/app/agents/safety_agent.py` | Applies guardrails such as health-context window blocking and AC/window conflict detection. |
| Critic agent | `backend/app/agents/critic_agent.py` | Reviews the final candidate plan and records findings. |
| Execution agent | `backend/app/agents/execution_agent.py` | Applies virtual device actions to the simulated environment. |
| Feedback agent | `backend/app/agents/feedback_agent.py` | Evaluates whether the target state was reached and proposes corrections. |
| LLM client | `backend/app/agents/llm_client.py` | Provides mock or real semantic parsing through a configurable provider. |
| RAG store | `backend/app/rag/document_store.py` | Indexes local Markdown, YAML, and JSON sources for retrieval. |

## Runtime Flow

1. The frontend or API client sends `POST /api/agent/command`.
2. `TaskRunner` reads the current `SmartHomeState`.
3. The semantic agent parses intent, room, scope, target ranges, and candidate devices.
4. The planning agent generates virtual device actions.
5. The execution agent updates devices and environment state.
6. The feedback agent evaluates lighting, temperature, humidity, comfort, and obvious waste.
7. If feedback is not satisfied, the orchestrator may run correction actions.
8. Safety and critic agents review the plan and annotate or adjust actions.
9. The response includes semantic, planning, execution, feedback, action, final state, RAG, and blackboard data.

The correction loop is capped at 3 rounds to keep runs predictable.

## RAG Sources

The local RAG index currently reads:

- `docs/*.md`
- `backend/app/config/*.yaml`
- `data/tasks/*.json`

API endpoints:

- `GET /api/rag/sources`
- `POST /api/rag/reindex`
- `POST /api/rag/query`

The default retriever uses deterministic lexical cosine scoring for local reproducibility. It can be replaced by FAISS, Chroma, or a local embedding service without changing agent call sites.

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
- `multi_agent_blackboard`
- `planning_result.multi_agent_context`

Frontend rendering is implemented in `frontend/src/components/AgentOutputPanel.tsx`, with TypeScript types in `frontend/src/types/state.ts`. The inspector includes RAG, Agents, and Safety tabs for the upgraded path.

## Extension Points

Possible future roles include:

- energy optimization agent
- safety constraint agent
- policy review agent
- user preference agent
- experiment comparison agent

Before adding a new role, define its input, output, call position, failure behavior, and evaluation metrics.
