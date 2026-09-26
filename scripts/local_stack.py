#!/usr/bin/env python3
"""Own the local OpenAlgo app and offline research worker (macOS/Linux).

Start is idempotent; Stop only signals a verified supervisor from this checkout.
No application imports, broker requests, shell-sourced secrets or global pkill.
"""

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".local-stack"
STATE = RUNTIME / "state.json"
LOGS = ROOT / "log/local-stack"
START_TIMEOUT = 600
WEB_TIMEOUT = 180
STOP_TIMEOUT = 30
WORKER_TIMEOUT = 60
LOG_LIMIT = 10 * 1024 * 1024


class StartupError(Exception):
    pass


def dependencies():
    if sys.version_info < (3, 12):  # noqa: UP036 -- diagnose an old local interpreter
        raise StartupError("Python 3.12 or newer is required. Run uv sync --frozen in this folder.")
    try:
        import psutil
        from dotenv import dotenv_values
    except ImportError as error:
        raise StartupError(
            "Python dependencies are missing. Run uv sync --frozen in this folder."
        ) from error
    return psutil, dotenv_values


def configuration():
    _, dotenv_values = dependencies()
    if not (ROOT / ".env").is_file():
        raise StartupError("Missing .env. Complete the installation configuration before starting.")
    # dotenv parses data; shell commands in a value are never executed.
    values = {
        key: value for key, value in dotenv_values(ROOT / ".env").items() if value is not None
    }
    env = {**os.environ, **values, "PYTHONUNBUFFERED": "1", "OPENALGO_LOCAL_STARTUP": "1"}
    for key in ("APP_KEY", "API_KEY_PEPPER"):
        value = env.get(key, "")
        if len(value) < 32 or "PLACEHOLDER" in value:
            raise StartupError(
                f"Configure a valid {key} in .env. Existing installation secrets must be preserved."
            )
    if env.get("FLASK_DEBUG", "False").lower() in {"true", "1", "t"}:
        raise StartupError(
            "Set FLASK_DEBUG=False in .env for one-click startup (no duplicate reloader processes)."
        )
    if env.get("FLASK_HOST_IP", "127.0.0.1") not in {"127.0.0.1", "localhost", "::1"}:
        raise StartupError(
            "Local desktop startup requires a loopback FLASK_HOST_IP. Use the existing server launcher for a public or LAN bind."
        )
    if env.get("APP_MODE", "").strip("'\"") == "standalone" or Path("/.dockerenv").exists():
        raise StartupError(
            "This launcher is for local integrated mode. Use the existing Docker/server launcher for standalone mode."
        )
    ports = []
    for label, host_key, port_key, default in (
        ("web", "FLASK_HOST_IP", "FLASK_PORT", 5000),
        ("WebSocket", "WEBSOCKET_HOST", "WEBSOCKET_PORT", 8765),
        ("ZeroMQ", "ZMQ_HOST", "ZMQ_PORT", 5555),
    ):
        host = env.get(host_key, "127.0.0.1")
        if host not in {"127.0.0.1", "localhost", "0.0.0.0", "::", "::1"}:
            raise StartupError(
                f"{host_key} must be a local or wildcard bind address for this launcher."
            )
        try:
            port = int(env.get(port_key, str(default)))
            if not 1 <= port <= 65535:
                raise ValueError()
        except ValueError as error:
            raise StartupError(f"{port_key} must be a port number from 1 to 65535.") from error
        ports.append((label, host, port))
    if len({port for _, _, port in ports}) != 3:
        raise StartupError("Web, WebSocket and ZeroMQ must have different port numbers.")
    local_host = "[::1]" if ports[0][1] in {"::", "::1"} else "127.0.0.1"
    return env, ports, f"http://{local_host}:{ports[0][2]}"


def preflight():
    for relative, remedy in (
        (".venv/bin/python", "Run uv sync --frozen to prepare the Python environment."),
        ("app.py", "Open the launchers in a complete OpenAlgo checkout."),
        ("upgrade/migrate_all.py", "Restore the required database migration scripts."),
        ("services/research/worker.py", "Restore the research worker."),
        ("frontend/dist/index.html", "Build the frontend: cd frontend && npm ci && npm run build"),
    ):
        if not (ROOT / relative).is_file():
            raise StartupError(f"Missing {relative}. {remedy}")
    return configuration()


