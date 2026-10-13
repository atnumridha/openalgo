from dataclasses import asdict
from datetime import datetime
from decimal import Decimal as D


def public_setup(s):
    return {
        k: v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, D) else v
        for k, v in asdict(s).items()
    }
