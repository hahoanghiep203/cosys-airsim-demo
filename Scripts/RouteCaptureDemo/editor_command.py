"""Invoke the isolated integration-test editor; never used for product control."""
import json
from pathlib import Path
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / 'Saved/RouteCaptureReview/control'

def editor(code, timeout=120):
    CONTROL.mkdir(parents=True, exist_ok=True)
    identity = uuid.uuid4().hex
    request = CONTROL / (identity + '.request.json')
    response = CONTROL / (identity + '.response.json')
    temp = request.with_suffix('.tmp')
    temp.write_text(json.dumps({'code':code}), encoding='utf-8')
    temp.replace(request)
    deadline = time.monotonic() + timeout
    while not response.exists():
        if time.monotonic() > deadline:
            raise TimeoutError('Editor test command timed out: ' + identity)
        time.sleep(.1)
    while True:
        try:
            data = json.loads(response.read_text(encoding='utf-8'))
            break
        except (PermissionError,FileNotFoundError):
            if time.monotonic()>deadline:
                raise TimeoutError('Editor response could not be read: '+identity)
            time.sleep(.02)
    if not data['success']:
        raise RuntimeError(data.get('error', data))
    return data.get('result')

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    print(json.dumps(editor(args.file.read_text(encoding='utf-8')), indent=2))
