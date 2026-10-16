import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, update

from services.kotak_assistant.store import Account, Store


def test_a_real_process_crash_does_not_leave_a_five_minute_recovery_lock(tmp_path):
    url = f"sqlite:///{tmp_path}/crash.db"
    code = """
import os,sys
from sqlalchemy import create_engine
from services.kotak_assistant.store import Store
s=Store(create_engine(sys.argv[1]))
with s.lock('fixture:live') as owner:
    s.save('fixture:live',{'trade_id':'saved-before-submit'},owner)
    os._exit(0)
"""
    subprocess.run([sys.executable, "-c", code, url], check=True, timeout=20)
    store = Store(create_engine(url))
    with store.lock("fixture:live") as owner:
        assert store.read("fixture:live")["trade_id"] == "saved-before-submit"
        store.save("fixture:live", {"recovered": True}, owner)
    assert store.read("fixture:live") == {"recovered": True}


def test_alive_process_and_unrecognized_owners_are_never_reclaimed(tmp_path):
    url = f"sqlite:///{tmp_path}/alive.db"
    first, second = Store(create_engine(url)), Store(create_engine(url))
    with first.lock("fixture:live"):
        with pytest.raises(ValueError, match="already in progress"):
            with second.lock("fixture:live"):
                pass
    with first.lock("fixture:live"):
        with first.engine.begin() as c:
            c.execute(
                update(Account)
                .where(Account.scope == "fixture:live")
                .values(owner="legacy-owner-not-provably-dead")
            )
        with pytest.raises(ValueError, match="already in progress"):
            with second.lock("fixture:live"):
                pass
