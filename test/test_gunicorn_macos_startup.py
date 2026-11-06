"""The launcher's real config must avoid a threaded arbiter on macOS."""

import runpy
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("platform, disabled", [("darwin", True), ("linux", False)])
def test_control_socket_is_disabled_only_for_macos_worker_fork_safety(
    monkeypatch, platform, disabled
):
    # The control thread is created after the first worker. Leaving it enabled
    # makes replacement workers crash when loading macOS-backed HTTP libraries.
    hooks = Path(__file__).resolve().parents[1] / "install/lib/gunicorn_hooks.py"
    monkeypatch.setattr(sys, "platform", platform)
    settings = runpy.run_path(str(hooks))
    assert settings.get("control_socket_disable", False) is disabled
