import copy
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "validate_thesis_claims.py"
MATRIX = PROJECT_ROOT / "data" / "research" / "thesis_claims.json"
spec = importlib.util.spec_from_file_location("thesis_claims", SCRIPT)
assert spec and spec.loader
thesis_claims = importlib.util.module_from_spec(spec)
spec.loader.exec_module(thesis_claims)


def _write_matrix(tmp_path: Path, matrix: dict) -> Path:
    path = tmp_path / "thesis_claims.json"
    path.write_text(json.dumps(matrix, ensure_ascii=False), encoding="utf-8")
    return path


def test_current_thesis_chain_is_structurally_valid_but_fail_closed_for_submission() -> None:
    result = thesis_claims.validate_thesis_claims(MATRIX)

    assert result["structurally_valid"] is True
    assert result["submission_ready"] is False
    assert result["research_question_count"] == 6
    assert result["innovation_candidate_count"] == 4
    assert result["blocking_rq_ids"] == ["RQ5"]


def test_duplicate_rq_and_real_home_overclaim_are_rejected(tmp_path: Path) -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    invalid = copy.deepcopy(matrix)
    invalid["research_questions"][1]["id"] = "RQ1"
    invalid["research_questions"][0]["supported_claim"] = "该机制已经保证真实家庭安全。"

    result = thesis_claims.validate_thesis_claims(_write_matrix(tmp_path, invalid))

    assert result["structurally_valid"] is False
    assert any("duplicate research question ids" in issue for issue in result["issues"])
    assert any("real-home evidence boundary" in issue for issue in result["issues"])


def test_missing_repository_evidence_is_rejected(tmp_path: Path) -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    invalid = copy.deepcopy(matrix)
    invalid["research_questions"][0]["repository_evidence"] = ["missing/evidence.py"]

    result = thesis_claims.validate_thesis_claims(_write_matrix(tmp_path, invalid))

    assert result["structurally_valid"] is False
    assert any("repository evidence missing" in issue for issue in result["issues"])
