# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-11-19

Additive release: the recorder-side sample fan-in moves into the core record
layer. No breaking change to any existing call, and the package still provides
no run control or CLI.

### Added

- `pysos_interop.fanin.SampleFanIn`, a standard-library per-sample barrier that
  aligns one ordinal from every expected slug before recording. It keeps the
  `observe`/`poll`/`flush` contract, per-slug ordinals and the 2 s watchdog
  partial flush, with an injectable clock for tests.
- `pysos_interop.fanin.sample_timestamp(ordinal, sample_period_s=0.1)`, the
  RPR-edge time base: RPR has no time field, so sample `n` is at
  `n * sample_period_s`.
- Both names are re-exported from `pysos_interop` and are core API; the fan-in
  is not part of the optional `rpr` extra.

### Compatibility

- The fan-in was moved from the flight-sim recorder scripts without a behaviour
  change. It imports no RPR/protobuf package, opens no socket and writes no
  file; the callback owns recording.

## [0.3.0] - 2026-11-19

Additive release: optional per-entity labels and colours for the Rerun export,
so a multi-aircraft run is readable in the viewer. No breaking change to any
existing call.

### Added

- `recordings_to_rrd(..., labels=..., colors=...)` and the `RerunSink`
  constructor accept optional mappings keyed by the wire slug
  `<site>_<application>_<entity>`.
- A supplied label is logged as a static `TextDocument` at
  `world/entity/<slug>/label` on the `sim_time` timeline. A supplied 0-255 RGB
  colour is applied to that entity's `marker` (`Boxes3D`) and `trail`
  (`LineStrips3D`).
- Slugs without an entry keep the previous output; no automatic label or
  palette is invented, so an old call produces the same `.rrd`.

## [0.2.1] - 2026-11-19

Packaging fix: the `rpr` extra pins the sibling release wheel; no API change.

## [0.2.0] - 2026-11-19

Additive release: the RPR decode path, the truth recorder with its metadata
sidecar and measurement CSV, and the optional Rerun sink. No breaking changes
to the entity model, the DIS codec, the JSONL recording format or the public
core surface.

### Added

- Optional `rpr` extra: an independent RPR-derived protobuf codec in
  `pysos_interop.rpr`. `RprOrigin` defines the explicit local ENU frame
  (WGS84 or ECEF reference point); RPR ECEF position and body-frame velocity
  convert to and from `EntityState`.
- `RprExtras` preserves the dead-reckoning algorithm and parameter bytes, body
  acceleration, `is_frozen`, entity type, platform kind and marking character
  set. Strict and lenient decode forward the `pysos_rpr` unknown-field policy.
- `RprChannel` adapts one `transport.Channel` as a synchronous RPR source/sink.
- `RprJsonlRecorder`, `iter_rpr_jsonl`, `iter_rpr_frames` and
  `replay_rpr_jsonl` record payloads with optional sequence and timestamp.
  The existing JSONL/DIS recording path is unchanged.
- `TruthRecorder` and `iter_truth` record one row per entity per sample with a
  `<run>.meta.json` sidecar: run id, origin, model ids, entity catalogue,
  sample rates, format version and start time.
- `export_measure_csv` writes the canonical `time` plus scalar-column CSV that
  `pyssp_vv.measure.Trajectory` consumes directly, including `nan` for a
  missing sample.
- Optional `rerun` extra: `pysos_interop.rerun_sink` logs `EntityState` or
  decoded `RprFrame` values to an `.rrd` file at
  `world/entity/<site>_<app>_<entity>/{pose,trail,marker}` and
  `status/{airspeed_mps,altitude_m,climb_rate_mps}`. `recordings_to_rrd`
  converts a recorded JSONL stream. `rerun` is imported lazily; the core
  never imports it.

### Compatibility

- Three independent optional extras: `dis`, `rpr` and `rerun`. None is
  installed with the core, and `import pysos_interop` still pulls in no
  third-party package.
- `rpr` depends on `pysos-rpr>=0.1`, a sibling release from the same
  organisation, not on any other `pysos_*` or `pyssp_*` package.
- `rpr` and `rerun` are available on Python >= 3.11 only; the core and `dis`
  keep their previous floor of Python 3.10.

## [0.1.0] - 2026-11-19

### Added

- `EntityKey` and the neutral `EntityState` model in local ENU metres, with
  Z-Y-X Euler attitude and body-frame angular velocity.
- Exact Z-Y-X Euler-rate to body-rate conversion and its inverse, with a clear
  error at the pitch singularity.
- DIS dead reckoning algorithms 1, 2 and 4, plus `is_stale`.
- `Channel`, a typed UDP unicast/multicast socket wrapper.
- Optional `dis` extra: IEEE 1278.1 Entity State PDU encode/decode with WGS84
  ECEF, wire Euler angles, and body-frame angular velocity.
- `JsonlRecorder` and `iter_jsonl` for transport-agnostic record and replay.
- Standard-library-only core with an explicit public surface.
