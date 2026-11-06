"""Private signed worker endpoint, deliberately separate from user-session routes."""
import time
from flask import Blueprint, jsonify, request
from services.combined_terminal.contracts import WorkerCommand
from services.combined_terminal.transport import PATH, MAX_BODY


def create_worker_blueprint(secret, guard, provider, *, clock=time.time):
    bp=Blueprint('broker_worker',__name__)

    @bp.post(PATH)
    def command():
        if request.content_length is not None and request.content_length>MAX_BODY:
            return jsonify(status='error',message='Request too large'),413
        body=request.get_data(cache=True)
        try:
            guard.verify(secret,body,PATH,dict(request.headers),now=clock())
        except (PermissionError,ValueError):
            return jsonify(status='error',message='Worker authentication required'),403
        try:
            payload=request.get_json(silent=True)
            if not isinstance(payload,dict):raise ValueError('Invalid envelope')
            parsed=WorkerCommand.from_dict(payload)
        except (ValueError,TypeError,KeyError):
            return jsonify(status='error',message='Invalid worker command'),400
        try:
            result=provider().execute(parsed)
            return jsonify(result.to_dict())
        except PermissionError:
            return jsonify(status='error',message='Worker account identity unavailable'),403
        except (ValueError,KeyError,TypeError):
            return jsonify(status='error',message='Worker command conflict'),409
        except Exception:
            return jsonify(status='error',message='Worker unavailable'),503

    return bp
