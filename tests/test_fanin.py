"""The recorder fan-in barrier completes samples and times out missing slugs."""

from __future__ import annotations

import pytest

from pysos_interop import SampleFanIn, sample_timestamp


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_complete_sample_flushes_when_every_slug_arrives():
    clock = _Clock()
    flushed: list[list[str]] = []
    fan_in = SampleFanIn(["a", "b"], flushed.append, sample_period_s=0.1, clock=clock)

    fan_in.observe("a", "a0")
    assert flushed == []
    fan_in.observe("b", "b0")

    assert flushed == [["a0", "b0"]]
    assert fan_in.samples == 1
    assert fan_in.complete_samples == 1
    assert fan_in.partial_samples == 0


def test_watchdog_flushes_a_partial_sample_instead_of_hanging():
    clock = _Clock()
    flushed: list[list[str]] = []
    fan_in = SampleFanIn(
        ["a", "b"], flushed.append, sample_period_s=0.1, watchdog_s=2.0, clock=clock
    )

    fan_in.observe("a", "a0")
    clock.now = 1.9
    fan_in.poll()
    assert flushed == []

    clock.now = 2.1
    fan_in.poll()
    assert flushed == [["a0"]]
    assert fan_in.pending == {}
    assert fan_in.partial_samples == 1
    assert fan_in.flushed_ordinals == [0.0]

    # The late publisher does not resurrect the already flushed sample.
    fan_in.observe("b", "b0")
    assert flushed == [["a0"]]
    clock.now = 4.2
    fan_in.poll()
    assert flushed == [["a0"], ["b0"]]


def test_flush_drains_incomplete_tail_at_end_of_stream():
    clock = _Clock()
    flushed: list[list[str]] = []
    fan_in = SampleFanIn(["a", "b"], flushed.append, clock=clock)

    fan_in.observe("a", "a0")
    fan_in.observe("a", "a1")
    fan_in.flush()

    assert flushed == [["a0"], ["a1"]]
    assert fan_in.samples == 2


def test_ordinals_advance_per_slug_and_key_samples_by_period():
    clock = _Clock()
    flushed: list[list[str]] = []
    fan_in = SampleFanIn(["b", "a", "a"], flushed.append, sample_period_s=0.05, clock=clock)

    assert fan_in.expected_slugs == ("a", "b")
    assert fan_in.ordinals["a"] == 0

    fan_in.observe("a", "a0")
    assert fan_in.ordinals["a"] == 1
    fan_in.observe("b", "b0")
    assert fan_in.ordinals["b"] == 1
    fan_in.observe("b", "b1")
    fan_in.observe("a", "a1")

    assert flushed == [["a0", "b0"], ["a1", "b1"]]
    assert fan_in.flushed_ordinals == [0.0, 0.05]
    assert fan_in.samples == 2
    assert fan_in.complete_samples == 2
    assert fan_in.pending == {}


def test_sample_timestamp_is_the_rpr_edge_time_base():
    assert sample_timestamp(0) == 0.0
    assert sample_timestamp(1) == pytest.approx(0.1)
    assert sample_timestamp(25, 0.04) == pytest.approx(1.0)
    assert sample_timestamp(3, sample_period_s=0.5) == pytest.approx(1.5)

    clock = _Clock()
    flushed: list[list[str]] = []
    fan_in = SampleFanIn(["a"], flushed.append, sample_period_s=0.04, clock=clock)
    fan_in.observe("a", "a0")
    fan_in.observe("a", "a1")

    assert fan_in.flushed_ordinals == [
        sample_timestamp(0, 0.04),
        sample_timestamp(1, 0.04),
    ]
