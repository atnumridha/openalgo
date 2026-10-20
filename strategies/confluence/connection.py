"""Use the Delta account already authenticated in the local OpenAlgo host.

No credential copy/setup, account mutation, or credential-bearing log output.
The database session is closed after each check; revocation and order mode are
read from current rows rather than a child-process cache.
"""

from __future__ import annotations

import os


def hosted_activation():
    return bool(
        os.getenv("STRATEGY_ID")
        and os.getenv("OPENALGO_API_KEY")
        and os.getenv("OPENALGO_START_REASON") in ("manual", "scheduled")
    )


def credentials_from_account(account, api, decrypt, env):
    from .live import backend

    if not account or account.is_revoked or account.broker != "deltaexchange":
        raise ValueError("Connect an active Delta account in OpenAlgo")
    if not api or api.order_mode not in (None, "auto"):
        raise ValueError(
            "OpenAlgo automatic order mode is required; existing order approvals are preserved"
        )
    if (
        env.get("DELTA_BASE_URL", "https://api.india.delta.exchange").rstrip("/")
        != "https://api.india.delta.exchange"
    ):
        raise ValueError("This live strategy requires the Delta India production connection")
    key, secret = decrypt(account.auth), env.get("BROKER_API_SECRET")
    if not key or not secret:
        raise ValueError("The existing OpenAlgo Delta connection is incomplete")
    _, _, _, rest, _, _, _ = backend()
    # The existing login authenticates the key, but does not prove rotation.
    return rest.Credentials(key, secret, rotated=False)


def connected_credentials():
    key = os.getenv("OPENALGO_API_KEY")
    if not key:
        raise ValueError("OpenAlgo host authentication is unavailable")
    from database.auth_db import ApiKeys, Auth, db_session, decrypt_token, verify_api_key

    try:
        user = verify_api_key(key)
        if not user:
            raise ValueError("OpenAlgo host authentication is invalid")
        account = db_session.query(Auth).populate_existing().filter_by(name=user).first()
        api = db_session.query(ApiKeys).populate_existing().filter_by(user_id=user).first()
        return credentials_from_account(account, api, decrypt_token, os.environ)
    except ValueError:
        raise
    except Exception:
        raise ValueError("Existing OpenAlgo Delta connection could not be read") from None
    finally:
        db_session.remove()
