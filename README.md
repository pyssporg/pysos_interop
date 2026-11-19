# pysos_interop

`pysos_interop` is the communication hub contract for system-of-systems simulation: one neutral `EntityState` plus working protocol interop, so engines and viewers exchange entity state without owning each other's schema. The core is standard-library only; DIS support is an optional extra.

## Install

```bash
pip install pysos-interop
pip install "pysos-interop[dis]"   # IEEE 1278.1 Entity State PDU codec
```

## API

```python
from pysos_interop import EntityKey, EntityState, dead_reckon

key = EntityKey(1, 1, 7)
state = EntityState(key, 0.0, (0.0, 0.0, 1000.0), (50.0, 0.0, 0.0),
                    (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), "AC-7")
next_state = dead_reckon(state, 1.0, algorithm=2)
```
