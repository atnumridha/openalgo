"""Run local launchers against disposable programs, never the trading app."""

import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

SOURCE = Path(__file__).resolve().parents[1]


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "Trading App With Spaces"
    for folder in (
        "scripts",
        "utils",
        ".venv/bin",
        "frontend/dist",
        "upgrade",
        "services/research",
    ):
        (root / folder).mkdir(parents=True)
    # Copy the actual launcher; only the application/worker are test doubles.
    launcher = SOURCE / "scripts/local_stack.py"
    assert launcher.exists(), "The local startup supervisor has not been implemented"
    shutil.copy(launcher, root / "scripts/local_stack.py")
    if (SOURCE / "utils/local_startup.py").exists():
        shutil.copy(SOURCE / "utils/local_startup.py", root / "utils/local_startup.py")
    # A relocated symlink loses the real virtualenv's pyvenv.cfg discovery.
    # Exec the installed interpreter at its original path, retaining dependencies.
    python = root / ".venv/bin/python"
    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    python.chmod(0o700)
    (root / "frontend/dist/index.html").write_text("built UI")
    ports = []
    listeners = []
    try:
        for _ in range(3):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            listeners.append(sock)
            ports.append(sock.getsockname()[1])
    finally:
        for sock in listeners:
            sock.close()
    (root / ".env").write_text(
        f"APP_KEY={'a' * 64}\nAPI_KEY_PEPPER={'b' * 64}\nFLASK_DEBUG=False\n"
        f"FLASK_PORT={ports[0]}\nWEBSOCKET_PORT={ports[1]}\nZMQ_PORT={ports[2]}\n"
        "FLASK_HOST_IP=127.0.0.1\nWEBSOCKET_HOST=127.0.0.1\nZMQ_HOST=127.0.0.1\n"
        "LAUNCH_TEST_VALUE=from dotenv\n"
    )
    (root / "upgrade/migrate_all.py").write_text(
        "import os, pathlib, sys\n"
        "p=pathlib.Path('migrations-ran'); p.write_text(p.read_text()+'x' if p.exists() else 'x')\n"
        "sys.exit(1 if pathlib.Path('fail-migration').exists() else 0)\n"
    )
    (root / "app.py").write_text("""
import os, pathlib, socket
from flask import Flask
from flask_socketio import SocketIO
from utils.local_startup import local_server_options
assert pathlib.Path('migrations-ran').exists()
pathlib.Path('app-env').write_text(os.environ['LAUNCH_TEST_VALUE'])
listeners=[]
for name in ['WEBSOCKET_PORT', 'ZMQ_PORT']:
    sock=socket.socket(); sock.bind(('127.0.0.1',int(os.environ[name]))); sock.listen()
    listeners.append(sock)
app=Flask(__name__)
app.add_url_rule('/health/status',view_func=lambda:{'serviceId':'openalgo','status':'pass'})
SocketIO(app,async_mode='threading').run(app,host='127.0.0.1',port=int(os.environ['FLASK_PORT']),
    **local_server_options('127.0.0.1',False,os.environ.get('OPENALGO_LOCAL_STARTUP')))
""")
    (root / "services/research/worker.py").write_text("""
import json, os, pathlib, signal, sys, time
pathlib.Path('worker-env').write_text(os.environ['LAUNCH_TEST_VALUE'])
signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))
if pathlib.Path('fail-worker').exists(): sys.exit(1)
ready=pathlib.Path(sys.argv[sys.argv.index('--ready-file')+1])
ready.write_text(json.dumps({'pid':os.getpid()}))
while True: time.sleep(.1)
""")
    yield root, ports
    run(root, "stop", timeout=50)


def run(root, action, *, timeout=25):
    return subprocess.run(
        [sys.executable, str(root / "scripts/local_stack.py"), action, "--no-browser"],
        cwd=root.parent,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "LAUNCH_TEST_VALUE": "wrong inherited value"},
    )


def state(root):
    return json.loads((root / ".local-stack/state.json").read_text())


def test_start_from_another_directory_is_ready_once_and_stop_reaps_owned_services(installation):
    root, _ = installation
    original_env = (root / ".env").read_bytes()
    first = run(root, "start")
    assert first.returncode == 0, first.stdout + first.stderr
    before = state(root)
    assert before["status"] == "ready"
    assert (root / "worker-env").read_text() == "from dotenv"
    assert (root / "app-env").read_text() == "from dotenv"
    second = run(root, "start")
    assert second.returncode == 0, second.stdout + second.stderr
    assert state(root)["pid"] == before["pid"]
    assert (root / "migrations-ran").read_text() == "x"
    assert run(root, "status").returncode == 0
    assert run(root, "stop").returncode == 0
    assert state(root)["status"] == "stopped"
    assert (root / ".env").read_bytes() == original_env
    for child in before["services"].values():
        assert not psutil.pid_exists(child["pid"])


def test_port_conflict_never_migrates_or_kills_the_existing_listener(installation):
    root, ports = installation
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", ports[0]))
        occupied.listen()
        result = run(root, "start")
        assert result.returncode != 0
        assert "port" in result.stdout.lower()
        assert not (root / "migrations-ran").exists()
        assert occupied.getsockname()[1] == ports[0]


def test_migration_failure_does_not_start_app_or_worker(installation):
    root, _ = installation
    (root / "fail-migration").touch()
    result = run(root, "start")
    assert result.returncode != 0
    assert "migration" in result.stdout.lower()
    assert not (root / "app-env").exists()
    assert not (root / "worker-env").exists()


