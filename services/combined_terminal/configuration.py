"""Private on-host configuration. No secrets or registry paths enter API responses."""
import json
import os
from pathlib import Path
import stat

from .contracts import ConnectionRef
from .registry import Registry,WorkerConfig


def private_bytes(path):
    path=Path(path)
    if not path.is_absolute():raise ValueError('Configuration requires an absolute private file')
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:
                raise ValueError('Configuration must be a private owner-only file')
            if info.st_size>1048576:raise ValueError('Private configuration too large')
            return stream.read()
    except OSError:raise ValueError('Private configuration unavailable') from None


def document(path):
    try:
        value=json.loads(private_bytes(path))
        if not isinstance(value,dict):raise ValueError()
        return value
    except (TypeError,json.JSONDecodeError):raise ValueError('Invalid private configuration') from None


def absolute_db(value):
    if not isinstance(value,str) or not Path(value).is_absolute() or Path(value).is_symlink():raise ValueError('An absolute local database path is required')
    return Path(value).resolve()


def load_registry(path):
    config=document(path)
    workers=[WorkerConfig(ConnectionRef(**w['connection']),w['url'],private_bytes(w['secret_file']).strip()) for w in config['workers']]
    if not workers:raise ValueError('No broker workers configured')
    return Registry(workers),absolute_db(config['ledger_path'])


def configured_runtime():
    from sqlalchemy import create_engine
    from .ledger import Ledger
    from .runtime import Runtime
    from .transport import Transport
    registry,path=load_registry(os.environ.get('COMBINED_TERMINAL_CONFIG',''))
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    return Runtime(registry,Ledger(create_engine('sqlite:///'+str(path)),[w.connection for w in registry._workers.values()]),Transport(registry))
