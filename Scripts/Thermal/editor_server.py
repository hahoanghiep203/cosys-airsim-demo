"""Local automation bridge for the isolated thermal test editor."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import traceback

import unreal

ROOT = Path(unreal.Paths.project_dir()).resolve()
OUTPUT = ROOT / 'Saved' / 'ThermalScene'
OUTPUT.mkdir(parents=True, exist_ok=True)
PORT = 12049
SERVER = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
SERVER.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
SERVER.bind(('127.0.0.1', PORT))
SERVER.listen(4)
SERVER.setblocking(False)
CLIENTS = {}
SCOPE = {'unreal': unreal, 'ROOT': ROOT, 'OUTPUT': OUTPUT, 'Path': Path, 'json': json}


def tick(_delta):
    try:
        connection, _ = SERVER.accept()
        connection.setblocking(False)
        CLIENTS[connection] = bytearray()
    except BlockingIOError:
        pass
    for connection, buffer in list(CLIENTS.items()):
        try:
            packet = connection.recv(65536)
            if not packet:
                connection.close()
                del CLIENTS[connection]
                continue
            buffer.extend(packet)
            if b'\n' not in buffer:
                continue
            request = json.loads(bytes(buffer).split(b'\n', 1)[0])
            globals()['BRIDGE_LAST_CODE'] = request['code']
            stdout = io.StringIO()
            SCOPE.pop('result', None)
            try:
                with contextlib.redirect_stdout(stdout):
                    exec(request['code'], SCOPE, SCOPE)
                response = {'success': True, 'result': SCOPE.get('result'), 'stdout': stdout.getvalue()}
            except Exception:
                response = {'success': False, 'error': traceback.format_exc(), 'stdout': stdout.getvalue()}
            connection.settimeout(3.0)
            connection.sendall(json.dumps(response, default=str).encode('utf-8') + b'\n')
            connection.close()
            del CLIENTS[connection]
        except BlockingIOError:
            pass
        except Exception:
            globals()['BRIDGE_LAST_ERROR'] = traceback.format_exc()
            unreal.log_error('THERMAL_BRIDGE: ' + traceback.format_exc())
            connection.close()
            CLIENTS.pop(connection, None)


CALLBACK = unreal.register_slate_post_tick_callback(tick)
exec((ROOT / 'Scripts/Thermal/file_bridge.py').read_text(encoding='utf-8'), SCOPE, SCOPE)
(OUTPUT / 'editor_ready.json').write_text(json.dumps({'pid': os.getpid(), 'port': PORT, 'project': str(ROOT)}), encoding='utf-8')
unreal.log('THERMAL_EDITOR_BRIDGE_READY port=' + str(PORT))