def ensure_ports_free(ports):
    for label, host, port in ports:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(family) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError as error:
                raise StartupError(
                    f"{label} port {port} is unavailable. An existing service was left untouched; use its own launcher to stop it."
                ) from error


def read_state():
    try:
        if STATE.stat().st_size > 65536:
            raise StartupError("The local startup state is invalid; no processes were signalled.")
        value = json.loads(STATE.read_text())
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as error:
        raise StartupError(
            "Cannot read the local startup state. Inspect .local-stack/state.json; no processes were signalled."
        ) from error


def write_state(value):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(STATE)


def process_record(process, command):
    psutil, _ = dependencies()
    return {
        "pid": process.pid,
        "created": psutil.Process(process.pid).create_time(),
        "command": command,
    }


def recorded_process(record):
    psutil, _ = dependencies()
    try:
        process = psutil.Process(int(record["pid"]))
        if process.status() == psutil.STATUS_ZOMBIE:
            return None
        if abs(process.create_time() - float(record["created"])) > 0.01:
            raise StartupError("A saved PID belongs to a different process. Refusing to signal it.")
        return process
    except (psutil.NoSuchProcess, KeyError):
        return None
    except (psutil.AccessDenied, ValueError, TypeError) as error:
        raise StartupError(
            "Cannot verify the saved process identity. No process was signalled."
        ) from error


def supervisor(value):
    if not value:
        return None
    process = recorded_process(value)
    if process is None:
        return None
    psutil, _ = dependencies()
    try:
        expected = [str(ROOT / "scripts/local_stack.py"), "_run", value.get("token")]
        if value.get("root") != str(ROOT) or process.cmdline()[1:] != expected:
            raise StartupError(
                "The saved process is not this checkout's supervisor. Refusing to signal it."
            )
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return None
    except psutil.AccessDenied as error:
        raise StartupError(
            "Cannot verify supervisor ownership. No process was signalled."
        ) from error
    return process


