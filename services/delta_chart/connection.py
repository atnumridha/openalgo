"""Credential storage is independent of the application's selected broker."""

import json
import os
import stat
from pathlib import Path

from dotenv import dotenv_values


class Connections:
    def __init__(self, store):
        self.store = store

    def __call__(self, user):
        from database.auth_db import decrypt_token

        with self.store.db() as db:
            row = db.execute("SELECT value FROM credentials WHERE user=?", (user,)).fetchone()
        if row:
            values = json.loads(decrypt_token(row["value"]))
            return values["key"], values["secret"]
        owner = os.getenv("DELTA_CHART_OWNER")
        if owner:
            if user != owner:
                return None
        else:
            from database.user_db import User

            users = User.query.limit(2).all()
            if len(users) != 1 or users[0].username != user:
                return None
        # Same server-only store/read semantics as delta_scalper.observation.monitor_credentials.
        path = Path(
            os.getenv("DELTA_MCP_CONFIG_FILE") or Path.home() / ".delta-exchange-mcp/config.env"
        ).expanduser()
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd) as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o077
                ):
                    return None
                values = dotenv_values(stream=stream)
            if values.get("DELTA_MCP_ENV", "india_prod") != "india_prod":
                return None
            key = values.get("DELTA_API_KEY")
            secret = values.get("DELTA_API_SECRET")
            return (key, secret) if key and secret else None
        except OSError:
            return None

    def save(self, user, key, secret):
        from database.auth_db import encrypt_token

        if (
            not isinstance(key, str)
            or not isinstance(secret, str)
            or not 8 <= len(key) <= 512
            or not 8 <= len(secret) <= 512
        ):
            raise ValueError("Valid Delta key and secret required")
        from services.delta_chart.service import Client

        Client(key, secret).request("GET", "/v2/users/trading_preferences")
        value = encrypt_token(json.dumps({"key": key, "secret": secret}))
        with self.store.db() as db:
            db.execute("INSERT OR REPLACE INTO credentials VALUES(?,?)", (user, value))
