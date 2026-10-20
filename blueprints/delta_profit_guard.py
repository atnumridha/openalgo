"""Session and CSRF-protected controls for adopting existing Delta protection."""
from functools import wraps

from flask import Blueprint, jsonify, request, session

from services import delta_profit_guard as service

delta_profit_guard_bp = Blueprint('delta_profit_guard', __name__, url_prefix='/delta-profit-protection/api')


def guarded(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user'):
            return jsonify(status='error', message='Sign in to view Delta protection'), 401
        if session.get('broker') != 'deltaexchange':
            return jsonify(status='error', message='Connect Delta to use this protection'), 403
        try:
            return fn(*args, **kwargs)
        except service.ProtectionError as exc:
            return jsonify(status='error', message=str(exc)), 409
        except (ValueError, KeyError, TypeError):
            # Validation explanations are supplied through the known service
            # messages below; unexpected broker formats cannot become a success.
            import logging
            logging.getLogger(__name__).exception('Delta protection request could not be completed')
            return jsonify(status='error', message='Protection could not be verified. Refresh the preview and check broker orders'), 409
        finally:
            from utils.db_sessions import remove_all_scoped_sessions
            remove_all_scoped_sessions()
    return wrapper


@delta_profit_guard_bp.get('/status')
@guarded
def status():
    plans = [service.public(p) for _, _, p in service.repository().list(user=session['user'])]
    return jsonify(status='success', data={'plans':plans, 'heartbeat':service.last_cycle, 'interval_seconds':1})


def inputs():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('symbol'), str) or not data['symbol']:
        raise service.ProtectionError('Choose the position to protect')
    if data.get('mode') != 'live':
        raise service.ProtectionError('Explicit Live mode is required')
    return data


@delta_profit_guard_bp.post('/preview')
@guarded
def preview():
    data = inputs()
    result = service.manager().preview(session['user'], data['symbol'], data)
    return jsonify(status='success', data=service.public(result))


@delta_profit_guard_bp.post('/enable')
@guarded
def enable():
    from database.settings_db import get_analyze_mode
    if get_analyze_mode():
        raise service.ProtectionError('Select Live mode before enabling real-position protection')
    data = inputs()
    result = service.manager().enable(session['user'], data['symbol'], data, data.get('preview_id'))
    return jsonify(status='success', data=service.public(result))


@delta_profit_guard_bp.post('/pause')
@guarded
def pause():
    data = inputs()
    result = service.manager().disable(session['user'], data['symbol'])
    return jsonify(status='success', data=service.public(result) if result else None)
