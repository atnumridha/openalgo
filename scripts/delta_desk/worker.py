"""Fixed-function OpenAlgo bridge. Launched only with local server paths.

Uses the installed controller unchanged. No live/qualification/credential actions
are reachable. Research reports describe reference-policy agreement, not returns.
"""
import json
from pathlib import Path
import sys
import time


def read_json(path):
    return json.loads(path.read_text())

def compact(value):
    if isinstance(value,dict):
        return {k:compact(v) for k,v in value.items() if k not in {'details','directory','adapter','fused','dataset','log','reused_from','prompt'}}
    if isinstance(value,list):return [compact(x) for x in value]
    return value

def research(root):
    paths=sorted((root/'validation').glob('decision-*/summary.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    result={'training':None,'comparison':None,'model':None,'at':None}
    for path in paths:
        try:
            data=read_json(path)
            if 'comparison' not in data:continue
            result.update({k:compact(data.get(k)) for k in result})
            # Model details are not private; only expose serving tag and digest.
            model=data.get('model') or {}
            result['model']={'tag':model.get('tag'),'digest':model.get('metadata',{}).get('digest')}
            break
        except (OSError,ValueError,TypeError):continue
    result['note']='Policy agreement and latency only. Paper P&L is measured separately. Training does not activate a model.'
    return result

def check_model(root,tag,digest):
    if tag=='deepseek-r1:1.5b':return
    for path in sorted((root/'validation').glob('decision-*/model.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            model=read_json(path)
            if model.get('tag')!=tag:continue
            evidence=read_json(path.with_name('comparison.json'))
            if evidence.get('eligible_for_paper') is not True:
                raise ValueError('This research model failed paper selection: '+', '.join(evidence.get('failures',[])))
            if not digest or model.get('metadata',{}).get('digest')!=digest:
                raise ValueError('Model digest differs from evaluated artifact; evaluate it again')
            return
        except (OSError,json.JSONDecodeError):continue
    raise ValueError('Model needs a completed paper-selection evaluation before activation')

class Worker:
    def __init__(self,install,root):
        sys.path.insert(0,str(install/'scripts'))
        from delta_scalper import dashboard,observation,local_ai
        from trades import with_trade_details
        # Enrich only this read-only helper process; the installed execution code is unchanged.
        observation.account_report=with_trade_details(observation.account_report)
        self.dashboard,self.observation,self.local_ai=dashboard,observation,local_ai
        self.root=root
        self.cache=None;self.cache_at=0

    def handle(self,action,p):
        profile=p.get('profile','historical')
        if profile not in ('baseline','historical'):raise ValueError('Invalid profile')
        if action=='status':
            x=self.dashboard.snapshot(self.root,profile)
            # Bound historical rows; aggregates remain over the complete ledger.
            x['runs']=x['runs'][:50];x['report']['trade_details']=x['report']['trade_details'][-100:]
            x.pop('last_decision_packet',None)
            x['readiness']=self.observation.live_readiness(self.root,profile)
            return compact(x)
        if action=='observation':return self.observation.get_monitor().snapshot()
        if action=='research':
            if self.cache is None or time.time()-self.cache_at>30:
                self.cache=research(self.root);self.cache_at=time.time()
            return self.cache
        if action=='models':
            local=self.local_ai.local_health()
            for model in local['models']:
                try:check_model(self.root,model['name'],model.get('digest'));model['selectable']=True
                except ValueError as exc:model.update(selectable=False,blocker=str(exc))
            return {'codex':self.dashboard.model_catalog(),'local':local}
        if action=='stream':
            from delta_scalper.ai_stream import read_stream
            from delta_scalper.runner import namespace
            value=read_stream(namespace(self.root,'paper','india_prod',profile=profile))
            # Expose current output and timings. Raw reasoning stays in the local UI.
            if value:value={k:v for k,v in value.items() if k not in {'thinking','thinking_trimmed'}}
            return {'stream':value}
        if action=='control':
            if p.get('mode')!='paper':raise ValueError('Paper mode required')
            if p['action']=='start':
                s=p.get('settings',{});provider=s.get('provider','codex');model=s.get('model')
                if provider=='ollama':
                    model=model or self.local_ai.DEFAULT_MODEL
                    models=self.local_ai.local_health()['models']
                    row=next((m for m in models if m['name']==model),{})
                    check_model(self.root,model,row.get('digest'))
                return self.dashboard.start_paper(self.root,profile,p.get('minutes'),model,s.get('reasoning'),s.get('decision_mode','ai'),provider)
            return self.dashboard.control(self.root,profile,p['action'])
        raise ValueError('Unsupported action')

def main():
    worker=Worker(Path(sys.argv[1]),Path(sys.argv[2]))
    for line in sys.stdin:
        try:
            request=json.loads(line)
            result={'ok':True,'data':worker.handle(request['action'],request['payload'])}
        except ValueError as exc:result={'ok':False,'validation':True,'error':str(exc)}
        except Exception:result={'ok':False,'error':'Controller read failed'}
        print(json.dumps(result,default=str,allow_nan=False),flush=True)

if __name__=='__main__':main()
