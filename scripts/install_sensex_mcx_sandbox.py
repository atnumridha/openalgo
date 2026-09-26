"""Install and optionally activate the SENSEX/MCX sandbox starter pack."""

from __future__ import annotations

import argparse
import pathlib
import sys

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    from database import auth_db, flow_db, strategy_module_db
    from services.strategy_module import starter_pack

    strategy_module_db.init_db()
    flow_db.init_db()
    result = starter_pack.install(args.username)
    workflows = [*result.workflows_created, *result.workflows_existing]
    activated: list[str] = []

    if args.activate:
        api_key = auth_db.get_api_key_for_tradingview(args.username)
        if not api_key:
            raise RuntimeError("No OpenAlgo API key is configured for this user")
        for workflow in workflows:
            if not flow_db.activate_workflow(workflow["id"], api_key=api_key):
                raise RuntimeError(f"Could not activate workflow {workflow['id']}")
            activated.append(workflow["name"])

    print(
        {
            "strategies_created": len(result.created),
            "strategies_existing": len(result.existing),
            "workflows_created": len(result.workflows_created),
            "workflows_existing": len(result.workflows_existing),
            "activated": activated,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
