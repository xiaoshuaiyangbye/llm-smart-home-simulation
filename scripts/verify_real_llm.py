import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

from app.agents.llm_client import LLMClient
from app.simulation.environment import SmartHomeEnvironment


def main() -> int:
    load_dotenv(BACKEND_ROOT / ".env.local")
    load_dotenv(BACKEND_ROOT / ".env")
    output_dir = PROJECT_ROOT / "data" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    environment = SmartHomeEnvironment()
    state = environment.get_state(refresh_realtime=True)
    client = LLMClient()
    result = client.validate_connection(state)
    result["verified_at"] = datetime.now().isoformat(timespec="seconds")
    result["api_key"] = "***"

    output_path = output_dir / "real_llm_connectivity.json"
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nSaved: {output_path}")
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
