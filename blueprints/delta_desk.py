"""Owner-bound, session/CSRF-protected native Delta paper desk."""
import os
import re
from flask import Blueprint, jsonify, request, session
from utils.session import check_session_validity
from services.delta_desk import bridge

delta_desk_bp=Blueprint('delta_desk',__name__,url_prefix='/delta-desk/api')

@delta_desk_bp.before_request
@check_session_validity
def owner_only():
    owner=os.environ.get('DELTA_SCALPER_OWNER')
    if not owner:
        return jsonify(error='Delta desk is not linked. Set DELTA_SCALPER_OWNER to the owning OpenAlgo username on this server.'),503
    if session.get('user')!=owner:
        return jsonify(error='This Delta controller belongs to a different OpenAlgo user.'),403

@delta_desk_bp.after_request
def no_cache(response):
    response.headers['Cache-Control']='no-store'
    return response

def dispatch(action,payload):
    try:
        return jsonify(bridge.call(action,payload))
    except ValueError as exc:
        return jsonify(error=str(exc)),409
    except bridge.BridgeUnavailable:
        return jsonify(error='Delta controller unavailable or busy. Refresh status before retrying a control; its outcome may be pending.'),503

@delta_desk_bp.get('/<action>')
def read(action):
    if action not in {'status','observation','research','models','stream'}:
        return jsonify(error='Unknown view'),404
    profile=request.args.get('profile','historical')
    if profile not in {'historical','baseline'}:
        return jsonify(error='Invalid profile'),400
    return dispatch(action,{'profile':profile})

@delta_desk_bp.post('/control')
def control():
    body=request.get_json(silent=True)
    if not isinstance(body,dict) or set(body)-{'action','mode','profile','settings','minutes'}:
        return jsonify(error='Invalid control request'),400
    if body.get('mode')=='live':
        return jsonify(error='This desk controls paper only. Live requires exchange qualification and explicit CLI arming.'),409
    if body.get('mode')!='paper' or body.get('profile') not in ('historical','baseline') or body.get('action') not in ('start','pause','resume','stop'):
        return jsonify(error='Choose paper mode, profile and a supported control explicitly'),400
    settings=body.get('settings',{})
    if not isinstance(settings,dict) or set(settings)-{'provider','model','reasoning','decision_mode'}:
        return jsonify(error='Risk settings and execution paths cannot be overridden'),400
    if settings.get('provider','codex') not in ('codex','ollama') or settings.get('decision_mode','ai') not in ('ai','filter'):
        return jsonify(error='Invalid AI provider or decision mode'),400
    model=settings.get('model');reasoning=settings.get('reasoning')
    if model is not None and (not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}',model)):
        return jsonify(error='Invalid model'),400
    efforts=(None,'off','on') if settings.get('provider')=='ollama' else (None,'none','minimal','low','medium','high','xhigh','max','ultra')
    if reasoning not in efforts:
        return jsonify(error='Invalid reasoning setting'),400
    minutes=body.get('minutes')
    if minutes is not None and (type(minutes) is not int or not 1<=minutes<=720):
        return jsonify(error='Timed runs require 1–720 minutes; use null for continuous'),400
    return dispatch('control',body)
