"""Transport-agnostic JSON Lines record and replay of entity state."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .model import EntityKey, EntityState


def _state_to_dict(state: EntityState) -> dict[str, Any]:
    key = state.key
    return {
        "key": {
            "site": int(key.site),
            "application": int(key.application),
            "entity": int(key.entity),
        },
        "timestamp": float(state.timestamp),
        "position_enu_m": [float(value) for value in state.position_enu_m],
        "velocity_enu_mps": [float(value) for value in state.velocity_enu_mps],
        "orientation_rps": [float(value) for value in state.orientation_rps],
        "angular_velocity_rps": [float(value) for value in state.angular_velocity_rps],
        "marking": str(state.marking),
        "force_id": int(state.force_id),
        "exercise_id": int(state.exercise_id),
    }


def _state_from_dict(data: dict[str, Any]) -> EntityState:
    key = data["key"]
    return EntityState(
        key=EntityKey(
            site=int(key["site"]),
            application=int(key["application"]),
            entity=int(key["entity"]),
        ),
        timestamp=float(data["timestamp"]),
        position_enu_m=tuple(float(value) for value in data["position_enu_m"]),  # type: ignore[arg-type]
        velocity_enu_mps=tuple(float(value) for value in data["velocity_enu_mps"]),  # type: ignore[arg-type]
        orientation_rps=tuple(float(value) for value in data["orientation_rps"]),  # type: ignore[arg-type]
        angular_velocity_rps=tuple(  # type: ignore[arg-type]
            float(value) for value in data.get("angular_velocity_rps", (0.0, 0.0, 0.0))
        ),
        marking=str(data["marking"]),
        force_id=int(data.get("force_id", 1)),
        exercise_id=int(data.get("exercise_id", 1)),
    )


class JsonlRecorder:
    """Append entity states as one JSON object per line.

    The file is opened when the recorder is constructed and closed by
    :meth:`close` or by leaving the context manager.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file = self.path.open("w", encoding="utf-8")

    def write(self, state: EntityState) -> None:
        """Write one state as a single line and flush it."""

        self._file.write(
            json.dumps(_state_to_dict(state), separators=(",", ":")) + "\n"
        )
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def __enter__(self) -> JsonlRecorder:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def iter_jsonl(path: str | Path) -> Iterator[EntityState]:
    """Yield the entity states recorded in ``path``, in file order."""

    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield _state_from_dict(json.loads(stripped))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid entity state on line {line_number} of {path}: {exc}"
                ) from exc
