from statistics import mean

from app.schemas.state_schema import SmartHomeState


def summarize_basic_metrics(state: SmartHomeState) -> dict[str, float]:
    rooms = state.rooms
    average_illuminance = sum(room.indoor_illuminance_lux for room in rooms) / len(rooms)
    average_temperature = sum(room.indoor_temperature_c for room in rooms) / len(rooms)
    average_humidity = sum(room.indoor_humidity_percent for room in rooms) / len(rooms)
    return {
        "average_illuminance_lux": round(average_illuminance, 2),
        "average_temperature_celsius": round(average_temperature, 2),
        "average_humidity_percent": round(average_humidity, 2),
        "current_power_w": round(state.energy_metrics.current_power_w, 2),
        "cumulative_energy_kwh": round(state.energy_metrics.cumulative_energy_kwh, 5),
        "average_comfort_score": round(state.comfort_metrics.average_overall_score, 2),
        "comfortable_room_count": float(state.comfort_metrics.comfortable_room_count),
    }


def summarize_batch_records(records: list[dict]) -> dict[str, float]:
    if not records:
        return {}

    def rate(field: str) -> float:
        return round(sum(1 for item in records if item.get(field)) / len(records) * 100, 2)

    response_times = [float(item["response_time_ms"]) for item in records if item.get("response_time_ms") is not None]
    action_counts = [float(item["action_count"]) for item in records if item.get("action_count") is not None]
    comfort_scores = [float(item["average_comfort_score"]) for item in records if item.get("average_comfort_score") is not None]
    power_values = [float(item["current_power_w"]) for item in records if item.get("current_power_w") is not None]

    return {
        "sample_count": float(len(records)),
        "success_rate_percent": rate("success"),
        "task_completion_rate_percent": rate("completed"),
        "intent_accuracy_percent": rate("intent_correct"),
        "room_accuracy_percent": rate("room_correct"),
        "average_response_time_ms": round(mean(response_times), 2) if response_times else 0.0,
        "average_action_count": round(mean(action_counts), 2) if action_counts else 0.0,
        "average_comfort_score": round(mean(comfort_scores), 2) if comfort_scores else 0.0,
        "average_current_power_w": round(mean(power_values), 2) if power_values else 0.0,
    }
