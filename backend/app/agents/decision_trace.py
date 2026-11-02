"""Snapshot actual plan edits and state transitions without inventing reasoning."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def executable_actions(actions: list[dict]) -> list[dict]:
    return [{key: action.get(key, {} if key == 'parameters' else None)
             for key in ('entity_id', 'action', 'parameters')} for action in actions]


class DecisionTrace:
    def __init__(self, semantic_mode: str = 'unknown') -> None:
        self.semantic_mode = semantic_mode
        self.events: list[dict] = []

    def record(self, stage: str, *, before_actions: list[dict] | None = None,
               after_actions: list[dict] | None = None, before_state: Any = None,
               after_state: Any = None, duration_ms: float = 0, details: dict | None = None) -> None:
        before, after = before_actions or [], after_actions or []
        def state_dict(state):
            return state.model_dump(mode='json') if hasattr(state, 'model_dump') else state
        self.events.append(deepcopy({'event_id': f'decision-{len(self.events) + 1}', 'stage': stage,
            'before_actions': before, 'after_actions': after,
            'actions_changed': executable_actions(before) != executable_actions(after),
            'before_state': state_dict(before_state), 'after_state': state_dict(after_state),
            'duration_ms': round(max(0, duration_ms), 4), 'details': details or {}}))

    def snapshot(self) -> dict:
        return deepcopy({'schema_version': 'decision_trace_v1', 'semantic_mode': self.semantic_mode,
                         'evidence_class': 'observed_software_simulation', 'events': self.events,
                         'boundary': 'Observed action/state changes; stage presence alone does not establish benefit.'})
