from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from app.agents.blackboard import MultiAgentBlackboard
from app.agents.collaboration_agent import CollaborationAgent
from app.agents.comfort_agent import ComfortAgent
from app.agents.context_memory import UserContextMemory
from app.agents.critic_agent import CriticAgent
from app.agents.energy_agent import EnergyAgent
from app.agents.execution_agent import ExecutionAgent
from app.agents.feedback_agent import FeedbackAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.llm_client import LLMClient, is_location_update_command
from app.agents.planning_agent import PlanningAgent
from app.agents.safety_agent import SafetyAgent
from app.agents.semantic_agent import SemanticAgent
from app.experiments.logger import ExperimentLogger
from app.rag import RagDocumentStore
from app.research import RobustnessConfig, UserPreferenceService
from app.schemas.action_schema import AgentOutput
from app.schemas.state_schema import SmartHomeState
from app.schemas.task_schema import AgentCommandRequest, AgentCommandResponse, TaskRequest, TaskResponse
from app.simulation.environment import SmartHomeEnvironment

FOLLOW_ME_INTENTS = {
    "basic_ac_control",
    "basic_light_control",
    "lighting_comfort_control",
    "thermal_comfort_control",
    "study_mode",
    "movie_mode",
    "sleep_mode",
    "energy_saving_mode",
}


def _deterministic_llm_metrics() -> dict[str, Any]:
    return {
        "cache_hit": False,
        "prompt_bytes": 0,
        "request_ms": 0.0,
        "stream": False,
    }