@contextmanager
def lock(name):
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    with (RUNTIME / name).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise StartupError(
                "Another startup is already in progress. Use Status to see its progress."
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def healthy(url):
    try:
        # Loopback readiness must not be routed through an inherited HTTP proxy.
        with build_opener(ProxyHandler({})).open(url + "/health/status", timeout=2) as response:
            data = json.loads(response.read(8192))
            return (
                response.status == 200
                and data.get("serviceId") == "openalgo"
                and data.get("status") in {"pass", "warn"}
            )
    except (URLError, OSError, ValueError, AttributeError):
        return False


def listeners_ready(ports):
    for _, host, port in ports:
        host = "::1" if host in {"::", "::1"} else "127.0.0.1"
        try:
            with socket.create_connection((host, port), timeout=0.5):
                pass
        except OSError:
            return False
    return True


def rotate_log(filename):
    """Keep the latest bounded segment; truncate the same inode children hold."""
    if not filename.exists() or filename.stat().st_size <= LOG_LIMIT:
        return
    with filename.open("rb") as source, filename.with_suffix(".previous.log").open("wb") as backup:
        source.seek(-LOG_LIMIT, os.SEEK_END)
        remaining = LOG_LIMIT
        while remaining:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            backup.write(chunk)
            remaining -= len(chunk)
    with filename.open("r+b") as current:
        current.truncate(0)


def launch(command, name, env):
    LOGS.mkdir(mode=0o700, parents=True, exist_ok=True)
    logfile = LOGS / f"{name}.log"
    rotate_log(logfile)
    with logfile.open("ab") as output:
        return subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def cleanup(children):
    # Keep ownership through Popen objects; never infer children from port numbers.
    for process in reversed(list(children.values())):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + STOP_TIMEOUT
    for process in reversed(list(children.values())):
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def serve(token):
    psutil, _ = dependencies()
    with lock("supervisor.lock"):
        stopping = False
        children = {}
        value = {
            "pid": os.getpid(),
            "created": psutil.Process().create_time(),
            "root": str(ROOT),
            "token": token,
            "status": "starting",
            "message": "Preparing startup",
            "services": {},
        }

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        def update(status, message):
            value.update(status=status, message=message)
            write_state(value)
            print(message, flush=True)

        def spawn(name, command, env):
            children[name] = launch(command, name, env)
            value["services"][name] = process_record(children[name], command)
            write_state(value)
            return children[name]

        try:
            env, ports, url = preflight()
            value["url"] = url
            value["ports"] = ports
            ensure_ports_free(ports)
            update("starting", "Applying database migrations")
            python = str(ROOT / ".venv/bin/python")
            migration = spawn("migrations", [python, str(ROOT / "upgrade/migrate_all.py")], env)
            deadline = time.monotonic() + START_TIMEOUT
            while migration.poll() is None and not stopping:
                if time.monotonic() >= deadline:
                    raise StartupError("Database migrations timed out. Check migrations.log.")
                rotate_log(LOGS / "migrations.log")
                time.sleep(0.25)
            if stopping:
                return
            if migration.wait() != 0:
                raise StartupError(
                    "Database migrations failed. Check migrations.log; the app was not started."
                )
            del children["migrations"]
            value["services"].pop("migrations")
            ensure_ports_free(ports)
            update("starting", "Starting app, WebSocket proxy and risk runtime")
            app = spawn("app", [python, str(ROOT / "app.py")], configuration()[0])
            deadline = time.monotonic() + WEB_TIMEOUT
            while not stopping:
                if app.poll() is not None:
                    raise StartupError("The app exited during startup. Check app.log.")
                if healthy(url) and listeners_ready(ports):
                    break
                if time.monotonic() >= deadline:
                    raise StartupError(
                        "App readiness timed out. Check app.log and the configured ports."
                    )
                rotate_log(LOGS / "app.log")
                time.sleep(0.5)
            if stopping:
                return
            update("starting", "Starting offline research worker")
            ready_file = RUNTIME / "research-ready.json"
            ready_file.unlink(missing_ok=True)
            worker = spawn(
                "research",
                [python, "-m", "services.research.worker", "--ready-file", str(ready_file)],
                configuration()[0],
            )
            deadline = time.monotonic() + WORKER_TIMEOUT
            worker_ready = False
            while time.monotonic() < deadline and not stopping and worker.poll() is None:
                try:
                    worker_ready = json.loads(ready_file.read_text()).get("pid") == worker.pid
                except (OSError, ValueError, AttributeError):
                    pass
                if worker_ready:
                    break
                time.sleep(0.1)
            last_status = None
            while not stopping:
                if app.poll() is not None:
                    raise StartupError(
                        "The app stopped. Check app.log; automatic trading restarts are disabled."
                    )
                if not worker_ready and worker.poll() is None:
                    try:
                        worker_ready = json.loads(ready_file.read_text()).get("pid") == worker.pid
                    except (OSError, ValueError, AttributeError):
                        pass
                status = "ready" if worker.poll() is None and worker_ready else "degraded"
                if status != last_status:
                    update(
                        status,
                        "OpenAlgo and the research worker are ready"
                        if status == "ready"
                        else "Research worker is not ready; the app remains running. Check research.log.",
                    )
                    last_status = status
                for name in ("app", "research", "supervisor"):
                    rotate_log(LOGS / f"{name}.log")
                time.sleep(0.5)
        except Exception as error:
            # Never include environment values or a credential-bearing exception.
            message = (
                str(error)
                if isinstance(error, StartupError)
                else f"Startup failed ({type(error).__name__}). Check the service logs."
            )
            update("failed", message)
        finally:
            failed = value["status"] == "failed"
            try:
                if not failed:
                    update("stopping", "Stopping the processes owned by this launcher")
            finally:
                # A full disk or removed state directory must never skip reaping.
                try:
                    cleanup(children)
                finally:
                    (RUNTIME / "research-ready.json").unlink(missing_ok=True)
            if not failed:
                update("stopped", "OpenAlgo local services stopped")


def start(no_browser):
    with lock("start.lock"):
        old = read_state()
        if supervisor(old):
            print_status(old)
            if stack_ready(old):
                if not no_browser:
                    webbrowser.open(old["url"] + "/strategy/research")
                return 0
            raise StartupError(
                "The existing stack is starting, stopping or degraded. Check Status and the logs; no second stack was started."
            )
        if any(recorded_process(record) for record in old.get("services", {}).values()):
            raise StartupError(
                "An earlier launcher left a running service. Inspect Status before starting; no process was killed."
            )
        env, ports, _ = preflight()
        ensure_ports_free(ports)
        token = uuid.uuid4().hex
        command = [
            str(ROOT / ".venv/bin/python"),
            str(ROOT / "scripts/local_stack.py"),
            "_run",
            token,
        ]
        child = launch(command, "supervisor", env)
        deadline = time.monotonic() + START_TIMEOUT + WEB_TIMEOUT + WORKER_TIMEOUT + 15
        last_message = None
        while time.monotonic() < deadline:
            value = read_state()
            if value.get("token") == token:
                if value.get("message") != last_message:
                    print(value["message"], flush=True)
                    last_message = value["message"]
                if value.get("status") == "ready" and stack_ready(value):
                    print(f"Open: {value['url']}/strategy/research\nLogs: {LOGS}")
                    if not no_browser:
                        webbrowser.open(value["url"] + "/strategy/research")
                    return 0
                if value.get("status") in {"failed", "degraded", "stopped"}:
                    print(f"Logs: {LOGS}")
                    return 1
            if child.poll() is not None:
                raise StartupError(f"Startup supervisor exited. Check {LOGS / 'supervisor.log'}.")
            time.sleep(0.25)
        raise StartupError(
            "Startup is taking longer than expected. Use Status; no second stack was started."
        )


def print_status(value):
    print(
        f"State: {value.get('status', 'stopped')} — {value.get('message', 'No managed local stack')}"
    )
    for name, record in value.get("services", {}).items():
        print(
            f"  {name}: {'running' if recorded_process(record) else 'stopped'} (PID {record['pid']})"
        )
    if value.get("url"):
        print(f"Dashboard: {value['url']}/strategy/research")
    print(f"Logs: {LOGS}")


def status():
    value = read_state()
    owner = supervisor(value)
    print_status(value)
    if not owner:
        print("No verified startup supervisor is running.")
        return 1
    ready = stack_ready(value)
    if not ready:
        print("The stack is not fully ready; see the status and logs above.")
    return 0 if ready else 1


def stack_ready(value):
    return (
        value.get("status") == "ready"
        and {"app", "research"}.issubset(value.get("services", {}))
        and all(recorded_process(r) for r in value.get("services", {}).values())
        and healthy(value["url"])
        and listeners_ready(value["ports"])
    )


def stop():
    value = read_state()
    process = supervisor(value)
    if process is None:
        if any(recorded_process(record) for record in value.get("services", {}).values()):
            raise StartupError(
                "The supervisor is unavailable but an earlier service remains. Refusing to signal an unowned process; inspect the saved PIDs."
            )
        print("OpenAlgo is already stopped (no owned local processes).")
        return 0
    process.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + STOP_TIMEOUT + 10
    while time.monotonic() < deadline:
        if supervisor(value) is None:
            print("OpenAlgo local services stopped.")
            return 0
        time.sleep(0.2)
    raise StartupError(
        "Shutdown is still in progress. Inspect Status and supervisor.log before restarting."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "check", "_run"))
    parser.add_argument("token", nargs="?")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        dependencies()
        if args.action == "_run":
            if not args.token or len(args.token) != 32:
                raise StartupError("The startup supervisor must be launched with Start.")
            serve(args.token)
            return 0
        if args.action == "start":
            return start(args.no_browser)
        if args.action == "stop":
            return stop()
        if args.action == "status":
            return status()
        _, ports, url = preflight()
        if supervisor(read_state()):
            return status()
        ensure_ports_free(ports)
        print(
            f"Startup checks passed. Dashboard: {url}/strategy/research\nNo services or migrations were started."
        )
        return 0
    except (StartupError, OSError) as error:
        print(f"OpenAlgo: {error}")
        return 1
    except KeyboardInterrupt:
        print("Startup wait interrupted. Use Status or Stop to manage any started services.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
