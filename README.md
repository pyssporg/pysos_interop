# pysos_interop

`pysos_interop` is the communication hub contract for system-of-systems simulation: one neutral `EntityState` plus working protocol interop, so engines and viewers exchange entity state without owning each other's schema. The core is standard-library only; DIS and RPR support are optional extras.

## Install

```bash
pip install pysos-interop
pip install "pysos-interop[dis]"   # IEEE 1278.1 Entity State PDU codec
pip install "pysos-interop[rpr]"   # RPR-derived protobuf codec, Python >= 3.11
```

The core never imports either adapter. `pysos_interop.rpr` imports `pysos_rpr`
when the module is imported, so RPR is a dependency of that path only; the
`dis` and `rpr` extras are independent.

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
