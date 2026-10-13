import os
from flask import request
from flask_restx import Namespace, Resource

from database.auth_db import verify_api_key
from limiter import limiter
from services.neo_desk.service import get_service
from utils.logging import get_logger

api = Namespace("neodesk", description="Native confirmed-signal provider; cannot activate trading")


@api.route("/signal")
class NeoSignal(Resource):
    @limiter.limit("4 per second")
    def post(self):
        if os.environ.get("NEO_SAVED_LOGIN", "").upper() != "TRUE":
            return {"status": "error", "message": "Neo Desk is not enabled on this instance."}, 404
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"apikey"}:
            return {"status": "error", "message": "Only the native API key is accepted."}, 400
        owner = verify_api_key(body["apikey"])
        if not owner:
            return {"status": "error", "message": "Native API authentication failed."}, 401
        try:
            return get_service().poll(owner), 200
        except Exception:
            get_logger(__name__).exception("Native signal provider failed")
            from database import neo_desk_db as desk

            desk.db_session.rollback()
            desk.configure(
                owner, status="Signal evaluation failed. Check broker connection and native logs."
            )
            return {
                "status": "error",
                "message": "Signal evaluation failed. Check the broker connection and native logs.",
            }, 503
