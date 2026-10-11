"""Deterministic browser fixture. No Docker socket, live Steam tokens or real players."""
import json
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel.core import Controller, config_from, atomic_json
from panel.server import Handler
from test_installer import FakeEngine

root=Path(tempfile.mkdtemp(prefix=".cs2-test-"))
controller=Controller(root/'state',root/'config',FakeEngine())
controller.bootstrap='browser-test-setup-token'
controller.config=config_from({'gslt':'a'*32,'server_name':'Arikitos CS2','join_password':'friends-only'})
controller.write_config()
controller.job.update(installed=True,installed_build='12345',stage='ready')
controller.create_server()
controller.engine.containers['cs2-local-server']['State'].update(Running=True,Health={'Status':'healthy'})
controller.rcon_command=lambda command:'CS2LOCAL_OK'
controller.management.public_address=lambda force=False:{'ip':'8.8.8.8','address':'8.8.8.8:27015','port':27015,'error':None}
controller.metrics=lambda:{'cpu_percent':4.2,'memory_bytes':800*1024**2,'memory_limit':8*1024**3}
controller.management.telemetry.mkdir(parents=True)
atomic_json(controller.management.telemetry/'users-seen.json',{'76561198000000001':{'name':'Demo <player>','first_seen':time.time(),'last_seen':time.time(),'visits':1}})
def snapshots():
    while True:
        atomic_json(controller.management.telemetry/'live.json',{'updated_at':time.time(),'players':[{'steamid':'76561198000000001','name':'Demo <player>','bot':False,'team':3,'ping':23}]})
        time.sleep(1)
threading.Thread(target=snapshots,daemon=True).start()
Handler.controller=controller
ThreadingHTTPServer(('127.0.0.1',8090),Handler).serve_forever()
