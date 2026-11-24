"""Public surface and import-isolation tests."""

import os
import subprocess
import sys
from pathlib import Path

import pysos_interop


def test_public_surface_is_explicit():
    expected = {
        "Channel",
        "ChannelClosedError",
        "ChannelTimeoutError",
        "EntityKey",
        "EntityState",
        "GeoOrigin",
        "JsonlRecorder",
        "SampleFanIn",
        "TransportError",
        "TruthMetadata",
        "UnixChannel",
        "TruthRecorder",
        "__version__",
        "body_rates_to_euler_rates",
        "dead_reckon",
        "ecef_to_enu",
        "ecef_to_geodetic",
        "enu_to_ecef",
        "euler_rates_to_body_rates",
        "export_measure_csv",
        "geodetic_to_ecef",
        "is_stale",
        "iter_jsonl",
        "iter_truth",
        "read_truth_metadata",
        "sample_timestamp",
    }
    assert set(pysos_interop.__all__) == expected
    for name in pysos_interop.__all__:
        assert hasattr(pysos_interop, name)
    assert pysos_interop.__version__ == "0.4.0"


def _run(code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_core_import_does_not_load_opendis():
    result = _run(
        "import sys, pysos_interop; "
        "assert 'opendis' not in sys.modules, sorted(sys.modules); "
        "assert 'pysos_interop.dis' not in sys.modules"
    )
    assert result.returncode == 0, result.stderr


def test_core_import_does_not_load_pysos_rpr():
    result = _run(
        "import sys, pysos_interop; "
        "assert 'pysos_rpr' not in sys.modules, sorted(sys.modules); "
        "assert 'pysos_interop.rpr' not in sys.modules"
    )
    assert result.returncode == 0, result.stderr


def test_missing_opendis_fails_only_when_dis_is_used():
    code = """
import sys

class Blocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "opendis" or fullname.startswith("opendis."):
            raise ImportError("blocked for test")
        return None

sys.meta_path.insert(0, Blocker())
import pysos_interop

try:
    import pysos_interop.dis
except ImportError as exc:
    assert "pysos-interop[dis]" in str(exc), exc
else:
    raise SystemExit("expected ImportError")
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr
