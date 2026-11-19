"""Truth-stream recording, sidecar metadata and measurement CSV export.

A recorded run has three artifacts:

* the truth stream, one JSON object per entity per sample;
* a sidecar metadata file next to it with the run identity and catalogue;
* a measurement CSV with one ``time`` column and one float column per
  entity/channel, the shape ``pyssp_vv.measure.Trajectory`` consumes directly.

The truth stream is a superset of the :mod:`pysos_interop.jsonl` row: it adds
a ``sample`` index and keeps the same state fields, so ``iter_jsonl`` can also
read it.  The CSV export is not an adapter around the measurement tool; it is
the tabular form of the same truth stream, with no translation step between
recording and measurement.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .geo import GeoOrigin
from .jsonl import _state_from_dict, _state_to_dict
from .model import EntityKey, EntityState

FORMAT_VERSION = "1"

#: Measurement channels exported per entity, in column order.
MEASURE_CHANNELS: tuple[str, ...] = (
    "position_east_m",
    "position_north_m",
    "position_up_m",
    "velocity_east_mps",
    "velocity_north_mps",
    "velocity_up_mps",
    "orientation_roll_rad",
    "orientation_pitch_rad",
    "orientation_yaw_rad",
    "angular_velocity_x_rps",
    "angular_velocity_y_rps",
    "angular_velocity_z_rps",
)

#: Units for :data:`MEASURE_CHANNELS`, written to the metadata sidecar.
MEASURE_UNITS: dict[str, str] = {
    "position_east_m": "m",
    "position_north_m": "m",
    "position_up_m": "m",
    "velocity_east_mps": "m/s",
    "velocity_north_mps": "m/s",
    "velocity_up_mps": "m/s",
    "orientation_roll_rad": "rad",
    "orientation_pitch_rad": "rad",
    "orientation_yaw_rad": "rad",
    "angular_velocity_x_rps": "rad/s",
    "angular_velocity_y_rps": "rad/s",
    "angular_velocity_z_rps": "rad/s",
}


def entity_slug(key: EntityKey) -> str:
    """Documented entity slug: ``<site>_<application>_<entity>``."""

    return f"{key.site}_{key.application}_{key.entity}"


def truth_metadata_path(path: str | Path) -> Path:
    """Return the sidecar metadata path for a truth stream."""

    return Path(path).with_suffix(".meta.json")


def _channel_values(state: EntityState) -> dict[str, float]:
    position = state.position_enu_m
    velocity = state.velocity_enu_mps
    orientation = state.orientation_rps
    angular = state.angular_velocity_rps
    return {
        "position_east_m": float(position[0]),
        "position_north_m": float(position[1]),
        "position_up_m": float(position[2]),
        "velocity_east_mps": float(velocity[0]),
        "velocity_north_mps": float(velocity[1]),
        "velocity_up_mps": float(velocity[2]),
        "orientation_roll_rad": float(orientation[0]),
        "orientation_pitch_rad": float(orientation[1]),
        "orientation_yaw_rad": float(orientation[2]),
        "angular_velocity_x_rps": float(angular[0]),
        "angular_velocity_y_rps": float(angular[1]),
        "angular_velocity_z_rps": float(angular[2]),
    }


@dataclass(frozen=True)
class TruthMetadata:
    """Sidecar metadata for one recorded truth stream.

    ``start_time_sim`` is the simulation timestamp of the first sample;
    ``started_utc`` is when the recorder was opened.  ``entities`` is the
    catalogue actually observed, sorted by entity key.
    """

    run_id: str
    origin: GeoOrigin
    model_ids: Mapping[str, str]
    entities: tuple[Mapping[str, Any], ...]
    rates: Mapping[str, float]
    format_version: str
    start_time_sim: float | None
    started_utc: str
    sample_count: int
    units: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "run_id": self.run_id,
            "started_utc": self.started_utc,
            "start_time_sim": self.start_time_sim,
            "sample_count": int(self.sample_count),
            "origin": {
                "latitude_deg": float(self.origin.latitude_deg),
                "longitude_deg": float(self.origin.longitude_deg),
                "altitude_m": float(self.origin.altitude_m),
            },
            "model_ids": dict(sorted(self.model_ids.items())),
            "entities": [dict(entity) for entity in self.entities],
            "rates": {name: float(value) for name, value in sorted(self.rates.items())},
            "units": dict(sorted(self.units.items())),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TruthMetadata:
        origin = data["origin"]
        return cls(
            run_id=str(data["run_id"]),
            origin=GeoOrigin(
                latitude_deg=float(origin["latitude_deg"]),
                longitude_deg=float(origin["longitude_deg"]),
                altitude_m=float(origin["altitude_m"]),
            ),
            model_ids={str(k): str(v) for k, v in data.get("model_ids", {}).items()},
            entities=tuple(dict(entity) for entity in data.get("entities", ())),
            rates={str(k): float(v) for k, v in data.get("rates", {}).items()},
            format_version=str(data["format_version"]),
            start_time_sim=(
                None if data.get("start_time_sim") is None else float(data["start_time_sim"])
            ),
            started_utc=str(data["started_utc"]),
            sample_count=int(data.get("sample_count", 0)),
            units={str(k): str(v) for k, v in data.get("units", {}).items()},
        )


class TruthRecorder:
    """Record one row per entity per sample, plus a metadata sidecar.

    ``write_sample`` takes all entities of one sample and gives them the same
    ``sample`` index.  ``write`` is the single-entity convenience form.  The
    sidecar is written when the recorder opens and rewritten by ``close`` once
    the entity catalogue is known.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        run_id: str,
        origin: GeoOrigin | None = None,
        model_ids: Mapping[str, str] | None = None,
        sample_rate_hz: float | None = None,
        rates: Mapping[str, float] | None = None,
        start_time: float | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path = truth_metadata_path(self.path)
        self.run_id = str(run_id)
        self.origin = origin or GeoOrigin()
        self.model_ids = {str(k): str(v) for k, v in (model_ids or {}).items()}
        self.start_time_sim = start_time
        self.started_utc = datetime.now(timezone.utc).isoformat()
        declared_rates = dict(rates or {})
        if sample_rate_hz is not None:
            declared_rates["sample_hz"] = float(sample_rate_hz)
            declared_rates["sample_period_s"] = 1.0 / float(sample_rate_hz)
        self.rates = declared_rates
        self._sample = 0
        self._catalogue: dict[str, dict[str, Any]] = {}
        self._closed = False
        self._file = self.path.open("w", encoding="utf-8")
        self._write_metadata()

    def _entity_entry(self, state: EntityState) -> dict[str, Any]:
        slug = entity_slug(state.key)
        return {
            "entity": slug,
            "key": {
                "site": int(state.key.site),
                "application": int(state.key.application),
                "entity": int(state.key.entity),
            },
            "marking": state.marking,
            "force_id": int(state.force_id),
            "exercise_id": int(state.exercise_id),
            "model_id": self.model_ids.get(slug),
        }

    def write_sample(self, states: Iterable[EntityState]) -> int:
        """Write every state of one sample and return its sample index."""

        batch = list(states)
        if not batch:
            raise ValueError("write_sample needs at least one state")
        sample = self._sample
        for state in batch:
            row = {"sample": sample, **_state_to_dict(state)}
            self._file.write(json.dumps(row, separators=(",", ":")) + "\n")
            self._catalogue.setdefault(entity_slug(state.key), self._entity_entry(state))
            if self.start_time_sim is None:
                self.start_time_sim = float(state.timestamp)
        self._file.flush()
        self._sample += 1
        return sample

    def write(self, state: EntityState) -> int:
        """Write one entity as its own sample."""

        return self.write_sample([state])

    def metadata(self) -> TruthMetadata:
        """Return the metadata for the stream recorded so far."""

        entities = tuple(self._catalogue[slug] for slug in sorted(self._catalogue))
        return TruthMetadata(
            run_id=self.run_id,
            origin=self.origin,
            model_ids=self.model_ids,
            entities=entities,
            rates=self.rates,
            format_version=FORMAT_VERSION,
            start_time_sim=self.start_time_sim,
            started_utc=self.started_utc,
            sample_count=self._sample,
            units=MEASURE_UNITS,
        )

    def _write_metadata(self) -> None:
        payload = self.metadata().to_dict()
        self.metadata_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._file.closed:
            self._file.close()
        self._write_metadata()

    def __enter__(self) -> TruthRecorder:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def iter_truth(path: str | Path) -> Iterator[EntityState]:
    """Yield the entity states of a truth stream, in file order."""

    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield _state_from_dict(json.loads(stripped))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid truth record on line {line_number} of {path}: {exc}"
                ) from exc


