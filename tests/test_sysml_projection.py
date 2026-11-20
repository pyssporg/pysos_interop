"""The SysML projection is generated from ``EntityState`` and stays in sync."""

from __future__ import annotations

import importlib.util
import types
import typing
from dataclasses import MISSING, fields
from pathlib import Path

import pytest

from pysos_interop.model import EntityState

ROOT = Path(__file__).resolve().parents[1]
SYSML = ROOT / "sysml" / "entity_state.sysml"
GENERATOR = ROOT / "tools" / "generate_sysml.py"

# Mirrors the projection rule: identity, run facts, and static configuration
# are not port members.
EXCLUDED = frozenset(
    {
        "key",
        "timestamp",
        "exercise_id",
        "acceleration",
        "is_frozen",
        "entity_type",
        "platform_kind",
        "algorithm",
        "parameters",
    }
)

_PRIMITIVES = {bool: "Boolean", int: "Integer", float: "Real", str: "String"}


def _generator() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("generate_sysml", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_projection_is_fresh(tmp_path):
    fresh = tmp_path / "entity_state.sysml"
    _generator().write(fresh)
    assert fresh.read_bytes() == SYSML.read_bytes()


def _expected_members() -> list[tuple[str, str, str | None]]:
    hints = typing.get_type_hints(EntityState)
    members = []
    for field in fields(EntityState):
        if field.name in EXCLUDED:
            continue
        annotation = hints[field.name]
        if typing.get_origin(annotation) is tuple:
            items = typing.get_args(annotation)
            primitives = {_PRIMITIVES[item] for item in items}
            assert len(primitives) == 1, field.name
            members.append((field.name, primitives.pop(), str(len(items))))
        else:
            members.append((field.name, _PRIMITIVES[annotation], None))
    return members


def test_port_definition_matches_dataclass():
    sysml2 = pytest.importorskip("pycps_sysml2")
    try:
        architecture = sysml2.load(SYSML)
    except Exception as exc:  # report the parser's verdict, do not hide it
        pytest.fail(f"pycps_sysml2 rejected {SYSML.relative_to(ROOT)}: {exc}")

    assert "EntityState" in architecture.port_definitions
    port = architecture.port_definitions["EntityState"]
    expected = _expected_members()

    assert list(port.attributes) == [name for name, _, _ in expected]
    for name, primitive, multiplicity in expected:
        attribute = port.attributes[name]
        assert attribute.type_name == primitive, name
        assert attribute.multiplicity == multiplicity, name

    forced = next(field for field in fields(EntityState) if field.name == "force_id")
    assert forced.default is not MISSING
    assert port.attributes["force_id"].value == forced.default

    entity = architecture.part_definitions["Entity"]
    state = entity.ports["entityState"]
    assert state.direction == "out"
    assert state.type_name == "EntityState"
