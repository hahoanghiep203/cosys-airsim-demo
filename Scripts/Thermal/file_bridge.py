"""File-based control channel for deterministic, reviewable editor tests."""
import traceback

CONTROL = OUTPUT / 'control'
CONTROL.mkdir(parents=True, exist_ok=True)
FILE_SCOPE = globals()
FILE_BUSY = False

def thermal_file_tick(_delta):
    global FILE_BUSY
    # Asset saving can pump Slate again. Do not execute the same request twice.
    if FILE_BUSY: return
    for request_path in sorted(CONTROL.glob('*.request.json'))[:1]:
        FILE_BUSY = True
        response_path = request_path.with_name(request_path.name.replace('.request.json', '.response.json'))
        try:
            request = json.loads(request_path.read_text(encoding='utf-8'))
            FILE_SCOPE.pop('result', None)
            try:
                exec(request['code'], FILE_SCOPE, FILE_SCOPE)
                response = {'success': True, 'result': FILE_SCOPE.get('result')}
            except Exception:
                response = {'success': False, 'error': traceback.format_exc()}
            temporary = response_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(response, default=str), encoding='utf-8')
            temporary.replace(response_path)
        finally:
            request_path.unlink(missing_ok=True)
            FILE_BUSY = False

FILE_CALLBACK = unreal.register_slate_post_tick_callback(thermal_file_tick)
result = 'file control channel ready'