def read_truth_metadata(path: str | Path) -> TruthMetadata:
    """Read the sidecar metadata of a truth stream."""

    metadata_path = truth_metadata_path(path)
    return TruthMetadata.from_dict(json.loads(metadata_path.read_text(encoding="utf-8")))


def measure_columns(entities: Iterable[str]) -> list[str]:
    """Return the measurement CSV header for the given entity slugs."""

    columns = ["time"]
    for slug in entities:
        columns.extend(f"{slug}.{channel}" for channel in MEASURE_CHANNELS)
    return columns


def export_measure_csv(truth_path: str | Path, csv_path: str | Path) -> Path:
    """Export a truth stream as a measurement CSV.

    The CSV has a leading ``time`` column in simulation seconds and one float
    column per entity/channel named ``<site>_<app>_<entity>.<channel>``.  Rows
    are the sorted union of recorded timestamps; an entity that has no sample
    at a timestamp gets ``nan`` in its columns, which the measurement layer
    treats as missing coverage rather than as a zero.

    Feed the columns of one entity to ``pyssp_vv.measure.Trajectory`` after
    stripping the ``<slug>.`` prefix; no value translation is needed.
    """

    states = list(iter_truth(truth_path))
    target = Path(csv_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    slugs = sorted({entity_slug(state.key) for state in states}, key=_slug_sort_key)
    times = sorted({float(state.timestamp) for state in states})
    cells: dict[tuple[float, str], dict[str, float]] = {}
    for state in states:
        # Last sample wins for a duplicate (entity, timestamp) pair.
        cells[(float(state.timestamp), entity_slug(state.key))] = _channel_values(state)

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(measure_columns(slugs))
        for timestamp in times:
            row: list[str] = [repr(timestamp)]
            for slug in slugs:
                values = cells.get((timestamp, slug))
                for channel in MEASURE_CHANNELS:
                    row.append("nan" if values is None else repr(values[channel]))
            writer.writerow(row)
    return target


def _slug_sort_key(slug: str) -> tuple[int, int, int]:
    site, application, entity = slug.split("_")
    return (int(site), int(application), int(entity))


__all__ = [
    "FORMAT_VERSION",
    "MEASURE_CHANNELS",
    "MEASURE_UNITS",
    "TruthMetadata",
    "TruthRecorder",
    "entity_slug",
    "export_measure_csv",
    "iter_truth",
    "measure_columns",
    "read_truth_metadata",
    "truth_metadata_path",
]