def test_worker_failure_reports_degraded_and_keeps_web_risk_runtime_alive(installation):
    root, _ = installation
    (root / "fail-worker").touch()
    result = run(root, "start")
    assert result.returncode != 0
    snapshot = state(root)
    assert snapshot["status"] == "degraded"
    assert psutil.pid_exists(snapshot["services"]["app"]["pid"])
    assert run(root, "status").returncode != 0
    assert run(root, "stop").returncode == 0


def test_read_only_check_refuses_missing_build_and_debug_reloader(installation):
    root, _ = installation
    (root / "frontend/dist/index.html").unlink()
    result = run(root, "check")
    assert result.returncode != 0 and "frontend" in result.stdout.lower()
    assert not (root / "migrations-ran").exists()
    assert not (root / ".local-stack").exists()
    (root / "frontend/dist/index.html").write_text("UI")
    with (root / ".env").open("a") as env:
        env.write("FLASK_DEBUG=True\n")
    result = run(root, "check")
    assert result.returncode != 0 and "FLASK_DEBUG" in result.stdout


def test_local_server_permission_cannot_be_used_for_external_bind_or_debug():
    from utils.local_startup import local_server_options

    assert local_server_options("127.0.0.1", False, None) == {}
    assert local_server_options("127.0.0.1", False, "1")["allow_unsafe_werkzeug"]
    for host, debug in (("0.0.0.0", False), ("::", False), ("127.0.0.1", True)):
        with pytest.raises(ValueError):
            local_server_options(host, debug, "1")


def test_stop_refuses_forged_state_pointing_at_an_unrelated_process(installation):
    root, _ = installation
    runtime = root / ".local-stack"
    runtime.mkdir()
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (runtime / "state.json").write_text(
            json.dumps(
                {
                    "pid": unrelated.pid,
                    "created": psutil.Process(unrelated.pid).create_time(),
                    "token": "forged",
                    "root": str(root),
                    "status": "ready",
                    "services": {},
                }
            )
        )
        assert run(root, "stop").returncode != 0
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_simultaneous_starts_do_not_duplicate_the_stack(installation):
    root, _ = installation
    command = [sys.executable, str(root / "scripts/local_stack.py"), "start", "--no-browser"]
    with (root / "first-start-output").open("w") as output:
        first = subprocess.Popen(command, cwd=root.parent, stdout=output, stderr=output)
        try:
            second = run(root, "start")
            assert first.wait(timeout=25) in (0, 1)
            # Either contender can win, but exactly one migration/start occurs.
            assert second.returncode in (0, 1)
            assert (root / "migrations-ran").read_text() == "x"
            assert state(root)["status"] == "ready"
        finally:
            if first.poll() is None:
                first.terminate()
                first.wait(timeout=5)


def test_finder_command_works_with_spaces_and_does_not_depend_on_terminal_cwd(installation):
    root, _ = installation
    shutil.copy(SOURCE / "Check OpenAlgo.command", root / "Check OpenAlgo.command")
    shutil.copy(SOURCE / "scripts/local-stack.sh", root / "scripts/local-stack.sh")
    result = subprocess.run(
        ["/bin/bash", str(root / "Check OpenAlgo.command"), "--no-browser"],
        cwd=root.parent,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No services or migrations" in result.stdout
    assert not (root / "migrations-ran").exists()


def test_app_failure_stops_its_research_worker_without_automatic_restart(installation):
    root, _ = installation
    assert run(root, "start").returncode == 0
    running = state(root)
    psutil.Process(running["services"]["app"]["pid"]).terminate()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if state(root)["status"] == "failed" and not psutil.pid_exists(
            running["services"]["research"]["pid"]
        ):
            break
        time.sleep(0.1)
    assert state(root)["status"] == "failed"
    assert not psutil.pid_exists(running["services"]["research"]["pid"])
    assert (root / "migrations-ran").read_text() == "x"


def test_log_rotation_preserves_child_file_descriptor_and_caps_history(tmp_path, monkeypatch):
    from scripts import local_stack

    monkeypatch.setattr(local_stack, "LOG_LIMIT", 100)
    filename = tmp_path / "app.log"
    with filename.open("ab", buffering=0) as child_output:
        child_output.write(b"a" * 200)
        local_stack.rotate_log(filename)
        child_output.write(b"still logging")
    assert filename.read_bytes() == b"still logging"
    assert filename.with_suffix(".previous.log").read_bytes() == b"a" * 100


def test_shutdown_reaps_children_even_when_status_cannot_be_written(tmp_path, monkeypatch):
    from scripts import local_stack

    handlers = {}
    cleaned = []
    monkeypatch.setattr(local_stack, "RUNTIME", tmp_path)
    monkeypatch.setattr(
        local_stack.signal, "signal", lambda sig, handler: handlers.update({sig: handler})
    )
    monkeypatch.setattr(local_stack, "preflight", lambda: ({}, [], "http://127.0.0.1:5000"))
    monkeypatch.setattr(local_stack, "ensure_ports_free", lambda ports: None)

    class StoppingMigration:
        def poll(self):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            return None

    child = StoppingMigration()
    monkeypatch.setattr(local_stack, "launch", lambda *args: child)
    monkeypatch.setattr(local_stack, "process_record", lambda *args: {})
    monkeypatch.setattr(local_stack, "cleanup", lambda children: cleaned.extend(children.values()))

    def write_state(value):
        if value["status"] == "stopping":
            raise OSError("Disk full")

    monkeypatch.setattr(local_stack, "write_state", write_state)
    with pytest.raises(OSError, match="Disk full"):
        local_stack.serve("a" * 32)
    assert cleaned == [child]
