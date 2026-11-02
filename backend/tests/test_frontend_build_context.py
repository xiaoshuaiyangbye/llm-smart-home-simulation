"""Cross-directory frontend JSON imports must exist in the Docker build stage."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_relative_json_inputs_are_copied_into_docker_build():
    dockerfile = (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
    copied = []
    for line in dockerfile.splitlines():
        words = line.split()
        if words and words[0] == "COPY" and not words[1].startswith("--"):
            copied.extend(ROOT.glob(words[1]))
    found = 0
    for source in (ROOT / "frontend/src").rglob("*.ts*"):
        for target in re.findall(r'from\s+["\'](\.[^"\']+\.json)["\']', source.read_text(encoding="utf-8")):
            resolved = (source.parent / target).resolve()
            assert resolved.is_file(), f"Missing frontend data input: {resolved}"
            assert any(resolved == item.resolve() or item.is_dir() and resolved.is_relative_to(item.resolve())
                       for item in copied), f"Docker COPY omits frontend data input: {resolved}"
            found += 1
    assert found > 0, "Expected shared geometry import to be checked"
