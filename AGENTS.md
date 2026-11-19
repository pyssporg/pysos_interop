# AGENTS

## Vision first (required)

Before you read code, edit files, or plan a change, read:

**`docs/breakdown/00-intent/intent.md`**

It states why this repository exists, what it commits to, and what it refuses
to become. Judge every change against it. If a change conflicts with the
intent, stop and surface the conflict; do not implement it silently.

## Repository focus

`pysos_interop` is the communication hub contract for the `pysos_*` family.
It owns a neutral entity-state model plus protocol adapters at the edge. It
does not own scenarios, orchestration, engines, or project-specific payloads.

- Modules: `model`, `rates`, `geo`, `dead_reckoning`, `transport`, `jsonl`,
  `truth`, and the optional `dis`, `rpr` and `rerun` adapters.
- It sits near the bottom of the dependency graph; consumers depend on it,
  never the reverse.

## Hard constraints

- **The core imports only the standard library.** `numpy` and every other
  third-party package are forbidden at import time.
- **One entity model.** `EntityState` is the only state shape. Do not add
  parallel or protocol-shaped models; convert at the boundary.
- **Protocol conversion only at the boundary.** ENU/ECEF, Euler/body rates,
  and DIS field ordering belong in `dis`, `geo`, or `rates`, never in
  `model`, engines, or recorders.
- **No project schemas.** No scenario format, UDP JSON payload schema,
  Rerun bridge, or consumer-specific field may enter this repository.
- **The core has no dependency on another `pysos_*` or `pyssp_*` package.**
  Optional protocol extras may depend on a sibling vocabulary package: only
  the `rpr` extra uses `pysos-rpr`, and the core never imports it.
- **Protocol dependencies are optional.** `import pysos_interop` and every core
  module must work without `opendis` and `pysos_rpr`; only
  `pysos_interop.dis` and `pysos_interop.rpr` may require them, and only when
  those modules are imported.
- **No CLI and no application framework.** `Channel`, `RprChannel`,
  `JsonlRecorder`, `RprJsonlRecorder` and the `iter_*` functions are library
  edge code; do not add run control.

## Code guidelines

- Public vocabulary is small and stable: `EntityKey`, `EntityState`, `Channel`,
  `JsonlRecorder`. Prefer plain dataclasses and explicit arguments.
- Pure functions for rates and dead reckoning; no hidden clock or global state.
- Transport failures raise typed errors. Never swallow an error silently.
- Tests must cover the independent wire convention, not only encode/decode
  agreement with itself.

## Environment

- Python >= 3.10, `src/` layout.
- Install: `pip install -e ".[dev]"` (includes `opendis` for the DIS tests).
- Tests: `python -m pytest -m "not network"`; lint: `ruff check src tests`
  (line length 100, target py310).
