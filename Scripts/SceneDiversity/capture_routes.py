"""Capture a configured route from an already open diversity map; never load maps."""
import argparse
import io
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Scripts/RouteCaptureDemo'))
from editor_command import editor


def _pose(response):
    p, q = response.camera_position, response.camera_orientation
    return {'position_m': [float(p.x_val), float(p.y_val), float(p.z_val)],
            'orientation_xyzw': [float(q.x_val), float(q.y_val), float(q.z_val), float(q.w_val)]}


def _distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _route_position(points, fraction):
    if len(points) < 2:
        raise ValueError('camera_route_cm requires at least two distinct points')
    lengths = [_distance(a, b) for a, b in zip(points, points[1:])]
    remaining = max(0.0, min(1.0, fraction)) * sum(lengths)
    if not sum(lengths):
        raise ValueError('Camera route has no translation')
    for a, b, length in zip(points, points[1:], lengths):
        if remaining <= length and length:
            return [x + (y - x) * remaining / length for x, y in zip(a, b)]
        remaining -= length
    return list(points[-1])


def _snapshot():
    return editor('result=diversity_snapshot()', timeout=180)


def _wait(predicate, description, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = _snapshot()
        if predicate(snapshot):
            return snapshot
        time.sleep(.15)
    raise TimeoutError(description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', required=True)
    parser.add_argument('--count', type=int)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--motion-step-seconds', type=float, default=1.0)
    parser.add_argument('--port', type=int, default=41471)
    parser.add_argument('--vehicle', default='EveningSample')
    args = parser.parse_args()
    scenes = json.loads((ROOT / 'Config/SceneDiversity/scenes.json').read_text(encoding='utf-8-sig'))['scenes']
    scene = next(s for s in scenes if s['id'] == args.scene)
    if scene.get('capture_mode')=='independent_viewpoints':
        raise ValueError('Use capture_angles.py for independent still viewpoints')
    count = args.count if args.count is not None else int(scene['captures'])
    if not 2 <= count <= 50 or args.motion_step_seconds <= 0:
        raise ValueError('Use 2..50 pairs and a positive simulated motion step')
    output = args.output or ROOT / 'Saved/SceneDiversity/captures' / args.scene
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Capture folder is not empty; use --output for a new run: ' + str(output))
    output.mkdir(parents=True, exist_ok=True)
    # Runtime must be installed by startup; install explicitly if this editor
    # already opened the map through the generic performance launcher.
    status = editor("""
if 'diversity_snapshot' not in globals():
 exec((ROOT/'Scripts/SceneDiversity/runtime.py').read_text(encoding='utf-8-sig'),globals(),globals())
 diversity_install()
world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if not world:
 unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_begin_play()
result={'pid':__import__('os').getpid(),'started_pie':not bool(world)}
""", timeout=180)
    ready = _wait(lambda s: s.get('ready') and s.get('id') == args.scene and s.get('pid') == status['pid'], 'Configured scene did not become ready')

    import airsim
    import msgpack
    import msgpackrpc.transport.tcp as rpc_tcp
    from PIL import Image
    original_init = rpc_tcp.BaseSocket.__init__
    def large_frame_socket(self, stream, encodings):
        original_init(self, stream, encodings)
        self._unpacker = msgpack.Unpacker(encoding=encodings[1], max_buffer_size=128*1024*1024,
                                        max_bin_len=64*1024*1024, max_str_len=64*1024*1024,
                                        max_array_len=4*1024*1024)
    rpc_tcp.BaseSocket.__init__ = large_frame_socket
    client = airsim.VehicleClient(ip='127.0.0.1', port=args.port, timeout_value=180)
    was_paused = bool(client.simIsPause())
    was_suspended = bool(ready.get('suspended', False))
    manifest = {'scene': args.scene, 'map': scene['map'], 'status': 'partial', 'expected_pairs': count,
                'pairing': 'RGB and IR captured while simulation and scripted movement are frozen',
                'editor_pid': status['pid'], 'pairs': []}
    manifest_path = output / 'manifest.json'
    def publish():
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    publish()
    try:
        client.simPause(False)
        editor('result=diversity_suspend(False)')
        previous_elapsed = ready['elapsed']
        for index in range(count):
            advanced = _wait(lambda s: s.get('id') == args.scene and s.get('elapsed', 0) >= previous_elapsed + args.motion_step_seconds,
                             'Scripted driving motion did not advance')
            position = _route_position(scene['camera_route_cm'], index / (count - 1))
            target = scene.get('camera_target_cm', scene['preview_target_cm'])
            view = editor('result=diversity_set_view(' + repr(position) + ',' + repr(target) + ',True)')
            if not view['cameras']:
                raise RuntimeError('No AirSim camera to capture')
            # Freeze scripted transforms first and render at least two frames
            # from this pose before stopping the world for paired readback.
            _wait(lambda s: s.get('tick', 0) >= view['tick'] + 3, 'New camera pose did not render', timeout=30)
            client.simPause(True)
            before = _snapshot()
            if not client.simIsPause():
                raise RuntimeError('World pause failed before paired capture')
            raw = client.client.call('simGetImages', [airsim.ImageRequest('0', kind, False, True) for kind in (0, 12)], args.vehicle)
            if len(raw) != 2:
                raise RuntimeError('Both RGB and IR responses are required')
            responses = [airsim.ImageResponse.from_msgpack(data) for data in raw]
            row = {'index': index, 'requested_camera_cm': position, 'snapshot': before, 'images': {}}
            poses = []
            for channel, response in zip(('rgb', 'ir'), responses):
                if response.message or (response.width, response.height) != (1280, 720):
                    raise RuntimeError('Invalid ' + channel + ' response: ' + str(response.message))
                frame = Image.open(io.BytesIO(response.image_data_uint8)).convert('RGB')
                if frame.size != (1280, 720):
                    raise RuntimeError('Decoded dimensions differ from sensor response')
                filename = f'{index:03d}_{channel}.png'
                frame.save(output / filename)
                pose = _pose(response); poses.append(pose)
                row['images'][channel] = {'file': filename, 'size': [response.width, response.height],
                                          'time_stamp': int(response.time_stamp), 'pose': pose}
            if _distance(poses[0]['position_m'], poses[1]['position_m']) > 1e-4 or _distance(poses[0]['orientation_xyzw'], poses[1]['orientation_xyzw']) > 1e-4:
                raise RuntimeError('RGB and IR sensor poses differ')
            after = _snapshot()
            if not client.simIsPause() or before['vehicles'] != after['vehicles'] or before['elapsed'] != after['elapsed']:
                raise RuntimeError('Scene transforms changed during frozen paired capture')
            row['timestamp_delta_ns'] = abs(row['images']['rgb']['time_stamp'] - row['images']['ir']['time_stamp'])
            row['frozen_scene_verified'] = True
            (output / f'{index:03d}_metadata.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
            manifest['pairs'].append(row); publish()
            print(json.dumps({'scene': args.scene, 'pair': index + 1, 'of': count}), flush=True)
            previous_elapsed = after['elapsed']
            client.simPause(False)
            editor('result=diversity_suspend(False)')
        first, last = manifest['pairs'][0], manifest['pairs'][-1]
        manifest['camera_translation_m'] = _distance(first['images']['rgb']['pose']['position_m'], last['images']['rgb']['pose']['position_m'])
        start_vehicles = {v['label']: v for v in first['snapshot']['vehicles']}
        manifest['driving_displacement_cm'] = {v['label']: _distance(start_vehicles[v['label']]['position_cm'], v['position_cm'])
                                               for v in last['snapshot']['vehicles'] if v['state'] == 'driving'}
        if manifest['camera_translation_m'] < .01:
            raise RuntimeError('Captured sensor camera did not move along its route')
        if not manifest['driving_displacement_cm'] or not all(d > 1.0 for d in manifest['driving_displacement_cm'].values()):
            raise RuntimeError('Configured driving cars did not move between captured frames')
        manifest['status'] = 'passed'; publish()
    except Exception as error:
        manifest['status'] = 'failed'; manifest['error'] = str(error); publish()
        raise
    finally:
        try:
            client.simPause(was_paused)
        finally:
            editor('result=diversity_suspend(' + repr(was_suspended) + ')')
    print(json.dumps({'status': manifest['status'], 'pairs': len(manifest['pairs']), 'manifest': str(manifest_path)}, indent=2))


if __name__ == '__main__':
    main()
