"""Validated local supervision; never clones credentials, logs them, or places orders."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import time

DB_KEYS=('DATABASE_URL','LATENCY_DATABASE_URL','LOGS_DATABASE_URL','HEALTH_DATABASE_URL','SANDBOX_DATABASE_URL','HISTORIFY_DATABASE_URL')


def validate_services(services):
    from dotenv import dotenv_values
    from services.combined_terminal.configuration import private_bytes
    ports=set();databases=set();roles=set()
    for item in services:
        role=item.get('role')
        if role not in ('kotak','flattrade') or role in roles:raise ValueError('Invalid or duplicate broker role')
        roles.add(role)
        root=Path(item['root']).resolve();path=Path(item['env_file'])
        if path!=root/'.env':raise ValueError('Environment must be the checkout private .env')
        private_bytes(path)
        env=dotenv_values(path,interpolate=False)
        if any(not env.get(k) for k in ('BROKER_API_KEY','BROKER_API_SECRET','APP_KEY','API_KEY_PEPPER')):raise ValueError('Broker credentials or application keys missing')
        for field,key in [('http_port','FLASK_PORT'),('ws_port','WEBSOCKET_PORT'),('zmq_port','ZMQ_PORT')]:
            port=item[field]
            if type(port) is not int or not 1024<=port<=65535 or port in ports:raise ValueError('Invalid or duplicate service port')
            ports.add(port)
            if str(port)!=env.get(key):raise ValueError('Environment service port mismatch')
        for key in DB_KEYS:
            value=env.get(key,'')
            if key!='HISTORIFY_DATABASE_URL':
                if not value.startswith('sqlite:///'):raise ValueError('Isolated SQLite database required')
                value=value[len('sqlite:///'):]
            if not value:raise ValueError('Missing isolated database')
            db=(root/value).resolve()
            if db in databases:raise ValueError('Shared database refused')
            databases.add(db)
        # The existing Kotak service is supervised by its own launchd job.
        if role=='kotak' and item.get('external') is not True:raise ValueError('Existing Kotak must remain externally supervised')
    return services


class Supervisor:
    def __init__(self,services,spawn):self.services,self.spawn,self.children=services,spawn,{}
    def tick(self):
        for item in self.services:
            if item.get('external'):continue
            child=self.children.get(item['role'])
            if child is None or child.poll() is not None:self.children[item['role']]=self.spawn(item)


def spawn(item):
    from scripts.kotak_assistant.supervise import server_command,listening
    if listening(item['http_port']):raise ValueError('Worker port already in use; refusing takeover')
    root=Path(item['root']).resolve();(root/'runtime/neo_desk').mkdir(parents=True,exist_ok=True)
    # Gunicorn loads this checkout's private .env itself. Never put credentials in argv.
    env={k:v for k,v in os.environ.items() if not k.startswith(('BROKER_','COMBINED_')) and k not in DB_KEYS}
    return subprocess.Popen(server_command(root,item['http_port']),cwd=root,env=env)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    from services.combined_terminal.configuration import document
    services=validate_services(document(args.config)['services'])
    if args.check:print('Isolated broker service configuration valid');return
    supervisor=Supervisor(services,spawn)
    while True:supervisor.tick();time.sleep(5)

if __name__=='__main__':main()
