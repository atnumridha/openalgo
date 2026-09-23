"""Session-scoped authorization for automated live entries."""

from __future__ import annotations

from dataclasses import dataclass

from services.strategy_module.session import session_reset_time
from utils.logging import get_logger
from utils.real_threading import Lock
from utils.session import get_trading_session_date

logger = get_logger(__name__)


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


def _notify_transition(user_id: str, kind: str, message: str) -> None:
    """Best-effort account lifecycle delivery, always outside ``_lock``."""
    try:
        from services.strategy_module.lifecycle_events import record_user_and_notify

        record_user_and_notify(str(user_id), kind, message)
    except Exception:
        # Authorization state is the authority. Losing an audit sink or alert
        # must not roll back a confirmed grant or leave a revoked grant active.
        logger.exception("Could not emit %s for user %s", kind, user_id)


def grant(user_id: str) -> LiveAuthorization:
    """Authorize one username to open automated live entries this session."""
    session_day = get_trading_session_date()
    username = str(user_id)
    authorization = LiveAuthorization(
        active=True,
        session_day=session_day,
        expires_at=session_reset_time().isoformat(timespec="minutes"),
    )
    expired = False
    with _lock:
        previous = _authorizations.get(username)
        if previous is not None and previous.session_day == session_day and previous.active:
            return previous
        expired = previous is not None and previous.session_day != session_day
        _authorizations[username] = authorization
    if expired:
        _notify_transition(
            username,
            "live_authorization_expired",
            "Live automation authorization expired at the trading-session boundary",
        )
    _notify_transition(
        username,
        "live_authorization_granted",
        "Live automation authorized for this trading session",
    )
    return authorization


def revoke(user_id: str) -> None:
    """Block new automated live entries for one username immediately."""
    username = str(user_id)
    session_day = get_trading_session_date()
    with _lock:
        previous = _authorizations.pop(username, None)
    if previous is None:
        return
    if previous.session_day == session_day:
        _notify_transition(
            username,
            "live_authorization_revoked",
            "Live automation authorization was revoked",
        )
    else:
        _notify_transition(
            username,
            "live_authorization_expired",
            "Live automation authorization expired at the trading-session boundary",
        )


def invalidate_for_reauthentication(user_id: str) -> None:
    """Require a fresh approval when broker identity or credentials change."""
    revoke(user_id)


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
    if authorization is not None:
        _notify_transition(
            username,
            "live_authorization_expired",
            "Live automation authorization expired at the trading-session boundary",
        )
    return _inactive(session_day)


def require_live_entry(user_id: str) -> tuple[bool, str | None]:
    """Say whether a new automated live entry may be claimed."""
    current = status(user_id)
    if current.active:
        return True, None
    return False, _DENIED_MESSAGE
