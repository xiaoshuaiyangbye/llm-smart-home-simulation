# Multi-Agent Workflow Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use task-by-task TDD execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the existing center-orchestrated smart-home controller an explicit, versioned workflow-graph contract and verify every completed command trace against it without changing controller behavior.

**Architecture:** Add a dependency-free, immutable graph specification that declares nodes and directed edges for the current `TaskRunner` flow. The graph validates the ordered blackboard stage trace and publishes its version, topology, and validation result through the existing blackboard snapshot; `TaskRunner` remains the execution facade in this first phase.

**Tech Stack:** Python 3, dataclasses, pytest, existing `MultiAgentBlackboard` and `TaskRunner`.

## Global Constraints

- Preserve the existing `POST /api/agent/command` contract and all experiment baselines.
- Retain center-orchestrated, deterministic control; do not describe this as decentralized negotiation or real-device autonomy.
- Do not add a third-party graph runtime in this phase.
- Do not alter task fixtures, metrics, or research conclusions.
- Do not commit, push, deploy, or modify external systems without user authorization.

---

### Task 1: Versioned graph contract and trace validator

**Files:**
- Create: `backend/app/agents/workflow_graph.py`
- Test: `backend/tests/test_workflow_graph.py`

**Interfaces:**
- Produces: `WorkflowEdge(source: str, target: str, condition: str | None = None)`.
- Produces: `MultiAgentWorkflowGraph(version: str, nodes: tuple[str, ...], edges: tuple[WorkflowEdge, ...])` with `describe() -> dict[str, object]` and `validate_stage_order(stages: list[dict[str, object]]) -> dict[str, object]`.
- Produces: `DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH` for the current normal `TaskRunner` stage order.

- [x] **Step 1: Write the failing test**

```python
from app.agents.workflow_graph import DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH

def test_default_graph_accepts_the_normal_blackboard_stage_order() -> None:
    stages = [{"agent": node} for node in DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.nodes]
    result = DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.validate_stage_order(stages)
    assert result == {"valid": True, "violations": []}
```

- [x] **Step 2: Run test to verify it fails**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_workflow_graph.py -q`

Expected: FAIL because `app.agents.workflow_graph` does not exist.

- [x] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class WorkflowEdge:
    source: str
    target: str
    condition: str | None = None

@dataclass(frozen=True)
class MultiAgentWorkflowGraph:
    version: str
    nodes: tuple[str, ...]
    edges: tuple[WorkflowEdge, ...]

    def validate_stage_order(self, stages: list[dict[str, object]]) -> dict[str, object]:
        observed = [str(stage.get("agent", "")) for stage in stages]
        violations = []
        for source, target in zip(observed, observed[1:]):
            if (source, target) not in {(edge.source, edge.target) for edge in self.edges}:
                violations.append(f"unexpected edge: {source} -> {target}")
        return {"valid": not violations, "violations": violations}
```

Declare every current stage node and transition, including the optional personalization evaluator edge.

- [x] **Step 4: Run focused tests to verify they pass**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_workflow_graph.py -q`

Expected: PASS for valid default trace and a deliberately invalid skipped-stage trace.

### Task 2: Publish graph provenance from the real command path

**Files:**
- Modify: `backend/app/agents/blackboard.py`
- Modify: `backend/app/experiments/task_runner.py`
- Modify: `backend/tests/test_collaboration_agent.py`

**Interfaces:**
- Consumes: `DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.describe()` and `validate_stage_order()`.
- Produces: blackboard snapshot key `workflow_graph` with `version`, `nodes`, `edges`, and `trace_validation`.

- [x] **Step 1: Write the failing integration test**

```python
def test_runner_publishes_a_valid_workflow_graph_trace(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    response = TaskRunner(SmartHomeEnvironment(), ExperimentLogger(tmp_path)).run_agent_command(
        AgentCommandRequest(user_command="turn on the living room light")
    )
    workflow = response.multi_agent_blackboard["workflow_graph"]
    assert workflow["version"] == "multi_agent_workflow_v1"
    assert workflow["trace_validation"] == {"valid": True, "violations": []}
```

- [x] **Step 2: Run test to verify it fails**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_collaboration_agent.py::test_runner_publishes_a_valid_workflow_graph_trace -q`

Expected: FAIL with missing `workflow_graph`.

- [x] **Step 3: Write minimal integration**

```python
blackboard.set_workflow_graph(DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.describe())
# after all stages have been recorded
blackboard.set_workflow_trace_validation(
    DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.validate_stage_order(blackboard.snapshot()["stages"])
)
```

Ensure `snapshot()` deep-copies no mutable graph state into later commands.

- [x] **Step 4: Run focused and affected regression tests**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_workflow_graph.py backend\\tests\\test_collaboration_agent.py backend\\tests\\test_personalization.py -q`

Expected: PASS, including SSE stage output and existing blackboard assertions.

### Task 3: Record the evidence and preserve the research boundary

**Files:**
- Modify: `docs/multi_agent_collaboration.md`
- Modify: `docs/improvement_backlog.md`

**Interfaces:**
- Consumes: validated graph metadata from Task 2.
- Produces: documentation that calls this an explicit center-orchestrated workflow graph, and an evidence-led backlog entry.

- [x] **Step 1: Write the documentation acceptance check**

```python
def test_collaboration_documentation_names_the_graph_contract() -> None:
    text = Path("docs/multi_agent_collaboration.md").read_text(encoding="utf-8")
    assert "multi_agent_workflow_v1" in text
    assert "不是去中心化" in text
```

- [x] **Step 2: Run test to verify it fails**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_workflow_graph.py::test_collaboration_documentation_names_the_graph_contract -q`

Expected: FAIL until the graph contract is documented.

- [x] **Step 3: Write the minimal documentation**

Document nodes, directed/conditional edges, the two bounded loops, and the boundary: graph provenance proves an internal software trace, not model efficacy, real-device safety, or decentralized autonomy. Append the required backlog fields: problem, minimum fix, verification evidence, research implication, research boundary, residual risk.

- [x] **Step 4: Run the final quality loop**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_workflow_graph.py backend\\tests\\test_collaboration_agent.py backend\\tests\\test_personalization.py -q`; `backend\\.venv\\Scripts\\python.exe -m ruff check backend\\app\\agents\\workflow_graph.py backend\\app\\agents\\blackboard.py backend\\app\\experiments\\task_runner.py backend\\tests\\test_workflow_graph.py`; `backend\\.venv\\Scripts\\python.exe scripts\\evaluate_rag.py --min-recall 1.0`

Expected: all checks PASS. If documentation changes lower RAG recall, update only retrieval cues that accurately describe the implementation, then rerun the RAG check.
