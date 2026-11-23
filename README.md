# pysos_interop

`pysos_interop` is the communication hub contract for system-of-systems simulation: one neutral `EntityState` plus working protocol interop, so engines and viewers exchange entity state without owning each other's schema. The core is standard-library only; DIS and RPR support are optional extras.

## Install

Python 3.10 or newer is required. The core has no dependencies; the optional
adapters need their extra and, for `rpr` and `rerun`, Python 3.11 or newer.

```bash
pip install pysos-interop
pip install "pysos-interop[dis]"   # IEEE 1278.1 Entity State PDU codec
pip install "pysos-interop[rpr]"   # RPR-derived protobuf codec, Python >= 3.11
pip install "pysos-interop[rerun]" # optional .rrd export, Python >= 3.11
pip install -e ".[dev]"            # this checkout, with tests and lint
pip install -e "repos/pysos_interop[dev]"  # from the workspace root
```

The core never imports any adapter. `pysos_interop.rpr` imports `pysos_rpr`
when the module is imported, so RPR is a dependency of that path only;
`pysos_interop.rerun_sink` imports `rerun` lazily when a sink is constructed.
The `dis`, `rpr` and `rerun` extras are independent.

## API

```python
from pysos_interop import EntityKey, EntityState, dead_reckon

key = EntityKey(1, 1, 7)
state = EntityState(key, 0.0, (0.0, 0.0, 1000.0), (50.0, 0.0, 0.0),
                    (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), "AC-7")
next_state = dead_reckon(state, 1.0, algorithm=2)
```

## RPR

RPR position is geocentric ECEF while `EntityState` is local ENU, so every
encode and decode requires an explicit `RprOrigin`. There is no default and no
process-wide origin.

```python
from pysos_interop.rpr import (
    RprExtras, RprOrigin, decode_frame, encode_entity_state,
)

origin = RprOrigin(57.7, 12.0, 100.0)        # WGS84 lat/lon/height
# origin = RprOrigin.from_ecef((x, y, z))   # or an ECEF reference point

payload = encode_entity_state(state, origin=origin)
frame = decode_frame(payload, origin=origin, timestamp=state.timestamp)
assert frame.state.key == state.key
```

- `decode_frame(..., strict=True)` rejects unknown protobuf fields;
  `strict=False` preserves them, and re-encoding is byte-identical.
- `RprExtras` carries the data `EntityState` has no field for: dead-reckoning
  algorithm and 15-octet parameter block, body acceleration, `is_frozen`,
  entity type, platform kind and marking character set. `exercise_id` and
  `timestamp` have no RPR field, so they are not on the wire.
- `RprChannel` wraps one `Channel` as a synchronous RPR source/sink. It owns no
  socket and starts no thread.
- `RprJsonlRecorder`, `iter_rpr_jsonl`, `iter_rpr_frames` and
  `replay_rpr_jsonl` record payload bytes with optional sequence and timestamp.
  This is a separate format from `JsonlRecorder`; the DIS recording format is
  unchanged.

## Truth stream and measurement CSV

`TruthRecorder` writes one row per entity per sample together with a
`<run>.meta.json` sidecar: run id, local origin, model ids, the observed entity
catalogue, sample rates, format version and start time.

```python
from pysos_interop import TruthRecorder, export_measure_csv, read_truth_metadata

with TruthRecorder("run.jsonl", run_id="r-42", sample_rate_hz=10.0,
                   model_ids={"1_1_7": "aircraft"}) as recorder:
    recorder.write_sample([state_a, state_b])   # one sample, all entities

metadata = read_truth_metadata("run.jsonl")
export_measure_csv("run.jsonl", "run.csv")
```

The CSV has a leading `time` column in simulation seconds and one float column
per entity/channel named `<site>_<app>_<entity>.<channel>`. Strip the
`<slug>.` prefix and feed one entity's columns to
`pyssp_vv.measure.Trajectory`; the values need no translation. A missing sample
is `nan`, which the measurement layer reports as missing coverage.

## Sample fan-in

`SampleFanIn` aligns one sample per expected slug when each RPR publisher owns
its own ordinal sequence. RPR has no time field, so
`sample_timestamp(n, sample_period_s)` defines sample `n` at
`n * sample_period_s`.

```python
from pysos_interop import SampleFanIn

fan_in = SampleFanIn(["1_1_7", "1_1_8"], write_sample, sample_period_s=0.1)
fan_in.observe("1_1_7", state_a)
fan_in.observe("1_1_8", state_b)   # flushes [state_a, state_b]
fan_in.poll()                      # applies the 2 s partial-sample watchdog
fan_in.flush()                     # drains the tail at end of stream
```

It is recorder-side assembly only: standard library, no socket, no file format,
no RPR import, and no run control or CLI.

## Rerun export (optional)

`pysos_interop.rerun_sink` turns a recorded JSONL stream, or live
`EntityState`/`RprFrame` values, into an `.rrd` file. It is synchronous, owns no
thread or socket, and imports `rerun` only when a sink is constructed, so the
core stays dependency-light and the module imports cleanly without the extra.

```python
from pysos_interop.rerun_sink import recordings_to_rrd

recordings_to_rrd(
    "run.jsonl",
    "run.rrd",
    app_id="pysos_interop",
    labels={"1_1_7": "ALPHA", "1_1_8": "BRAVO"},
    colors={"1_1_7": (0, 128, 255), "1_1_8": (255, 128, 0)},
)
```

Paths follow `world/entity/<site>_<app>_<entity>/{pose,trail,marker}` plus
`status/{airspeed_mps,altitude_m,climb_rate_mps}`. The Rerun world frame is
ENU and orientation is logged as a `(x, y, z, w)` quaternion.

`labels` and `colors` are optional and keyed by the documented wire slug
`<site>_<application>_<entity>`, not by marking. A supplied label becomes a
static `world/entity/<slug>/label` `TextDocument`; a supplied 0-255 RGB colour
tints that entity's `marker` and `trail`. Slugs without an entry keep the
previous output exactly; with neither mapping supplied the `.rrd` is unchanged.

## Development

```bash
python -m pytest                       # default suite
python -m pytest -m "not network"      # skip the opt-in multicast test
ruff check src tests
```

The multicast test is skipped unless `PYSOS_NETWORK_TESTS=1` is set. Ruff is
configured in `pyproject.toml` (line length 100, target `py310`). Read
[`AGENTS.md`](AGENTS.md) and the
[intent](docs/breakdown/00-intent/intent.md) before changing behaviour; the
module stack is in
[`docs/breakdown/02-architecture/layers.md`](docs/breakdown/02-architecture/layers.md).
