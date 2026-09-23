"""Session-scoped authorization for automated live entries."""

from __future__ import annotations

from dataclasses import dataclass

from services.strategy_module.session import session_reset_time
from utils.real_threading import Lock
from utils.session import get_trading_session_date


@dataclass(frozen=True, slots=True)
class LiveAuthorization:
    active: bool
    session_day: str
    expires_at: str


_authorizations: dict[str, LiveAuthorization] = {}
_lock = Lock()
_DENIED_MESSAGE = "Live automation is not authorized for this trading session"


def _inactive(session_day: str) -> LiveAuthorization:
    return LiveAuthorization(
        active=False,
        session_day=session_day,
        expires_at=session_reset_time().isoformat(timespec="minutes"),
    )


def grant(user_id: str) -> LiveAuthorization:
    """Authorize one username to open automated live entries this session."""
    session_day = get_trading_session_date()
    authorization = LiveAuthorization(
        active=True,
        session_day=session_day,
        expires_at=session_reset_time().isoformat(timespec="minutes"),
    )
    with _lock:
        _authorizations[str(user_id)] = authorization
    return authorization


def revoke(user_id: str) -> None:
    """Block new automated live entries for one username immediately."""
    with _lock:
        _authorizations.pop(str(user_id), None)


def status(user_id: str) -> LiveAuthorization:
    """Return current authorization, invalidating a prior-session grant."""
    session_day = get_trading_session_date()
    username = str(user_id)
    with _lock:
        authorization = _authorizations.get(username)
        if authorization is not None and authorization.session_day == session_day:
            return authorization
        if authorization is not None:
            _authorizations.pop(username, None)
    return _inactive(session_day)


def require_live_entry(user_id: str) -> tuple[bool, str | None]:
    """Say whether a new automated live entry may be claimed."""
    current = status(user_id)
    if current.active:
        return True, None
    return False, _DENIED_MESSAGE
