"""Session/CSRF-protected public terminal API. Worker secrets never cross it."""
from dataclasses import asdict
import os
from flask import Blueprint,jsonify,request,session


def create_combined_terminal_blueprint(provider=None):
    bp=Blueprint('combined_terminal',__name__,url_prefix='/combined-terminal/api')
    def runtime():
        if provider:return provider()
        from services.combined_terminal.runtime import get_runtime
        return get_runtime()

    @bp.before_request
    def authorize():
        if not isinstance(session.get('user'),str) or not session['user']:
            return jsonify(status='error',message='Authentication required'),401
        if request.endpoint=='combined_terminal.config':return None
        if not runtime().enabled:return jsonify(status='error',message='Combined terminal is not configured'),404
        if getattr(runtime(),'coordinator',None) is None and request.endpoint not in ('combined_terminal.snapshot','combined_terminal.config'):
            return jsonify(status='error',message='Private broker configuration required'),409

    @bp.errorhandler(PermissionError)
    def forbidden(error):return jsonify(status='error',message='Account or intent unavailable'),403

    @bp.errorhandler(ValueError)
    def conflict(error):
        data={'status':'error','message':str(error)}
        if request.endpoint=='combined_terminal.entry':
            payload=request.get_json(silent=True) or {}
            try:
                runtime().ledger.intent(session['user'],payload.get('operation_id'))
                data['submission']='reconcile'
            except PermissionError:
                data['submission']='not_submitted'
        return jsonify(data),409

    @bp.errorhandler(KeyError)
    @bp.errorhandler(TypeError)
    def invalid(error):return jsonify(status='error',message='Invalid terminal request'),400

    @bp.get('/config')
    def config():
        enabled=runtime().enabled if provider else os.getenv('COMBINED_TERMINAL_ENABLED','').lower()=='true'
        return jsonify(status='success',data={'enabled':enabled})

    @bp.get('/snapshot')
    def snapshot():
        mode=request.args.get('mode','live')
        if mode not in ('live','analyze'):raise ValueError('Invalid mode')
        return jsonify(status='success',data=runtime().snapshot(session['user'],mode))

    @bp.get('/market')
    def market():
        data=request.args.to_dict()
        connection=data.pop('connection_id')
        return jsonify(status='success',data=runtime().coordinator.read_data(session['user'],connection,'market',data))

    @bp.get('/chart')
    def chart():
        data=request.args.to_dict()
        connection=data.pop('connection_id')
        return jsonify(runtime().coordinator.read_data(session['user'],connection,'chart',data))

    @bp.post('/settings')
    def settings():
        data=request.get_json()
        return jsonify(status='success',data=runtime().configure(session['user'],data['mode'],data['settings']))

    @bp.post('/selection')
    def selection():
        data=request.get_json()
        return jsonify(status='success',data=runtime().coordinator.select(session['user'],data['context_id'],data['connection_id']))

    @bp.post('/preview')
    def preview():
        data=request.get_json()
        return jsonify(status='success',data=runtime().coordinator.preview(session['user'],data['connection_id'],data['ticket']))

    @bp.post('/entry')
    def entry():
        data=request.get_json()
        if not isinstance(data.get('connection_id'),str):raise ValueError('Select the execution broker')
        result=runtime().coordinator.enter(session['user'],data['preview_id'],data['operation_id'],connection_id=data['connection_id'])
        return jsonify(status='success',data=asdict(result))

    @bp.post('/trade-action')
    def trade_action():
        data=request.get_json()
        result=runtime().coordinator.mutate_trade(session['user'],data['trade_id'],data['action'],data.get('payload',{}))
        return jsonify(status='success',data=result.to_dict())

    return bp
