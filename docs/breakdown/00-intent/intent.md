# Intent — `pysos_interop`

## Why

System-of-systems simulation suffers a structural problem before any physics
runs: every engine and viewer invents its own entity-state shape, and then one
of them becomes the de-facto schema. The others grow adapters that leak that
schema inward, and the hub is owned by whoever wrote the first adapter.

`pysos_interop` exists to make the hub neutral. It fixes **one** entity state
and a small set of protocols, so engines, viewers, recorders and analysis tools
meet at a shared, replaceable seam instead of negotiating pairwise.

## Commitments

- **One entity model.** `EntityState` is the vocabulary. New needs extend it
  deliberately, not by adding a second parallel model.
- **Protocol conversion at the boundary.** ENU versus ECEF, Euler versus body
  rates, and wire field order are adapter concerns. The model itself stays
  frame-explicit and protocol-free.
- **Standard-library core.** `pysos_interop` must install and import anywhere
  Python 3.10+ runs. Optional protocols, DIS and RPR, are extras; neither is
  imported by the core.
- **Pure, testable kernels.** Rate conversion, dead reckoning and staleness are
  pure functions with explicit inputs. Transport raises typed errors.
- **Record and replay without a transport.** JSONL is the lowest common
  denominator for evidence and regression tests.
- **Interoperate with real traffic.** The DIS codec is checked against an
  independent golden PDU, not only against its own encoder.

## Non-goals

- **Not an orchestrator.** No run control, federation management, time
  synchronisation, or scheduling. An orchestrator consumes this contract.
- **Not an engine.** No dynamics, integration, or model execution.
- **Not a scenario format.** No exercise file, routing table, or project-specific
  UDP JSON schema. The truth-stream sidecar records the entity catalogue
  observed in a run, for provenance only; it is never read back as a scenario
  input.
- **Not a viewer.** No rendering, live bridge, viewer process, or UI. An
  optional, lazily imported sink may export a recorded or handed-in entity
  stream to an `.rrd` file for offline inspection; it owns no process and is
  not a live protocol bridge.
- **Not an application.** No CLI and no run control. `Channel`, `RprChannel`,
  `JsonlRecorder`, `RprJsonlRecorder` and the `iter_*` functions are library
  edge code, not sinks that own a process.
- **Not a dependency hub for the family.** The core depends on no other
  `pysos_*` or `pyssp_*` package and imports neither DIS nor RPR. The optional
  RPR adapter is the only sibling dependency, isolated in the `rpr` extra.
