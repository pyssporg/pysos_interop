# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
