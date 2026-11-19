# Layers

The repository is a stack with one-way dependencies. A higher layer may import
a lower one; a lower layer never imports a higher one.

```text
dis (optional)   jsonl        transport
     │              │             │
     └──────────────┼─────────────┘
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

## `transport`

`Channel`, a single UDP socket for unicast or multicast. Construction, open,
send, receive and close are explicit. Every socket failure becomes a
`TransportError`; a receive timeout becomes `ChannelTimeoutError`.

## `dis` (optional extra)

IEEE 1278.1 Entity State PDU encode and decode. Imports `opendis` only when the
module is imported, never from the package `__init__`. This is where ENU becomes
ECEF, Euler radians become DIS `psi/theta/phi`, and algorithm-4 velocity becomes
body-frame. Angular velocity crosses unchanged because both sides use body axes.

## Rule

Protocol knowledge lives only in `dis` (and the frame/rate helpers it calls).
If a conversion is needed by an engine, it belongs in that engine or in
`rates`/`geo`, not in `model`.
