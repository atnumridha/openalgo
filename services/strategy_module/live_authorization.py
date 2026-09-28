"""Session-scoped authorization for automated live entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from database import live_authorization_db as store
from services.strategy_module.session import IST, session_reset_time
from utils.logging import get_logger
from utils.real_threading import Lock
from utils.session import get_trading_session_date

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LiveAuthorization:
    active: bool
    session_day: str
    expires_at: str


_lock = Lock()
_revocation_epoch = 0
_revocations_inflight = 0
_grants_inflight = 0
_revocation_failed = False
_DENIED_MESSAGE = "Live automation is not authorized for this trading session"


def authorization_expires_at(session_day: str) -> str:
    """The next reset after this session's start-date, at any configured hour."""
    next_day = datetime.fromisoformat(session_day).date() + timedelta(days=1)
    boundary = IST.localize(datetime.combine(next_day, session_reset_time()))
    return boundary.isoformat(timespec="minutes")


def _inactive(session_day: str) -> LiveAuthorization:
    return LiveAuthorization(
        active=False,
        session_day=session_day,
        expires_at=authorization_expires_at(session_day),
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


def _now() -> datetime:
    return datetime.now(IST)


def _public(row: dict) -> LiveAuthorization:
    return LiveAuthorization(
        bool(row["active"]), row["session_day"], row["expires_at"]
    )


def grant(user_id: str) -> LiveAuthorization:
    """Commit explicit approval for this account/session before returning it."""
    global _revocation_failed, _grants_inflight
    username = str(user_id)
    session_day = get_trading_session_date()
    with _lock:
        epoch = _revocation_epoch
        recovering = _revocation_failed
        if _revocations_inflight or _grants_inflight:
            return _inactive(session_day)
        _grants_inflight += 1
    try:
        previous, current, changed = store.grant(
            username, session_day, authorization_expires_at(session_day), _now(),
            discard_previous=recovering,
        )
        with _lock:
            overtaken = epoch != _revocation_epoch or bool(_revocations_inflight)
            if not overtaken:
                _revocation_failed = False
        if overtaken:
            # Revoke may finish before this write gets its database lock. Do
            # not leave that late write available for the next status/restart.
            store.revoke(username, expected=current)
            return _inactive(session_day)
    except Exception:
        with _lock:
            _revocation_failed = True
        logger.exception("Could not persist live authorization for user %s", username)
        return _inactive(session_day)
    finally:
        with _lock:
            _grants_inflight -= 1
    if changed:
        if previous and previous["active"] and previous["session_day"] != session_day:
            _notify_transition(
                username, "live_authorization_expired",
                "Live automation authorization expired at the trading-session boundary",
            )
        _notify_transition(
            username, "live_authorization_granted",
            "Live automation authorized for this trading session",
        )
    return _public(current)


def revoke(user_id: str) -> None:
    """Block immediately and acknowledge revocation only after it is durable.

    An unavailable persistence layer cannot confirm revocation. Fail the call
    and latch process-wide entry denial until a fresh explicit approval can
    first discard every uncertain old grant in the same transaction.
    """
    global _revocation_epoch, _revocations_inflight, _revocation_failed
    username = str(user_id)
    with _lock:
        _revocation_epoch += 1
        _revocations_inflight += 1
    try:
        previous = store.revoke(username)
    except Exception as exc:
        with _lock:
            _revocation_failed = True
        logger.exception("Could not persist live revocation for user %s", username)
        raise RuntimeError("Live authorization revocation could not be persisted") from exc
    finally:
        with _lock:
            _revocations_inflight -= 1
    if previous is not None:
        expired = previous["session_day"] != get_trading_session_date()
        _notify_transition(
            username,
            "live_authorization_expired" if expired else "live_authorization_revoked",
            "Live automation authorization expired at the trading-session boundary"
            if expired else "Live automation authorization was revoked",
        )


def invalidate_for_reauthentication(user_id: str) -> None:
    """Require a fresh approval when broker identity or credentials change."""
    revoke(user_id)


def _effective_status(user_id: str, *, invalidate: bool) -> LiveAuthorization:
    global _revocation_failed
    session_day = get_trading_session_date()
    username = str(user_id)
    with _lock:
        epoch = _revocation_epoch
        if _revocation_failed or _revocations_inflight or _grants_inflight:
            return _inactive(session_day)
    try:
        row, binding = store.read(username)
        if not row or not row["active"]:
            return _inactive(session_day)
        expired = (
            row["session_day"] != session_day
            or datetime.fromisoformat(row["expires_at"]) <= _now()
        )
        if expired or not binding or binding != row["binding_digest"]:
            revoked = None
            if invalidate:
                try:
                    revoked = store.revoke(username, expected=row)
                except Exception:
                    with _lock:
                        _revocation_failed = True
                    raise
            if revoked is not None:
                _notify_transition(
                    username,
                    "live_authorization_expired" if expired else "live_authorization_revoked",
                    "Live automation authorization expired at the trading-session boundary"
                    if expired else "Live automation authorization no longer matches the broker session",
                )
            return _inactive(session_day)
        with _lock:
            if epoch != _revocation_epoch or _revocation_failed or _revocations_inflight or _grants_inflight:
                return _inactive(session_day)
        return _public(row)
    except Exception:
        logger.exception("Could not verify live authorization for user %s", username)
        return _inactive(session_day)


def status(user_id: str) -> LiveAuthorization:
    """Verify durable authority; expire stale grants once outside any lock."""
    return _effective_status(user_id, invalidate=True)


def peek_status(user_id: str) -> LiveAuthorization:
    """Read effective durable authority without writes or lifecycle delivery."""
    return _effective_status(user_id, invalidate=False)


def require_live_entry(user_id: str) -> tuple[bool, str | None]:
    """Say whether a new automated live entry may be claimed."""
    current = status(user_id)
    if current.active:
        return True, None
    return False, _DENIED_MESSAGE
