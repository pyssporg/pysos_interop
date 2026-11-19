# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
