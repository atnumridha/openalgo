"""Private JSON-lines child using the scalper's own Python environment.

No shell, browser-provided paths, inherited broker secrets or automatic mutation
retries. A timed-out control may already have succeeded: reconcile status first.
The child exits on stdin EOF; the independently owned paper controller survives.
"""
import atexit
import json
import os
from pathlib import Path
import selectors
import subprocess
import threading
import time

class BridgeUnavailable(RuntimeError):
    pass

_LOCK = threading.Lock()
_PROCESS = None
_PARENT = None

def _close():
    global _PROCESS
    if _PROCESS is not None:
        try:
            _PROCESS.terminate()
            _PROCESS.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            _PROCESS.kill()
        for stream in (_PROCESS.stdin, _PROCESS.stdout):
            if stream: stream.close()
        _PROCESS = None

atexit.register(_close)

def _child():
    global _PROCESS, _PARENT
    if _PARENT != os.getpid():
        # A fork must not terminate its parent's helper.
        _PROCESS = None
        _PARENT = os.getpid()
    if _PROCESS is None or _PROCESS.poll() is not None:
        _close()
        install = Path(os.environ.get('DELTA_SCALPER_HOME', str(Path.home()/'.codex/skills/delta-scalper'))).expanduser()
        state = Path(os.environ.get('DELTA_SCALPER_STATE', str(Path.home()/'.local/state/delta-scalper'))).expanduser()
        python = install/'.venv/bin/python'
        if not python.is_file() or not (install/'scripts/scalper.py').is_file():
            raise BridgeUnavailable('Delta controller is not installed')
        env = {k: os.environ[k] for k in ('HOME','PATH','USER','LOGNAME','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR','CODEX_HOME') if k in os.environ}
        _PROCESS = subprocess.Popen([str(python),'-u',str(Path(__file__).resolve().parents[2]/'scripts/delta_desk/worker.py'),str(install),str(state)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,env=env,close_fds=True)
    return _PROCESS

def call(action, payload):
    if action not in {'status','observation','research','models','stream','control'}:
        raise ValueError('Unsupported action')
    if not _LOCK.acquire(timeout=2):
        raise BridgeUnavailable('Delta bridge is busy')
    try:
        process = _child()
        process.stdin.write((json.dumps({'action':action,'payload':payload},allow_nan=False)+'\n').encode())
        deadline = time.monotonic()+25
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            while b'\n' not in output:
                remaining=deadline-time.monotonic()
                if remaining<=0 or not selector.select(remaining):
                    raise BridgeUnavailable('Delta request timed out')
                chunk=os.read(process.stdout.fileno(),65536)
                if not chunk or len(output)+len(chunk)>8_000_000:
                    raise BridgeUnavailable('Invalid Delta response')
                output.extend(chunk)
        result=json.loads(output)
        if not result.get('ok'):
            if result.get('validation'): raise ValueError(result['error'])
            raise BridgeUnavailable('Delta controller unavailable')
        return result['data']
    except ValueError:
        raise
    except Exception as exc:
        _close()
        raise BridgeUnavailable('Delta bridge unavailable') from exc
    finally:
        _LOCK.release()
