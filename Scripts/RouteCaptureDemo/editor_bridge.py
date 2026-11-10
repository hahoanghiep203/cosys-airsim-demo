"""Project-local integration-test harness; not used by the add-on UI/runtime."""
import json
import os
from pathlib import Path
import traceback
import unreal

ROOT = Path(unreal.Paths.project_dir()).resolve()
OUTPUT = ROOT / 'Saved' / 'RouteCaptureReview'
CONTROL = OUTPUT / 'control'
CONTROL.mkdir(parents=True, exist_ok=True)
SCOPE = {'unreal': unreal, 'ROOT': ROOT, 'OUTPUT': OUTPUT, 'Path': Path, 'json': json}
BUSY = False
PENDING = None

def publish_pending():
    global PENDING
    if PENDING is None:
        return True
    request, response, answer = PENDING
    temporary = response.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(answer, default=str), encoding='utf-8')
        temporary.replace(response)
        request.unlink(missing_ok=True)
    except (PermissionError, FileNotFoundError):
        return False
    PENDING = None
    return True

def route_demo_tick(_delta):
    global BUSY, PENDING
    if BUSY:
        return
    if not publish_pending():
        return
    for request in sorted(CONTROL.glob('*.request.json'))[:1]:
        BUSY = True
        response = request.with_name(request.name.replace('.request.json', '.response.json'))
        try:
            try:
                payload = json.loads(request.read_text(encoding='utf-8'))
            except (PermissionError, FileNotFoundError):
                # Keep the request: a scanner/reader may temporarily deny access.
                return
            except Exception:
                PENDING = (request, response, {'success':False, 'error':traceback.format_exc()})
                publish_pending()
                return
            SCOPE.pop('result', None)
            try:
                exec(payload['code'], SCOPE, SCOPE)
                answer = {'success': True, 'result': SCOPE.get('result')}
            except Exception:
                answer = {'success': False, 'error': traceback.format_exc()}
            # Retry publication without ever executing the command twice.
            PENDING = (request, response, answer)
            publish_pending()
        finally:
            BUSY = False

CALLBACK = unreal.register_slate_post_tick_callback(route_demo_tick)
(OUTPUT / 'editor_ready.json').write_text(json.dumps({'pid': os.getpid(), 'project': str(ROOT)}), encoding='utf-8')
unreal.log('ROUTE_DEMO_BRIDGE_READY')
