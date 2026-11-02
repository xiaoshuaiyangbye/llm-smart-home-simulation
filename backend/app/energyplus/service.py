import hashlib
import json
import os
import subprocess
import sys
import threading
import urllib.request
import uuid

from app.energyplus.calibration import fit_calibration
from app.energyplus.contracts import CalibrationRequest, RunRequest
from app.energyplus.model import ROOT, runtime_directory

RESULTS = ROOT / "data" / "results" / "energyplus" / "workbench"
CALIBRATIONS = ROOT / "data" / "results" / "energyplus" / "calibrations"
MODEL_URL = "http://127.0.0.1:8011"
DOWNLOADS = {"summary.json", "observations.csv", "observations.jsonl", "raw_callback_observations.jsonl",
             "control_trace.jsonl", "provenance.json", "accounting_audit.json", "bindings.json",
             "available_api_data.json", "single_room.epJSON", "whole_home.epJSON", "spatial_bindings.json",
             "engine/eplusout.err", "engine/eplusout.sql", "config.json"}


def owner_key(session):
    return hashlib.sha256(session.encode()).hexdigest()


def model_status():
    try:
        with urllib.request.urlopen(MODEL_URL + "/health", timeout=1) as response:
            return json.load(response)
    except Exception:
        return {"ready": False, "status": "unavailable", "model": "DeepSeek-R1-Distill-Qwen-7B adapter"}


class JobService:
    def __init__(self, root=RESULTS):
        self.root = root
        self.lock = threading.Lock()
        self.processes = {}

    def status(self):
        from app.energyplus.spatial import area, inventory
        layout, rooms = inventory()
        try:
            runtime = runtime_directory()
            installed = True
        except (ValueError, FileNotFoundError):
            runtime, installed = None, False
        return {"available": installed, "engine": "EnergyPlus", "version": "26.2.0",
                "runtime": str(runtime) if runtime else None, "deepseek": model_status(),
                "zone": "designed whole home", "spatial_scope": "whole_home", "room_count": len(rooms),
                "rooms": [{"room_id": r["room_id"], "name": r["name"], "area_m2": area(r["polygon"]),
                           "polygon": r["polygon"]} for r in rooms],
                "height_m": layout["height_m"], "geometry_assumptions": layout["assumptions"],
                "weather": "Golden NREL TMY3 example",
                "calibration_status": "uncalibrated_until_user_measurements_provided",
                "boundary": "physical software simulation; not a measured residence",
                "controllers": ["rule", "manual", "harness_real"]}

    def directory(self, run_id, owner):
        if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise KeyError("Unknown run")
        directory = self.root / run_id
        config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        if config["owner"] != owner_key(owner):
            raise KeyError("Unknown run")
        return directory

    def create(self, request: RunRequest, owner):
        from app.energyplus.spatial import inventory
        if request.current_room_id not in inventory()[0]["polygons"]:
            raise ValueError("Current room is not in the designed home")
        runtime_directory()
        if request.controller == "harness_real" and not model_status().get("ready"):
            raise RuntimeError("DeepSeek planner is not ready; training/evaluation may still be running")
        calibration = None
        if request.calibration_id:
            path = CALIBRATIONS / f"{request.calibration_id}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["owner"] != owner_key(owner):
                raise KeyError("Unknown calibration")
            calibration = data["fit"]
        with self.lock:
            active = [p for p in self.processes.values() if p.poll() is None]
            if len(active) >= 2:
                raise RuntimeError("Two EnergyPlus experiments are already active; wait or cancel one")
            run_id = uuid.uuid4().hex
            directory = self.root / run_id
            directory.mkdir(parents=True)
            config = {"request": request.model_dump(), "owner": owner_key(owner), "calibration": calibration}
            (directory / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            (directory / "status.json").write_text(json.dumps({"status": "queued", "samples": 0}), encoding="utf-8")
            with (directory / "worker.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen([sys.executable, "-u", "-m", "app.energyplus.runner", "--config", str(directory / "config.json")],
                    cwd=ROOT / "backend", stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.processes[run_id] = process
        return {"run_id": run_id, "status": "queued", "request": request.model_dump()}

    def get(self, run_id, owner):
        directory = self.directory(run_id, owner)
        data = json.loads((directory / "status.json").read_text(encoding="utf-8"))
        process = self.processes.get(run_id)
        if data["status"] in {"queued", "running"} and process and process.poll() is not None:
            data = json.loads((directory / "status.json").read_text(encoding="utf-8"))
            if data["status"] in {"queued", "running"}:
                data = {"status": "failed", "error": f"Worker exited with code {process.returncode}; inspect worker.log"}
        return {"run_id": run_id, **data}

    def list(self, owner):
        if not self.root.exists():
            return []
        rows = []
        for directory in sorted(self.root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                item = self.get(directory.name, owner)
                item.pop("summary", None)
                rows.append(item)
            except (KeyError, OSError, ValueError):
                continue
            if len(rows) == 30:
                break
        return rows

    def observations(self, run_id, owner):
        path = self.directory(run_id, owner) / "observations.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def cancel(self, run_id, owner):
        directory = self.directory(run_id, owner)
        if self.get(run_id, owner)["status"] in {"queued", "running"}:
            (directory / "cancel.request").write_text("user requested cancellation", encoding="utf-8")
        return self.get(run_id, owner)

    def calibrate(self, request: CalibrationRequest, owner):
        fit = fit_calibration(request)
        key = uuid.uuid4().hex
        CALIBRATIONS.mkdir(parents=True, exist_ok=True)
        data = {"calibration_id": key, "owner": owner_key(owner), "request": request.model_dump(), "fit": fit}
        (CALIBRATIONS / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"calibration_id": key, "fit": fit}


service = JobService()
