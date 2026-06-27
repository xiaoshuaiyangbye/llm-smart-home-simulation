from typing import Any


def state_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    diff: dict[str, dict[str, Any]] = {}
    _walk("", before, after, diff)
    return diff


def _walk(path: str, before: Any, after: Any, diff: dict[str, dict[str, Any]]) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after))
        for key in keys:
            next_path = f"{path}.{key}" if path else str(key)
            _walk(next_path, before.get(key), after.get(key), diff)
        return

    if isinstance(before, list) and isinstance(after, list):
        if _entity_list(before) and _entity_list(after):
            before_by_id = {item["entity_id"]: item for item in before}
            after_by_id = {item["entity_id"]: item for item in after}
            for key in sorted(set(before_by_id) | set(after_by_id)):
                _walk(f"{path}[{key}]", before_by_id.get(key), after_by_id.get(key), diff)
            return
        if _room_list(before) and _room_list(after):
            before_by_id = {item["room_id"]: item for item in before}
            after_by_id = {item["room_id"]: item for item in after}
            for key in sorted(set(before_by_id) | set(after_by_id)):
                _walk(f"{path}[{key}]", before_by_id.get(key), after_by_id.get(key), diff)
            return
        if before != after:
            diff[path] = {"before": before, "after": after}
        return

    if before != after:
        diff[path] = {"before": before, "after": after}


def _entity_list(items: list[Any]) -> bool:
    return all(isinstance(item, dict) and "entity_id" in item for item in items)


def _room_list(items: list[Any]) -> bool:
    return all(isinstance(item, dict) and "room_id" in item for item in items)

