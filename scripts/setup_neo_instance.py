"""Provision a clean native instance from existing private Kotak settings."""

import argparse
import secrets
import shutil
from pathlib import Path

from dotenv import load_dotenv, set_key

from services.kotak_saved_login import read_saved_kotak_settings


def provision(source: Path, target: Path):
    settings = read_saved_kotak_settings(source / "settings.env")
    if not all((settings.ucc, settings.api_token, settings.mobile, settings.mpin)):
        raise ValueError("The current private Kotak settings are incomplete.")
    env_file = target / ".env"
    if env_file.exists():
        raise ValueError("This instance already has private settings; refusing to overwrite them.")
    shutil.copy2(target / ".sample.env", env_file)
    env_file.chmod(0o600)
    values = {
        "BROKER_API_KEY": settings.ucc,
        "BROKER_API_SECRET": settings.api_token,
        "KOTAK_MOBILE": settings.mobile,
        "KOTAK_MPIN": settings.mpin,
        "NEO_LEGACY_ACCESS_SECRET": settings.access_secret,
        "NEO_SOURCE_RUNTIME": str(source.resolve()),
        "NEO_SAVED_LOGIN": "TRUE",
        "APP_KEY": secrets.token_hex(32),
        "API_KEY_PEPPER": secrets.token_hex(32),
        "FERNET_SALT": secrets.token_hex(32),
        "VALID_BROKERS": "kotak",
        "HOST_SERVER": "http://127.0.0.1:5001",
        "FLASK_HOST_IP": "127.0.0.1",
        "FLASK_PORT": "5001",
        "FLASK_DEBUG": "False",
        "REDIRECT_URL": "http://127.0.0.1:5001/kotak/callback",
        "WEBSOCKET_HOST": "127.0.0.1",
        "WEBSOCKET_PORT": "8767",
        "ZMQ_HOST": "127.0.0.1",
        "ZMQ_PORT": "5557",
        "SESSION_COOKIE_NAME": "neo_openalgo_session",
        "SESSION_EXPIRY_TIME": "00:00",
    }
    for key, value in values.items():
        set_key(env_file, key, value)
    (target / "frontend" / ".env.local").write_text("VITE_NEO_DESK_ENABLED=true\n")
    load_dotenv(env_file, override=True)
    from database.sandbox_db import init_db as init_sandbox
    from database.sandbox_db import set_config
    from database.settings_db import init_db, set_analyze_mode

    init_db()
    set_analyze_mode(True)
    init_sandbox()
    set_config(
        "starting_capital",
        "10000.00",
        "Initial Sandbox allocation; entry affordability uses fresh broker limit.",
    )
    from utils.logging import get_logger

    get_logger(__name__).info(
        "Native Kotak instance configured at http://127.0.0.1:5001 in Sandbox mode"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    provision(args.source, Path.cwd())
