# Layers

The repository is a stack with one-way dependencies. A higher layer may import
a lower one; a lower layer never imports a higher one.

```text
dis (optional)   rpr (optional)   jsonl   truth   transport
     │                 │              │       │          │
     └─────────────────┼──────────────┼───────┼──────────┘
                       │
                dead_reckoning
                       │
             model   rates   geo
```

## `model`

`EntityKey` and `EntityState`. No I/O, no imports beyond the standard library,
no protocol identity. This is the only state shape in the family.

## `rates`

Z-Y-X Euler-rate to body-rate conversion and its exact inverse. Depends only on
`model` for the `Vec3` alias. The inverse is undefined at pitch `+/-90` and says
so with `ValueError`.

## `geo`

WGS84 geodetic, ECEF and local ENU conversions plus `GeoOrigin`. Pure
standard-library maths. DIS needs it; the core model does not.

## `dead_reckoning`

Pure propagation for DIS algorithms 1, 2 and 4, and `is_stale`. Consumes the
model and `rates`; performs no I/O.

## `jsonl`

`JsonlRecorder` and `iter_jsonl`. Transport-agnostic persistence of
`EntityState`. One JSON object per line, field order mirrors the dataclass.

## `truth`

`TruthRecorder`, `iter_truth`, the metadata sidecar and `export_measure_csv`.
The truth stream is one JSON object per entity per sample; it is a superset of
the `jsonl` row (it adds a `sample` index), so `iter_jsonl` also reads it. The
sidecar records run id, origin, model ids, the observed entity catalogue,
sample rates, format version and start time. The CSV export is a leading
`time` column plus one float column per entity/channel; that is the tabular
shape `pyssp_vv.measure.Trajectory` consumes directly, with no adapter and no
value translation. Missing samples are `nan`, never zero.

## `transport`

`Channel`, a single UDP socket for unicast or multicast. Construction, open,
send, receive and close are explicit. Every socket failure becomes a
`TransportError`; a receive timeout becomes `ChannelTimeoutError`.

## `dis` (optional extra)

IEEE 1278.1 Entity State PDU encode and decode. Imports `opendis` only when the
module is imported, never from the package `__init__`. This is where ENU becomes
ECEF, Euler radians become DIS `psi/theta/phi`, and algorithm-4 velocity becomes
body-frame. Angular velocity crosses unchanged because both sides use body axes.

## `rpr` (optional extra)

RPR-derived protobuf encode and decode over `pysos_rpr.messages`. Imports
`pysos_rpr` only when the module is imported, never from the package
`__init__`. RPR position is ECEF, so every call takes an explicit `RprOrigin`
(WGS84 lat/lon/height or `RprOrigin.from_ecef`); there is no global default.
Velocity is always body-frame and crosses to ENU through the orientation.
`RprExtras` carries the dead-reckoning algorithm and parameter bytes, body
acceleration, `is_frozen`, entity type, platform kind and marking character
set; `exercise_id` and `timestamp` have no RPR field. `RprChannel` is a
synchronous source/sink over one `Channel`, and `RprJsonlRecorder` plus
`iter_rpr_frames`/`replay_rpr_jsonl` provide a separate record/replay path so
the DIS recording format stays untouched.

## Rule

Protocol knowledge lives only in `dis` and `rpr` (and the frame/rate helpers
they call). If a conversion is needed by an engine, it belongs in that engine
or in `rates`/`geo`, not in `model`.
