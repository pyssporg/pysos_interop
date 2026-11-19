# Entity model

## Identity

```text
EntityKey(site: int, application: int, entity: int)
```

The triple is the DIS entity identifier and nothing more. It is frozen,
ordered and hashable, so it can key dictionaries and compare deterministically.
`str(key)` renders `site:application:entity`.

## State

```text
EntityState(
    key: EntityKey,
    timestamp: float,
    position_enu_m: (east, north, up) metres,
    velocity_enu_mps: (east, north, up) metres/second,
    orientation_rps: (roll, pitch, yaw) radians,
    angular_velocity_rps: (p, q, r) body axes, radians/second,
    marking: str,
    force_id: int = 1,
    exercise_id: int = 1,
)
```

The dataclass is frozen. Updates produce new values (`dataclasses.replace`),
which keeps replay, dead reckoning and fan-out free of aliasing bugs.

`orientation_rps` follows the Z-Y-X convention: yaw about the local vertical,
then pitch, then roll. The suffix mirrors the protocol field name; the value is
an angle in radians, not a rate.

`angular_velocity_rps` is about body axes `x` forward, `y` right, `z` down. DIS
carries exactly this, so it crosses the boundary unchanged. Engine Euler rates
are converted with `euler_rates_to_body_rates` before they enter the model.

## Frames

| Quantity | Model | DIS wire |
| --- | --- | --- |
| Position | local ENU metres | WGS84 ECEF metres |
| Linear velocity | local ENU m/s | ECEF (alg 1/2) or body (alg 4) |
| Orientation | `(roll, pitch, yaw)` rad | `(psi, theta, phi)` rad |
| Angular velocity | body `(p, q, r)` rad/s | body `(p, q, r)` rad/s |

The local frame is defined by a `GeoOrigin`. The DIS codec defaults to the
WGS84 point at 0 latitude, 0 longitude, 0 altitude; callers that care about a
scenario area pass their own origin to both encode and decode. The RPR codec
requires an explicit `RprOrigin` with no default; its position is ECEF and its
velocity is body-frame, so it also converts linear velocity at the boundary.

## Time and staleness

`timestamp` is simulation seconds. The DIS encoder converts it to a
hour-relative 31-bit header timestamp; the decoder recovers it from that field,
so the value wraps every hour. Records and dead reckoning use the model value.

`is_stale(state, now, threshold)` is a strict comparison: an age equal to the
threshold is fresh. Staleness is a query, not a field, so the same state can be
judged against different consumers' thresholds.

## What is deliberately absent

- Entity type, domain and category: identity metadata outside the hub contract;
  DIS uses a neutral platform/air entry.
- Stale flag: derived by `is_stale`.
- Scenario, route, force or exercise catalogue: not state.
- Free-form metadata: a schema by another name; extensions must be explicit.
