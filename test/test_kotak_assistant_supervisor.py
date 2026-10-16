import socket

import pytest

from scripts.kotak_assistant.supervise import listening, server_command


def test_service_uses_the_requested_checkout_and_binds_only_to_loopback(tmp_path):
    for name in (".venv/bin/python", "app.py", "install/lib/gunicorn_hooks.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    cmd = server_command(tmp_path, 5001)
    assert cmd[0] == str(tmp_path / ".venv/bin/python")
    assert cmd[cmd.index("--bind") + 1] == "127.0.0.1:5001"
    assert "--preload" not in cmd  # Do not import macOS libraries before fork.
    assert cmd[cmd.index("--pid") + 1] == str(tmp_path / "runtime/neo_desk/native-server.pid")
    with pytest.raises(ValueError):
        server_command(tmp_path, 99999)


def test_existing_listener_is_detected_to_prevent_a_duplicate_server():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        assert listening(listener.getsockname()[1])