class TaskRunner:
    def __init__(
        self,
        environment: SmartHomeEnvironment,
        experiment_logger: ExperimentLogger,
        refresh_realtime: bool = False,
        enable_feedback_correction: bool = True,
        enable_context_memory: bool = True,
        enable_multi_agent_review: bool = True,
        execute_actions: bool = True,
        log_task_results: bool = True,
        rag_store: RagDocumentStore | None = None,
        experiment_safety_fault: dict[str, Any] | None = None,
    ) -> None:
        llm_client = LLMClient()
        self.environment = environment
        self.experiment_logger = experiment_logger
        self.rag_store = rag_store or RagDocumentStore()
        self.semantic_agent = SemanticAgent(llm_client)
        self.knowledge_agent = KnowledgeAgent(self.rag_store)
        self.comfort_agent = ComfortAgent()
        self.collaboration_agent = CollaborationAgent()
        self.energy_agent = EnergyAgent()
        self.planning_agent = PlanningAgent()
        self.safety_agent = SafetyAgent()
        self.critic_agent = CriticAgent()
        self.execution_agent = ExecutionAgent()
        self.feedback_agent = FeedbackAgent()
        self.context_memory = UserContextMemory()
        self.refresh_realtime = refresh_realtime
        self.enable_feedback_correction = enable_feedback_correction
        self.enable_context_memory = enable_context_memory
        self.enable_multi_agent_review = enable_multi_agent_review
        self.execute_actions = execute_actions
        self.log_task_results = log_task_results
        # This hook is intentionally constructor-only: it is a deterministic
        # experiment fixture, not an API surface for normal home control.
        self.experiment_safety_fault = deepcopy(experiment_safety_fault) if experiment_safety_fault else None
        self._last_follow_me_semantic: dict[str, Any] | None = None

    def run_agent_command(
        self,
        request: AgentCommandRequest,
        preference_service: UserPreferenceService | None = None,
        evaluation_preference_service: UserPreferenceService | None = None,
        robustness_config: RobustnessConfig | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentCommandResponse:
        try:
            blackboard = MultiAgentBlackboard(request.user_command, on_stage=event_callback)
            current_state = self.environment.get_state(refresh_realtime=self.refresh_realtime)
            blackboard.add_stage(
                "orchestrator",
                {
                    "event": "state_loaded",
                    "room_count": len(current_state.rooms),
                    "device_count": len(current_state.devices),
                },
            )
            previous_occupied_rooms = []
            if request.current_room_id:
                previous_occupied_rooms = [
                    room.room_id
                    for room in current_state.rooms
                    if room.occupancy and room.room_id != request.current_room_id
                ]
            if request.current_room_id:
                current_state = self.environment.set_current_room(request.current_room_id)

            memory_context = (
                self.context_memory.update(request.user_command, request.current_room_id)
                if self.enable_context_memory
                else {}
            )
            blackboard.add_stage("context_agent", memory_context if self.enable_context_memory else {"enabled": False})
            knowledge_result = (
                self.knowledge_agent.retrieve(request.user_command, current_state, memory_context)
                if self.enable_multi_agent_review
                else {
                    "agent": "knowledge_agent",
                    "rag_context": {"matches": [], "match_count": 0},
                    "used_sources": [],
                    "guidance": [],
                }
            )
            blackboard.add_stage("knowledge_agent", knowledge_result)
            if self.enable_context_memory and isinstance(memory_context, dict):
                memory_context["rag_context"] = knowledge_result.get("rag_context", {})
                memory_context["rag_guidance"] = knowledge_result.get("guidance", [])

            if self.enable_context_memory and memory_context.get("context_update_only"):
                semantic_result = self._build_context_update_semantic(
                    request.user_command,
                    request.current_room_id,
                    current_state,
                    memory_context,
                )
            elif self.enable_context_memory and request.current_room_id and is_location_update_command(request.user_command):
                semantic_result = self._build_location_update_semantic(
                    request.user_command,
                    request.current_room_id,
                    current_state,
                )
            else:
                semantic_result = self.semantic_agent.parse(
                    request.user_command,
                    current_state,
                    memory_context if self.enable_context_memory else None,
                )
            if semantic_result.get("error"):
                raise RuntimeError(str(semantic_result["error"]))
            semantic_result["rag_context"] = knowledge_result.get("rag_context", {})
            semantic_result["rag_guidance"] = knowledge_result.get("guidance", [])
            if preference_service:
                semantic_result = preference_service.personalize_semantic_result(semantic_result)
            decision_state, robustness_observation = UserPreferenceService.observe(
                current_state,
                robustness_config or RobustnessConfig(),
            )
            semantic_result["robustness_observation"] = robustness_observation
            blackboard.add_stage("semantic_agent", self._compact_for_blackboard(semantic_result))
            blackboard.add_stage("robustness_observation", robustness_observation)

            if self.enable_context_memory:
                self._attach_memory_context(semantic_result, memory_context)
            self._attach_room_context(
                semantic_result,
                request.current_room_id,
                previous_occupied_rooms,
            )
            comfort_result = (
                self.comfort_agent.analyze(semantic_result, decision_state)
                if self.enable_multi_agent_review
                else {"agent": "comfort_agent", "enabled": False}
            )
            energy_result = (
                self.energy_agent.analyze(semantic_result, decision_state)
                if self.enable_multi_agent_review
                else {"agent": "energy_agent", "enabled": False}
            )
            blackboard.add_stage("comfort_agent", comfort_result)
            blackboard.add_stage("energy_agent", energy_result)
            plan_result = self.planning_agent.plan(
                semantic_result,
                decision_state,
            )
            if self.experiment_safety_fault:
                plan_result = self._inject_experiment_safety_fault(plan_result)
            blackboard.add_stage("planning_agent", plan_result)
            collaboration_result = (
                self.collaboration_agent.coordinate(plan_result, comfort_result, energy_result)
                if self.enable_multi_agent_review
                else {
                    "agent": "collaboration_agent",
                    "phase": "specialist_proposal_reconciliation",
                    "enabled": False,
                    "plan_result": plan_result,
                }
            )
            plan_result = collaboration_result["plan_result"]
            blackboard.add_stage(
                "collaboration_agent",
                {key: value for key, value in collaboration_result.items() if key != "plan_result"},
            )
            safety_result = (
                self.safety_agent.review(semantic_result, plan_result, knowledge_result)
                if self.enable_multi_agent_review
                else self._assess_without_safety_intervention(semantic_result, plan_result)
            )
            if self.enable_multi_agent_review:
                plan_result["actions"] = safety_result.get("actions", plan_result.get("actions", []))
            retained_actions, simulated_failures = UserPreferenceService.filter_failed_actions(
                plan_result.get("actions", []),
                robustness_config or RobustnessConfig(),
                current_state.current_time_step,
            )
            plan_result["actions"] = retained_actions
            plan_result["robustness_context"] = {
                "observation": robustness_observation,
                "simulated_actuator_failures": simulated_failures,
            }
            critic_result = (
                self.critic_agent.review(
                    semantic_result,
                    plan_result,
                    safety_result,
                    comfort_result,
                    energy_result,
                    knowledge_result,
                )
                if self.enable_multi_agent_review
                else {"agent": "critic_agent", "approved": True, "enabled": False}
            )
            critic_result["review_round"] = 1
            revision_result = (
                self.collaboration_agent.apply_critic_revision(plan_result, critic_result)
                if self.enable_multi_agent_review
                else {
                    "agent": "collaboration_agent",
                    "phase": "critic_revision",
                    "actions_changed": False,
                    "revision_decisions": [],
                    "plan_result": plan_result,
                }
            )
            if revision_result["actions_changed"]:
                first_critic_result = deepcopy(critic_result)
                plan_result = revision_result["plan_result"]
                safety_result = self.safety_agent.review(semantic_result, plan_result, knowledge_result)
                plan_result["actions"] = safety_result.get("actions", plan_result.get("actions", []))
                critic_result = self.critic_agent.review(
                    semantic_result,
                    plan_result,
                    safety_result,
                    comfort_result,
                    energy_result,
                    knowledge_result,
                )
                critic_result["review_round"] = 2
                critic_result["prior_review"] = first_critic_result
            critic_result["revision"] = {key: value for key, value in revision_result.items() if key != "plan_result"}
            plan_result["multi_agent_context"] = {
                "knowledge_result": knowledge_result,
                "comfort_result": comfort_result,
                "energy_result": energy_result,
                "safety_result": safety_result,
                "critic_result": critic_result,
                "collaboration_result": {key: value for key, value in collaboration_result.items() if key != "plan_result"},
            }
            blackboard.add_stage("safety_agent", safety_result)
            blackboard.add_stage("critic_agent", critic_result)
            if self.execute_actions:
                execution_result = self.execution_agent.execute(plan_result, self.environment)
                feedback_result = self.feedback_agent.evaluate(
                    semantic_result,
                    self.environment.get_state(refresh_realtime=False),
                    revision_round=0,
                )
            else:
                execution_result = {
                    "agent": "execution_agent",
                    "executed_at": datetime.now().isoformat(timespec="seconds"),
                    "skipped": True,
                    "executed_count": 0,
                    "results": [],
                    "final_state": current_state.model_dump(),
                }
                feedback_result = {
                    "completed": False,
                    "feedback": "Execution and feedback were skipped for the semantic-planning ablation group.",
                    "metrics": {"execution_skipped": True},
                    "correction_round": 0,
                    "correction_actions": [],
                }

            correction_round = 0
            while (
                self.execute_actions
                and self.enable_feedback_correction
                and not feedback_result["completed"]
                and feedback_result["correction_actions"]
                and correction_round < 3
            ):
                correction_round += 1
                correction_plan = {
                    "plan_id": f"{plan_result['plan_id']}-correction-{correction_round}",
                    "agent": "planning_agent",
                    "intent": semantic_result["intent"],
                    "room": semantic_result["room"],
                    "actions": feedback_result["correction_actions"],
                }
                correction_execution = self.execution_agent.execute(correction_plan, self.environment)
                execution_result.setdefault("correction_results", []).append(correction_execution)
                feedback_result = self.feedback_agent.evaluate(
                    semantic_result,
                    self.environment.get_state(refresh_realtime=False),
                    revision_round=correction_round,
                )
            blackboard.add_stage("execution_agent", self._compact_for_blackboard(execution_result))
            blackboard.add_stage("feedback_agent", feedback_result)

            final_state = self.environment.get_state(refresh_realtime=False)
            objective_evaluator = evaluation_preference_service or preference_service
            if objective_evaluator:
                multi_objective = objective_evaluator.evaluate_multi_objective(
                    final_state,
                    action_count=len(plan_result.get("actions", [])),
                    safety_passed=bool(safety_result.get("passed", True)),
                    safety_issues=(
                        safety_result.get("remaining_issues", [])
                        if isinstance(safety_result.get("remaining_issues", []), list)
                        else []
                    ),
                )
                plan_result["multi_objective_evaluation"] = multi_objective
                feedback_result["multi_objective_evaluation"] = multi_objective
                blackboard.add_stage("personalization_evaluator", multi_objective)
            blackboard.set_metric("final_action_count", len(plan_result.get("actions", [])))
            blackboard.set_metric("feedback_completed", feedback_result.get("completed"))
            blackboard_snapshot = blackboard.snapshot()
            semantic_result["multi_agent_blackboard"] = deepcopy(blackboard_snapshot)
            plan_result["multi_agent_blackboard"] = deepcopy(blackboard_snapshot)
            feedback_result["multi_agent_blackboard_summary"] = {
                "stage_count": len(blackboard_snapshot.get("stages", [])),
                "warnings": blackboard_snapshot.get("warnings", []),
                "metrics": blackboard_snapshot.get("metrics", {}),
            }
            agent_output = AgentOutput(
                semantic_result=semantic_result,
                planning_result=plan_result,
                execution_result=execution_result,
                feedback_result=feedback_result,
                actions=plan_result.get("actions", []),
                multi_agent_blackboard=deepcopy(blackboard_snapshot),
            )
            if self.log_task_results:
                self.experiment_logger.log_task(
                    experiment_id="agent-command",
                    user_command=request.user_command,
                    agent_output=agent_output,
                    state=final_state,
                )
            if self.enable_context_memory:
                self._remember_follow_me_semantic(semantic_result)
            return AgentCommandResponse(
                success=True,
                semantic_result=semantic_result,
                plan_result=plan_result,
                execution_result=execution_result,
                feedback_result=feedback_result,
                final_state=final_state,
                multi_agent_blackboard=deepcopy(blackboard_snapshot),
            )
        except Exception as exc:
            return AgentCommandResponse(
                success=False,
                error=str(exc),
                final_state=self.environment.get_state(refresh_realtime=False),
            )

    def run(self, request: TaskRequest) -> TaskResponse:
        response = self.run_agent_command(AgentCommandRequest(user_command=request.user_command))
        agent_output = AgentOutput(
            semantic_result=response.semantic_result,
            planning_result=response.plan_result,
            execution_result=response.execution_result,
            feedback_result=response.feedback_result,
            actions=response.plan_result.get("actions", []),
            multi_agent_blackboard=response.multi_agent_blackboard,
        )
        return TaskResponse(
            experiment_id=request.experiment_id,
            user_command=request.user_command,
            success=response.success,
            agent_output=agent_output,
            state=response.final_state or self.environment.get_state(refresh_realtime=False),
            error=response.error,
        )

    def validate_llm_connection(self, current_state: SmartHomeState | None = None) -> dict:
        current_state = current_state or self.environment.get_state(refresh_realtime=True)
        return self.semantic_agent.llm_client.validate_connection(current_state)

    def get_context_memory(self) -> dict[str, Any]:
        return self.context_memory.snapshot()

    def reset_context_memory(self) -> dict[str, Any]:
        self._last_follow_me_semantic = None
        return self.context_memory.reset()

    def query_rag(self, query: str, top_k: int = 5) -> dict[str, Any]:
        return self.rag_store.query(query, top_k=top_k)

    def reindex_rag(self) -> dict[str, Any]:
        return self.rag_store.reindex()

    def get_rag_sources(self) -> dict[str, Any]:
        return self.rag_store.sources()

    def _build_context_update_semantic(
        self,
        user_command: str,
        current_room_id: str | None,
        current_state,
        memory_context: dict[str, Any],
    ) -> dict[str, Any]:
        room_id = current_room_id or self._default_room_id(current_state)
        return {
            "intent": "context_update",
            "room": room_id,
            "scope": "single_room",
            "control_goal": "remember_context",
            "task_type": "context_memory",
            "targets": {
                "illuminance_lux_range": [0, 1200],
                "temperature_c_range": [18, 30],
            },
            "devices": [],
            "constraints": {
                "comfort_first": False,
                "energy_saving": False,
                **memory_context.get("planning_constraints", {}),
            },
            "llm_mode": "deterministic",
            "llm_metrics": _deterministic_llm_metrics(),
            "agent": "semantic_agent",
            "user_command": user_command,
            "context_update_only": True,
            "prompt_payload_summary": {
                "user_command": user_command,
                "room_count": len(current_state.rooms),
                "rooms": [
                    {
                        "room_id": room.room_id,
                        "name": room.name,
                        "occupancy": room.occupancy,
                        "activity": room.activity,
                    }
                    for room in current_state.rooms
                ],
                "user_context_memory": memory_context,
            },
        }

    def _build_location_update_semantic(
        self,
        user_command: str,
        current_room_id: str,
        current_state,
    ) -> dict[str, Any]:
        if self._last_follow_me_semantic is not None:
            semantic_result = deepcopy(self._last_follow_me_semantic)
            source_llm_mode = semantic_result.get("llm_mode")
            semantic_result.update(
                {
                    "room": current_room_id,
                    "scope": "single_room",
                    "llm_mode": "deterministic",
                    "llm_metrics": _deterministic_llm_metrics(),
                    "agent": "semantic_agent",
                    "user_command": user_command,
                    "location_update": True,
                    "follow_me_source_intent": self._last_follow_me_semantic.get("intent"),
                    "follow_me_source_llm_mode": source_llm_mode,
                }
            )
            return semantic_result

        return {
            "intent": "occupancy_update",
            "room": current_room_id,
            "scope": "single_room",
            "control_goal": "set_target",
            "task_type": "scene_control",
            "targets": {
                "illuminance_lux_range": [0, 1200],
                "temperature_c_range": [18, 30],
            },
            "devices": [],
            "constraints": {"comfort_first": False, "energy_saving": True},
            "llm_mode": "deterministic",
            "llm_metrics": _deterministic_llm_metrics(),
            "agent": "semantic_agent",
            "user_command": user_command,
            "location_update": True,
            "prompt_payload_summary": {
                "user_command": user_command,
                "room_count": len(current_state.rooms),
                "rooms": [
                    {
                        "room_id": room.room_id,
                        "name": room.name,
                        "occupancy": room.occupancy,
                        "activity": room.activity,
                    }
                    for room in current_state.rooms
                ],
            },
        }

    def _attach_memory_context(
        self,
        semantic_result: dict[str, Any],
        memory_context: dict[str, Any],
    ) -> None:
        semantic_result["memory_context"] = memory_context
        planning_constraints = memory_context.get("planning_constraints", {})
        if not planning_constraints:
            return

        constraints = semantic_result.setdefault("constraints", {})
        constraints.update(planning_constraints)

        if semantic_result.get("intent") in {"basic_ac_control", "thermal_comfort_control"}:
            recommended_range = planning_constraints.get("recommended_temperature_c_range")
            if isinstance(recommended_range, list) and len(recommended_range) == 2:
                targets = semantic_result.setdefault("targets", {})
                targets["temperature_c_range"] = recommended_range

    def _inject_experiment_safety_fault(self, plan_result: dict[str, Any]) -> dict[str, Any]:
        """Inject one named unsafe actuator action immediately before review.

        The personalization ablation uses this only to verify that the safety
        agent can intercept an otherwise valid planner output.  Keeping the
        fixture narrow and recorded prevents it from becoming an untraceable
        alternative control policy.
        """
        fault = self.experiment_safety_fault or {}
        fault_type = str(fault.get("type", ""))
        if fault_type not in {
            "unsafe_window_opening",
            "unsafe_fan_speed",
            "unsafe_ac_overcooling",
        }:
            raise ValueError(f"Unsupported experiment safety fault: {fault.get('type')}")
        entity_id = str(fault.get("entity_id", ""))
        expected_device_type = {
            "unsafe_window_opening": "window",
            "unsafe_fan_speed": "fan",
            "unsafe_ac_overcooling": "ac",
        }[fault_type]
        if not entity_id.startswith(f"{expected_device_type}."):
            raise ValueError(f"{fault_type} requires a {expected_device_type} entity_id")

        if fault_type == "unsafe_window_opening":
            action = "set_opening"
            parameters = {"opening_pct": float(fault.get("opening_pct", 100))}
        elif fault_type == "unsafe_fan_speed":
            action = "set_speed"
            parameters = {"speed_pct": float(fault.get("speed_pct", 100))}
        else:
            action = "set_temperature"
            parameters = {
                "mode": "cool",
                "setpoint_c": float(fault.get("setpoint_c", 16)),
            }

        injected_action = {
            "entity_id": entity_id,
            "action": action,
            "parameters": parameters,
            "reason": f"deterministic experiment fault: {fault_type} before safety review",
        }
        actions = list(plan_result.get("actions", []))
        replaced_existing_action = False
        for index, action in enumerate(actions):
            if action.get("entity_id") == entity_id:
                actions[index] = injected_action
                replaced_existing_action = True
                break
        if not replaced_existing_action:
            actions.append(injected_action)
        return {
            **plan_result,
            "actions": actions,
            "experiment_safety_fault": {
                "id": str(fault.get("id", "unnamed_safety_fault")),
                "type": fault_type,
                "entity_id": entity_id,
                **injected_action["parameters"],
                "replaced_existing_action": replaced_existing_action,
            },
        }

    def _assess_without_safety_intervention(
        self,
        semantic_result: dict[str, Any],
        plan_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Expose baseline safety risk without granting it reviewer intervention."""
        actions = list(plan_result.get("actions", []))
        assessment = self.safety_agent.assess(semantic_result, actions)
        issues = assessment["issues"]
        return {
            "agent": "safety_agent",
            "enabled": False,
            "passed": not any(issue["severity"] == "high" for issue in issues),
            "issues": issues,
            "remaining_issues": issues,
            "unsafe_action_detected": bool(issues),
            "unsafe_action_blocked": False,
            "action_count_before": len(actions),
            "action_count_after": len(actions),
            "actions_changed": False,
            "actions": actions,
        }

    def _attach_room_context(
        self,
        semantic_result: dict[str, Any],
        current_room_id: str | None,
        previous_occupied_rooms: list[str],
    ) -> None:
        if current_room_id:
            semantic_result["current_room_context"] = current_room_id
        semantic_result["previous_occupied_rooms"] = previous_occupied_rooms

    def _remember_follow_me_semantic(self, semantic_result: dict[str, Any]) -> None:
        intent = semantic_result.get("intent")
        if semantic_result.get("scope") != "single_room" or intent not in FOLLOW_ME_INTENTS:
            return
        if intent == "basic_light_control" and semantic_result.get("control_goal") == "turn_off":
            return
        self._last_follow_me_semantic = deepcopy(semantic_result)

    def _default_room_id(self, current_state) -> str:
        for room in current_state.rooms:
            if room.occupancy:
                return room.room_id
        return "living_room"

    def _compact_for_blackboard(self, payload: dict[str, Any]) -> dict[str, Any]:
        compact = dict(payload)
        for key in ["prompt_template", "prompt_payload_summary", "multi_agent_blackboard"]:
            compact.pop(key, None)
        return compact
