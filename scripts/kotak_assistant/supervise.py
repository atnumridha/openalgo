"""Foreground launchd service for the local Kotak terminal. Never places orders."""

import argparse
import os
import socket
import time
from pathlib import Path


def server_command(root, port):
    root = Path(root).resolve()
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    python = root / ".venv/bin/python"
    hooks = root / "install/lib/gunicorn_hooks.py"
    if not python.is_file() or not (root / "app.py").is_file() or not hooks.is_file():
        raise ValueError("OpenAlgo checkout, Python runtime or gunicorn hooks are missing")
    return [
        str(python),
        "-m",
        "gunicorn",
        "--config",
        str(hooks),
        "--worker-class",
        "gthread",
        "--threads",
        "64",
        "--workers",
        "1",
        "--bind",
        f"127.0.0.1:{port}",
        "--timeout",
        "120",
        "--graceful-timeout",
        "20",
        "--pid",
        str(root / "runtime/neo_desk/native-server.pid"),
        "app:app",
    ]


def listening(port):
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    cmd = server_command(args.root, args.port)
    if args.check:
        print("Local terminal startup configuration valid")
        return
    if listening(args.port):
        print(
            "Existing local terminal detected; waiting without starting a second server", flush=True
        )
        while listening(args.port):
            time.sleep(2)
    root = args.root.resolve()
    (root / "runtime/neo_desk").mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get(
        "PATH", "/usr/bin:/bin"
    )
    print("Starting local terminal; saved trades will reconcile with the broker", flush=True)
    os.execv(cmd[0], cmd)


if __name__ == "__main__":
    main()
