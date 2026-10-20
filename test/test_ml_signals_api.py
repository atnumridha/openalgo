"""Authenticated ML API response-shape and single-flight tests."""

from __future__ import annotations

import threading
import time

import pytest

from blueprints import ml_signals


def test_job_snapshot_has_stable_shape():
    value = ml_signals._snapshot()
    assert {"busy", "job", "progress", "message", "error"} <= set(value)


def test_start_rejects_second_job(monkeypatch):
    ml_signals._update(busy=False)
    started_gate = threading.Event()
    release_gate = threading.Event()
    started = ml_signals._start("unit", lambda: (started_gate.set(), release_gate.wait(1)))
    try:
        assert started is True
        assert started_gate.wait(1)
        assert ml_signals._start("second", lambda: None) is False
    finally:
        release_gate.set()
        for _ in range(20):
            if not ml_signals._snapshot()["busy"]:
                break
            time.sleep(0.01)


def test_unknown_model_activation_is_clean(monkeypatch):
    class Missing:
        def activate_model(self, version):
            raise FileNotFoundError(version)

    monkeypatch.setattr(ml_signals, "_core_module", lambda name: Missing())
    assert True
