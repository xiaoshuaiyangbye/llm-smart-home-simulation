import csv
from datetime import datetime
from pathlib import Path

from app.schemas.action_schema import AgentOutput, DeviceActionRequest
from app.schemas.state_schema import SmartHomeState


class ExperimentLogger:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "experiment_log.csv"

    def ensure_log_file(self) -> Path:
        if not self.log_file.exists():
            with self.log_file.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=self._fieldnames())
                writer.writeheader()
        return self.log_file

    def log_task(
        self,
        experiment_id: str,
        user_command: str,
        agent_output: AgentOutput,
        state: SmartHomeState,
    ) -> None:
        self.ensure_log_file()
        living_room = next(room for room in state.rooms if room.room_id == "living_room")
        with self.log_file.open("a", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self._fieldnames())
            writer.writerow(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "experiment_id": experiment_id,
                    "user_command": user_command,
                    "time_step": state.current_time_step,
                    "action_count": len(agent_output.actions),
                    "living_room_illuminance_lux": living_room.indoor_illuminance_lux,
                    "living_room_temperature_celsius": living_room.indoor_temperature_c,
                    "living_room_humidity_percent": living_room.indoor_humidity_percent,
                    "current_power_w": state.energy_metrics.current_power_w,
                    "cumulative_energy_kwh": state.energy_metrics.cumulative_energy_kwh,
                    "average_comfort_score": state.comfort_metrics.average_overall_score,
                    "feedback_status": agent_output.feedback_result.get(
                        "status",
                        agent_output.feedback_result.get("completed", ""),
                    ),
                }
            )

    def log_simulation_step(self, state: SmartHomeState, minutes: int) -> None:
        self.ensure_log_file()
        living_room = next(room for room in state.rooms if room.room_id == "living_room")
        with self.log_file.open("a", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self._fieldnames())
            writer.writerow(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "experiment_id": "simulation-step",
                    "user_command": f"advance_simulation_{minutes}_minutes",
                    "time_step": state.current_time_step,
                    "action_count": 0,
                    "living_room_illuminance_lux": living_room.indoor_illuminance_lux,
                    "living_room_temperature_celsius": living_room.indoor_temperature_c,
                    "living_room_humidity_percent": living_room.indoor_humidity_percent,
                    "current_power_w": state.energy_metrics.current_power_w,
                    "cumulative_energy_kwh": state.energy_metrics.cumulative_energy_kwh,
                    "average_comfort_score": state.comfort_metrics.average_overall_score,
                    "feedback_status": "simulated",
                }
            )

    def log_device_action(
        self,
        action: DeviceActionRequest,
        success: bool,
        message: str,
        state: SmartHomeState,
    ) -> None:
        self.ensure_log_file()
        living_room = next(room for room in state.rooms if room.room_id == "living_room")
        with self.log_file.open("a", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self._fieldnames())
            writer.writerow(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "experiment_id": "device-action",
                    "user_command": f"{action.entity_id}:{action.action}",
                    "time_step": state.current_time_step,
                    "action_count": 1 if success else 0,
                    "living_room_illuminance_lux": living_room.indoor_illuminance_lux,
                    "living_room_temperature_celsius": living_room.indoor_temperature_c,
                    "living_room_humidity_percent": living_room.indoor_humidity_percent,
                    "current_power_w": state.energy_metrics.current_power_w,
                    "cumulative_energy_kwh": state.energy_metrics.cumulative_energy_kwh,
                    "average_comfort_score": state.comfort_metrics.average_overall_score,
                    "feedback_status": message if success else f"failed: {message}",
                }
            )

    def list_log_files(self) -> list[str]:
        return sorted(path.name for path in self.log_dir.glob("*.csv"))

    def _fieldnames(self) -> list[str]:
        return [
            "timestamp",
            "experiment_id",
            "user_command",
            "time_step",
            "action_count",
            "living_room_illuminance_lux",
            "living_room_temperature_celsius",
            "living_room_humidity_percent",
            "current_power_w",
            "cumulative_energy_kwh",
            "average_comfort_score",
            "feedback_status",
        ]
