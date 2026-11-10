"""Capture independent paired viewpoints in an already running diversity scene.

Never starts PIE, loads a map, or launches/closes an editor. Scripted source
motion and temperatures remain frozen throughout all viewpoint captures.
"""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import time

from capture_routes import ROOT, editor, _distance, _pose

SCENE = '05_combined_environment'
MAP = '/Game/CityPark/Maps/ThermalDiversity_05_CombinedEnvironment'


def validate_views(config, count=None):
    if config.get('scene') != SCENE:
        raise ValueError('View configuration must name scene ' + SCENE)
    views = config.get('views')
    if not isinstance(views, list) or not views:
        raise ValueError('views must be a nonempty list')
    identities, poses = set(), set()
    for view in views:
        if not isinstance(view, dict):
            raise ValueError('Each view must be an object')
        identity = view.get('id')
        if not isinstance(identity, str) or not identity.strip() or identity in identities:
            raise ValueError('View ids must be nonempty unique strings')
        identities.add(identity)
        if not isinstance(view.get('zone'), str) or not view['zone'].strip():
            raise ValueError('Each view needs a nonempty zone')
        for key in ('position_cm', 'target_cm'):
            value = view.get(key)
            if not isinstance(value, list) or len(value) != 3 or any(
                    isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
                raise ValueError(identity + ': ' + key + ' must contain three finite numbers')
        for key in ('azimuth_deg', 'elevation_deg'):
            value = view.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(identity + ': ' + key + ' must be finite')
        direction = [b - a for a, b in zip(view['position_cm'], view['target_cm'])]
        length = math.sqrt(sum(x*x for x in direction))
        if length < 1:
            raise ValueError(identity + ': position and target must differ by at least 1 cm')
        pose = tuple(round(x, 4) for x in view['position_cm']) + tuple(round(x / length, 6) for x in direction)
        if pose in poses:
            raise ValueError(identity + ': duplicate camera pose')
        poses.add(pose)
    if count is not None and (isinstance(count, bool) or not 1 <= count <= len(views)):
        raise ValueError('--count must be between 1 and the configured view count')
    return views[:count] if count is not None else views


def _snapshot():
    # All Unreal objects are function-local; only JSON primitives cross the bridge.
    return editor('''
def _angles_snapshot_local():
 report=diversity_snapshot()
 world=_diversity_world()
 report['all_thermal_sources']=[]
 if world:
  for source in unreal.GameplayStatics.get_all_actors_of_class(world,unreal.load_class(None,'/Script/AirSim.ThermalSource')):
   p=source.get_actor_location()
   report['all_thermal_sources'].append({'path':source.get_path_name(),'position_cm':[p.x,p.y,p.z],'temperature_k':float(source.get_editor_property('temperature_kelvin')),'enabled':bool(source.get_editor_property('enabled'))})
 report['all_thermal_sources'].sort(key=lambda s:s['path'])
 return report
try:
 result=_angles_snapshot_local()
finally:
 del _angles_snapshot_local
''', timeout=180)


def frozen_state(snapshot):
    return {key: snapshot[key] for key in ('id', 'world', 'elapsed', 'vehicles', 'all_thermal_sources')}


def _wait(predicate, description, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = _snapshot()
        if predicate(snapshot):
            return snapshot
        time.sleep(.15)
    raise TimeoutError(description)


def _check_scene(snapshot):
    if not snapshot.get('ready') or snapshot.get('id') != SCENE or MAP.rsplit('/', 1)[-1] not in snapshot.get('world', ''):
        raise RuntimeError('Open the combined environment map and start PIE before capture')


def _check_collision(position):
    # Sweep against visibility collision, including initial overlaps. This is a
    # geometry clearance check; the audit separately validates the saved images.
    code = '''
def _angles_collision_local(position):
 world=_diversity_world()
 cameras=unreal.GameplayStatics.get_all_actors_of_class(world,unreal.load_class(None,'/Script/AirSim.PIPCamera'))
 hit=unreal.SystemLibrary.sphere_trace_single(world,unreal.Vector(*position),unreal.Vector(position[0],position[1],position[2]+0.1),15.0,unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,cameras,unreal.DrawDebugTrace.NONE,True)
 return {'blocked':bool(hit),'radius_cm':15.0,'channel':'visibility','trace_complex':True}
try:
 result=_angles_collision_local(POSITION)
finally:
 del _angles_collision_local
'''.replace('POSITION', repr(position))
    result = editor(code)
    if result['blocked']:
        raise ValueError('Camera viewpoint intersects visibility collision: ' + repr(position))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--views', type=Path, default=ROOT / 'Config/SceneDiversity/viewpoints.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--count', type=int)
    parser.add_argument('--warmup-seconds', type=float, default=20.0,
                        help='Minimum simulated runtime elapsed before freezing')
    parser.add_argument('--port', type=int, default=41471)
    parser.add_argument('--vehicle', default='EveningSample')
    parser.add_argument('--validate-only', action='store_true', help='Validate JSON without contacting the editor')
    args = parser.parse_args()
    views = validate_views(json.loads(args.views.read_text(encoding='utf-8-sig')), args.count)
    if not math.isfinite(args.warmup_seconds) or args.warmup_seconds < 0:
        raise ValueError('--warmup-seconds must be finite and nonnegative')
    if args.validate_only:
        print(json.dumps({'status': 'passed', 'views': len(views), 'scene': SCENE}))
        return
    output = (args.output or ROOT / 'Saved/SceneDiversity/captures' / SCENE).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Output must be empty: ' + str(output))
    ready = _snapshot()
    _check_scene(ready)
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
    original_view = (ready['view_position_cm'], ready['view_target_cm'])
    output.mkdir(parents=True, exist_ok=True)
    manifest = {'scene': SCENE, 'map': MAP, 'capture_mode': 'independent_viewpoints',
                'status': 'partial', 'expected_count': len(views), 'expected_pairs': len(views),
                'views_config': str(args.views.resolve()), 'warmup_seconds': args.warmup_seconds,
                'editor_pid': ready.get('pid'), 'timestamp_tolerance_ns': 0,
                'pairing': 'RGB and IR in one paused RPC call; scripted motion suspended for entire run', 'pairs': []}
    manifest_path = output / 'manifest.json'
    def publish():
        temporary = manifest_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(manifest_path)
    publish()
    try:
        if ready['elapsed'] < args.warmup_seconds:
            editor('result=diversity_suspend(False)')
            client.simPause(False)
            ready = _wait(lambda s: s.get('elapsed', 0) >= args.warmup_seconds,
                          'Simulated warmup did not reach requested duration')
            _check_scene(ready)
        editor('result=diversity_suspend(True)')
        client.simPause(True)
        baseline = _snapshot()
        _check_scene(baseline)
        if not baseline.get('suspended') or not client.simIsPause():
            raise RuntimeError('Could not freeze the scene')
        if not baseline.get('vehicles') or not baseline.get('all_thermal_sources'):
            raise RuntimeError('Frozen scene has no configured vehicles or thermal sources')
        manifest['frozen_baseline'] = baseline
        publish()
        actual_poses = set()
        for index, view in enumerate(views):
            collision = _check_collision(view['position_cm'])
            teleport = editor('result=diversity_set_view(' + repr(view['position_cm']) + ',' + repr(view['target_cm']) + ',True)')
            if not teleport.get('cameras'):
                raise RuntimeError('No AirSim cameras to capture')
            # Only rendering/settling runs unpaused; scripted transforms and heat
            # settings remain suspended continuously, including between views.
            client.simPause(False)
            settle_start = time.monotonic()
            settled = _wait(lambda s: s.get('tick', 0) >= teleport['tick'] + 6 and time.monotonic() - settle_start >= .25,
                            'Camera did not settle for at least five viewport ticks', timeout=30)
            settle_seconds = time.monotonic() - settle_start
            client.simPause(True)
            before = _snapshot()
            _check_scene(before)
            if not client.simIsPause() or not before.get('suspended') or frozen_state(before) != frozen_state(baseline):
                raise RuntimeError('Frozen source state changed between viewpoints')
            raw = client.client.call('simGetImages', [airsim.ImageRequest('0', kind, False, True) for kind in (0, 12)], args.vehicle)
            if len(raw) != 2:
                raise RuntimeError('Both RGB and IR responses are required')
            row = {'index': index, 'view_id': view['id'], 'zone': view['zone'],
                   'requested_camera_cm': view['position_cm'], 'requested_target_cm': view['target_cm'],
                   'azimuth_deg': view['azimuth_deg'], 'elevation_deg': view['elevation_deg'],
                   'collision_check': collision, 'settled_ticks': settled['tick'] - teleport['tick'],
                   'settle_wall_seconds': settle_seconds,
                   'snapshot': before, 'images': {}}
            for channel, data in zip(('rgb', 'ir'), raw):
                response = airsim.ImageResponse.from_msgpack(data)
                if response.message or (response.width, response.height) != (1280, 720) or not response.image_data_uint8:
                    raise RuntimeError('Empty or invalid ' + channel + ' sensor response: ' + str(response.message))
                pose = _pose(response)
                if not all(math.isfinite(x) for values in pose.values() for x in values):
                    raise RuntimeError('Nonfinite sensor pose')
                with Image.open(io.BytesIO(response.image_data_uint8)) as source:
                    source.load()
                    if source.size != (1280, 720):
                        raise RuntimeError('Decoded image must be exactly 1280x720')
                    frame = source.convert('RGB')
                filename = f'{index:03d}_{channel}.png'
                frame.save(output / filename)
                row['images'][channel] = {'file': filename, 'size': [1280, 720],
                    'time_stamp': int(response.time_stamp), 'pose': pose,
                    'sha256': hashlib.sha256((output / filename).read_bytes()).hexdigest()}
            rgb, ir = (row['images'][channel] for channel in ('rgb', 'ir'))
            if _distance(rgb['pose']['position_m'], ir['pose']['position_m']) > 1e-4 or min(
                    _distance(rgb['pose']['orientation_xyzw'], ir['pose']['orientation_xyzw']),
                    _distance(rgb['pose']['orientation_xyzw'], [-x for x in ir['pose']['orientation_xyzw']])) > 1e-4:
                raise RuntimeError('RGB and IR sensor poses differ')
            row['timestamp_delta_ns'] = abs(rgb['time_stamp'] - ir['time_stamp'])
            if rgb['time_stamp'] <= 0 or row['timestamp_delta_ns']:
                raise RuntimeError('RGB and IR must have identical positive timestamps')
            actual_key = tuple(round(x, 5) for x in rgb['pose']['position_m']) + tuple(round(x, 6) for x in rgb['pose']['orientation_xyzw'])
            if actual_key in actual_poses:
                raise RuntimeError('Duplicate actual sensor viewpoint')
            actual_poses.add(actual_key)
            after = _snapshot()
            if not client.simIsPause() or not after.get('suspended') or frozen_state(after) != frozen_state(baseline):
                raise RuntimeError('Source state changed during paired capture')
            row['after_snapshot'] = after
            row['frozen_scene_verified'] = True
            (output / f'{index:03d}_metadata.json').write_text(json.dumps(row, indent=2, allow_nan=False), encoding='utf-8')
            manifest['pairs'].append(row)
            publish()
            print(json.dumps({'view': view['id'], 'pair': index + 1, 'of': len(views)}), flush=True)
        manifest['status'] = 'passed'
        publish()
    except BaseException as error:
        manifest['status'] = 'failed'
        manifest['error'] = str(error)
        publish()
        raise
    finally:
        failures = []
        # Each restoration is attempted even if a preceding operation fails.
        for name, operation in (
                ('pause_before_restore', lambda: client.simPause(True)),
                ('view', lambda: editor('result=diversity_set_view(' + repr(original_view[0]) + ',' + repr(original_view[1]) + ',True)')),
                ('suspension', lambda: editor('result=diversity_suspend(' + repr(was_suspended) + ')')),
                ('pause', lambda: client.simPause(was_paused))):
            try:
                operation()
            except Exception as error:
                failures.append(name + ': ' + str(error))
        rpc_tcp.BaseSocket.__init__ = original_init
        manifest['restoration_errors'] = failures
        if failures and manifest['status'] == 'passed':
            manifest['status'] = 'failed'
            manifest['error'] = 'State restoration failed'
        publish()
        if failures:
            print(json.dumps({'restoration_errors': failures}), flush=True)
    print(json.dumps({'status': manifest['status'], 'pairs': len(manifest['pairs']), 'manifest': str(manifest_path)}))
    if manifest['status'] != 'passed':
        raise RuntimeError(manifest.get('error', 'Capture failed'))


if __name__ == '__main__':
    main()
