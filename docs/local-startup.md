# One-click local startup

On macOS, open the `openalgo` folder in Finder and double-click **Start OpenAlgo.command**. It opens a Terminal window, checks the installation, applies database migrations, starts the app and research worker, waits for readiness, and opens the Strategy Research page in your default browser. Sign in through the normal OpenAlgo login page when required.

| Launcher | Action |
| --- | --- |
| `Start OpenAlgo.command` | Start the local stack, or open the existing healthy stack. |
| `OpenAlgo Status.command` | Show process status, check app health and listeners, and display the dashboard and log locations. |
| `Check OpenAlgo.command` | Check configuration, required files and ports without starting services or running migrations. If this launcher already owns a running stack, show its status. |
| `Stop OpenAlgo.command` | Gracefully stop the services owned by this checkout's launcher. |

After Start reports ready, you can close its Terminal window. The background supervisor keeps the services running. Clicking Start again does not start duplicate services. These scripts find their installation directory automatically, including paths containing spaces.

**Stop is an application shutdown, not a broker square-off.** It stops local strategy and risk monitoring along with the app. Manage any open broker positions before shutting down. Startup follows the app's existing configuration, including resuming previously enabled workflows. The launchers do not grant live-release approval or alter capital limits, strategy rules, broker credentials or live-trading flags.

## Installation requirements

The launchers use the existing `.env`, `.venv/bin/python`, and `frontend/dist` build. They do not install packages, rebuild the UI or replace secrets on each click.

- Configure `.env` through the normal installation procedure. Preserve `APP_KEY` and `API_KEY_PEPPER` when upgrading an existing installation.
- Set `FLASK_HOST_IP=127.0.0.1` and `FLASK_DEBUG=False`. Desktop startup is restricted to loopback with no debug reloader. `localhost` and `::1` are also supported.
- Prepare missing Python dependencies with `uv sync --frozen` in the `openalgo` directory.
- If the frontend build is missing, run `npm ci` followed by `npm run build` in the `frontend` directory.
- Stop a previously launched app using its own launcher before switching to these scripts. Port conflicts are reported; unrelated processes are never killed.

The web, WebSocket and ZeroMQ ports come from `.env` (`FLASK_PORT`, `WEBSOCKET_PORT`, `ZMQ_PORT`). They must be distinct. The scripts print and open the configured web port, rather than assuming port 5000. `APP_MODE=standalone` and Docker environments use the existing server/Docker startup path, including `start.sh`.

The one-click supervisor is a macOS/Linux local tool. The `.command` files are Finder entry points on macOS. Windows is not supported by this supervisor.

## Terminal use

From the `openalgo` directory:

```sh
./scripts/local-stack.sh check
./scripts/local-stack.sh start --no-browser
./scripts/local-stack.sh status
./scripts/local-stack.sh stop
```

Omit `--no-browser` to open the dashboard automatically. The shell wrapper waits for Return when run in an interactive terminal so Finder errors stay visible. For scripts or an existing terminal where that pause is unwanted:

```sh
OPENALGO_NO_PAUSE=1 ./scripts/local-stack.sh start --no-browser
```

## Readiness and failures

Start runs `upgrade/migrate_all.py` before the app, with a ten-minute migration limit. A failed migration prevents app and worker startup. Normal app startup performs its existing database initialization and starts its integrated WebSocket, ZeroMQ and risk services.

The supervisor allows three minutes for the app's `/health/status` response and all three configured listeners, then one minute for the research worker to acknowledge that it holds the database worker lease. Health `pass` or `warn` indicates app availability; it does not prove broker connectivity, market-data quality, research profitability or live-trading eligibility.

A failed research worker leaves the app and its risk runtime running and reports **degraded**. Inspect the logs before using Stop and Start to recover. If the app exits, the supervisor stops its research worker and records the failure. It never automatically restarts trading services after a crash.

Stop asks managed processes to shut down, allows up to 30 seconds for graceful exit, then terminates remaining owned process groups. A research job observes shutdown at its cancellation checkpoints and becomes `interrupted`; it is not automatically replayed. If forced termination is necessary, stale worker jobs are recovered as interrupted after lease expiry on a later worker start.

## Logs and state

Logs are under `log/local-stack/`:

- `migrations.log`: database upgrade output.
- `app.log`: app, integrated services and normal application startup output.
- `research.log`: offline worker output.
- `supervisor.log`: service lifecycle and supervisor errors.

The supervisor periodically rotates logs exceeding 10 MiB, retaining their last 10 MiB in a corresponding `.previous.log`. Active output continues through the same file descriptor. Application-managed logs outside this folder follow their existing retention settings.

PID records and locks live in the ignored `.local-stack/` directory. Stop verifies the supervisor's process identity and checkout before signalling it. If state is corrupt or the supervisor is missing while services remain, the launcher refuses to guess which process to kill. Inspect the reported PIDs and logs; do not delete state while services are running.

Closing the Start terminal after readiness is supported. Logging out, rebooting or putting the Mac to sleep is not a continuous-operation deployment: these scripts are manual startup controls, not a launch-at-login or sleep-prevention service.
