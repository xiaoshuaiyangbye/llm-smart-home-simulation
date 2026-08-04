from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass


@dataclass(frozen=True)
class SnapshotCommitEvaluation:
    """Decision produced immediately before an autonomous action commit."""

    allowed: bool
    status: str
    state_changed: bool
    preference_changed: bool
    duplicate_commit: bool


def evaluate_snapshot_commit(
    *,
    snapshot_revision: int,
    current_revision: int,
    snapshot_preference_fingerprint: str,
    current_preference_fingerprint: str,
    commit_id: str,
    committed_action_ids: Collection[str],
    enforce_snapshot_freshness: bool = True,
) -> SnapshotCommitEvaluation:
    """Evaluate a commit while keeping duplicate suppression in every policy.

    Production uses the default guarded policy.  The explicit unguarded switch
    exists for an isolated ablation only: it removes the revision/fingerprint
    check while retaining the same action, duplicate policy, and execution
    path.
    """

    state_changed = current_revision != snapshot_revision
    preference_changed = current_preference_fingerprint != snapshot_preference_fingerprint
    duplicate_commit = commit_id in committed_action_ids

    if duplicate_commit:
        return SnapshotCommitEvaluation(
            allowed=False,
            status="duplicate_commit_suppressed",
            state_changed=state_changed,
            preference_changed=preference_changed,
            duplicate_commit=True,
        )
    if enforce_snapshot_freshness and (state_changed or preference_changed):
        return SnapshotCommitEvaluation(
            allowed=False,
            status="stale_snapshot_replan_required",
            state_changed=state_changed,
            preference_changed=preference_changed,
            duplicate_commit=False,
        )
    return SnapshotCommitEvaluation(
        allowed=True,
        status="commit_candidate",
        state_changed=state_changed,
        preference_changed=preference_changed,
        duplicate_commit=False,
    )
