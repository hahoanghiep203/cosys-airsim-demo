"""PIE-only scene motion and thermal states; persistent data contains no actors."""
import json
import math
import os
import time
from pathlib import Path
import unreal

DIVERSITY_ROOT = Path(unreal.Paths.project_dir()).resolve()
DIVERSITY_STATE = {}
DIVERSITY_SCENES = []


def _diversity_clean_camera(camera):
    """Use an undistorted RGB projection matching the geometry-based IR camera."""
    components = list(camera.get_components_by_class(unreal.CameraComponent) or [])
    components.extend(list(camera.get_components_by_class(unreal.SceneCaptureComponent2D) or []))
    removed = 0
    for component in components:
        settings = component.get_editor_property('post_process_settings').copy()
        blendables = settings.get_editor_property('weighted_blendables')
        old = list(blendables.get_editor_property('array') or [])
        filtered = [b for b in old if not b.object or 'CameraDistortion' not in b.object.get_name()]
        if len(filtered) != len(old):
            removed += len(old) - len(filtered)
            blendables.set_editor_property('array', filtered)
            settings.set_editor_property('weighted_blendables', blendables)
            component.set_editor_property('post_process_settings', settings, notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
    return removed


def _diversity_world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()


def _diversity_scene(world):
    if not world:
        return None
    path = world.get_path_name()
    return next((s for s in DIVERSITY_SCENES if s['map'].split('/')[-1] in path), None)


def _diversity_sources(actor):
    for component in actor.get_components_by_class(unreal.ChildActorComponent):
        source = component.get_editor_property('child_actor')
        if source and isinstance(source, unreal.ThermalSource):
            yield component.get_name(), source


def _diversity_temperatures(actor, vehicle, scene, elapsed):
    ambient = float(scene['ambient_k'])
    state = vehicle.get('state', 'parked')
    if state == 'driving':
        initial = float(vehicle.get('tire_initial_k', ambient + 3.0))
        target = float(vehicle.get('tire_target_k', 308.15))
        tire = target + (initial - target) * math.exp(-elapsed / 20.0)
        hood = float(vehicle.get('hood_k', 353.15))
        headlight = float(vehicle.get('headlight_k', 333.15))
    elif state in ('cooling', 'recently_parked'):
        decay = math.exp(-elapsed / 90.0)
        tire = ambient + (float(vehicle.get('tire_initial_k', 300.15)) - ambient) * decay
        hood = ambient + (float(vehicle.get('hood_k', 333.15)) - ambient) * decay
        headlight = ambient
    else:
        tire = hood = headlight = ambient
    light_states = DIVERSITY_STATE.setdefault('light_states', {})
    light_key = actor.get_path_name()
    if light_states.get(light_key) != (state == 'driving'):
        for light in actor.get_components_by_class(unreal.SpotLightComponent):
            light.set_visibility(state == 'driving', True)
        light_states[light_key] = state == 'driving'
    values = {}
    for name, source in _diversity_sources(actor):
        lower = name.lower()
        if 'tire' in lower:
            value, enabled = tire, state != 'parked'
        elif 'hood' in lower:
            value, enabled = hood, state != 'parked'
        elif 'headlight' in lower or 'lightheat' in lower:
            value, enabled = headlight, state == 'driving'
        else:
            continue
        source.set_editor_property('temperature_kelvin', value, notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
        source.set_source_enabled(enabled)
        values[name] = {'kelvin': value, 'enabled': enabled}
    return values


def _diversity_set_cameras(world):
    position = unreal.Vector(*DIVERSITY_STATE['view_position_cm'])
    target = unreal.Vector(*DIVERSITY_STATE['view_target_cm'])
    rotation = unreal.MathLibrary.find_look_at_rotation(position, target)
    paths = DIVERSITY_STATE.get('camera_paths', [])
    if not paths:
        cameras = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.load_class(None, '/Script/AirSim.PIPCamera'))
        paths = [camera.get_path_name() for camera in cameras]
        DIVERSITY_STATE['camera_paths'] = paths
    cameras = [unreal.find_object(None, path) for path in paths]
    cameras = [camera for camera in cameras if camera]
    for camera in cameras:
        camera.set_actor_location_and_rotation(position, rotation, False, True)
    return len(cameras)


def diversity_suspend(enabled=True):
    """Suspend scripted motion before pausing captures, including Slate callbacks."""
    DIVERSITY_STATE['suspended'] = bool(enabled)
    return {'suspended': DIVERSITY_STATE['suspended'], 'elapsed': DIVERSITY_STATE.get('elapsed', 0)}


def diversity_set_view(position_cm, target_cm, suspend=True):
    world = _diversity_world()
    if not world or not DIVERSITY_STATE.get('ready'):
        raise RuntimeError('Scene diversity PIE runtime is not ready')
    DIVERSITY_STATE['view_position_cm'] = list(position_cm)
    DIVERSITY_STATE['view_target_cm'] = list(target_cm)
    DIVERSITY_STATE['suspended'] = bool(suspend)
    count = _diversity_set_cameras(world)
    return {'cameras': count, 'tick': DIVERSITY_STATE['tick']}


def diversity_snapshot():
    """Read current transforms and heat-source values without retaining wrappers."""
    world = _diversity_world()
    scene = _diversity_scene(world)
    report = dict(DIVERSITY_STATE)
    report['vehicles'] = []
    if not world or not scene:
        return report
    configured = {v['label']: v for v in scene.get('vehicles', [])}
    for label, path in DIVERSITY_STATE.get('actor_paths', {}).items():
        actor = unreal.find_object(None, path)
        if not actor or label not in configured:
            continue
        point = actor.get_actor_location()
        rotation = actor.get_actor_rotation()
        sources = []
        for name, source in _diversity_sources(actor):
            location = source.get_actor_location()
            sources.append({'name': name, 'position_cm': [location.x, location.y, location.z],
                            'temperature_k': float(source.get_editor_property('temperature_kelvin')),
                            'enabled': bool(source.get_editor_property('enabled'))})
        report['vehicles'].append({'label': label, 'model': configured[label]['model'],
                                  'state': configured[label].get('state', 'parked'),
                                  'position_cm': [point.x, point.y, point.z],
                                  'yaw_deg': rotation.yaw, 'sources': sources})
    return report


def _diversity_write():
    output = DIVERSITY_ROOT / 'Saved/SceneDiversity/runtime.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(diversity_snapshot(), indent=2), encoding='utf-8')
    temporary.replace(output)


def _diversity_tick(_delta):
    global DIVERSITY_STATE
    world = _diversity_world()
    scene = _diversity_scene(world)
    if not scene:
        if DIVERSITY_STATE.get('world'):
            DIVERSITY_STATE = {'pid': os.getpid(), 'ready': False}
        return
    key = world.get_path_name()
    now = float(unreal.GameplayStatics.get_time_seconds(world))
    if DIVERSITY_STATE.get('world') != key:
        DIVERSITY_STATE = {'pid': os.getpid(), 'world': key, 'id': scene['id'], 'ready': False,
                           'elapsed': 0.0, 'last_world_time': now, 'tick': 0,
                           'suspended': False, 'last_publish': 0.0,
                           'view_position_cm': list(scene['preview_position_cm']),
                           'view_target_cm': list(scene['preview_target_cm'])}
    DIVERSITY_STATE['tick'] += 1
    step = max(0.0, now - DIVERSITY_STATE['last_world_time'])
    DIVERSITY_STATE['last_world_time'] = now
    # Initialization needs the vehicle children and camera to finish BeginPlay.
    if not DIVERSITY_STATE['ready'] and now < 1.0:
        return
    configured = {v['label']: v for v in scene.get('vehicles', [])}
    found = {}
    if DIVERSITY_STATE.get('actor_paths'):
        for label, path in DIVERSITY_STATE['actor_paths'].items():
            actor = unreal.find_object(None, path)
            if actor:
                found[label] = actor
    else:
        for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
            if actor.get_actor_label() in configured:
                found[actor.get_actor_label()] = actor
        if len(found) == len(configured):
            DIVERSITY_STATE['actor_paths'] = {label: actor.get_path_name() for label, actor in found.items()}
    missing = sorted(set(configured) - set(found))
    if missing:
        DIVERSITY_STATE['error'] = 'Missing configured vehicles: ' + ', '.join(missing)
        if time.monotonic() - DIVERSITY_STATE['last_publish'] > 1:
            _diversity_write(); DIVERSITY_STATE['last_publish'] = time.monotonic()
        return
    paused = bool(unreal.GameplayStatics.is_game_paused(world))
    if DIVERSITY_STATE['ready'] and not paused and not DIVERSITY_STATE['suspended']:
        DIVERSITY_STATE['elapsed'] += step
    elapsed = DIVERSITY_STATE['elapsed']
    # The native heat solver advances at 10 Hz. Avoid reflecting unchanged source
    # settings at viewport rate; vehicle/camera transforms still update every tick.
    update_heat = not DIVERSITY_STATE['ready'] or elapsed - DIVERSITY_STATE.get('last_heat_update', -1) >= .1
    for label, actor in found.items():
        vehicle = configured[label]
        if vehicle.get('state') == 'driving' and vehicle.get('motion_enabled', True) and not paused and not DIVERSITY_STATE['suspended']:
            start, end = vehicle['start_cm'], vehicle['end_cm']
            duration = max(1.0, float(vehicle.get('duration_seconds', 40.0)))
            phase = (elapsed / duration) % 2.0
            fraction = phase if phase <= 1 else 2 - phase
            position = [a + (b - a) * fraction for a, b in zip(start, end)]
            direction = 1 if phase <= 1 else -1
            yaw = math.degrees(math.atan2((end[1] - start[1]) * direction, (end[0] - start[0]) * direction))
            yaw += float(vehicle.get('yaw_offset_deg', 0))
            actor.set_actor_location_and_rotation(unreal.Vector(*position), unreal.Rotator(0, yaw, 0), False, True)
        if update_heat:
            _diversity_temperatures(actor, vehicle, scene, elapsed)
    if update_heat:
        DIVERSITY_STATE['last_heat_update'] = elapsed
    if not DIVERSITY_STATE['ready']:
        if scene.get('capture_mode')=='independent_viewpoints':
            exec((DIVERSITY_ROOT/'Scripts/SceneDiversity/temperature_policy.py').read_text(),globals(),globals())
            DIVERSITY_STATE['temperature_policy']=apply_temperature_policy(scene,True)
            exec((DIVERSITY_ROOT/'Scripts/SceneDiversity/align_sources.py').read_text(),globals(),globals())
            DIVERSITY_STATE['source_alignment']=apply_source_alignment(True)
        for fixture in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
            if fixture.get_actor_label().startswith('Sample_WarmLamp'):
                for light in fixture.get_components_by_class(unreal.PointLightComponent):
                    light.set_temperature(float(scene['lamp_kelvin']))
                    light.set_intensity(float(scene['lamp_cd']))
        DIVERSITY_STATE['removed_distortion_blendables'] = sum(
            _diversity_clean_camera(camera) for camera in
            unreal.GameplayStatics.get_all_actors_of_class(world, unreal.load_class(None, '/Script/AirSim.PIPCamera')))
        if scene.get('capture_mode')=='independent_viewpoints':
            exec((DIVERSITY_ROOT/'Scripts/SceneDiversity/rgb_camera.py').read_text(),globals(),globals())
            DIVERSITY_STATE['rgb_camera_profile']=apply_rgb_camera_profile()
        for hud in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.load_class(None, '/Script/AirSim.SimHUD')):
            hud.set_thermal_review_viewport_size(1280, 720)
        if not _diversity_set_cameras(world):
            return
        sources = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.load_class(None, '/Script/AirSim.ThermalSource'))
        if not sources:
            raise RuntimeError('No thermal sources in diversity scene')
        for source in sources:
            class_name = source.get_class().get_name()
            if 'SampleCounterHeat' in class_name:
                source.set_editor_property('temperature_kelvin', float(scene.get('counter_k', 363.15)), notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
            elif 'SampleLampHeat' in class_name:
                source.set_editor_property('temperature_kelvin', float(scene.get('lamp_heat_k', 328.15)), notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
        # Private combined-environment fixtures retain their local Kelvin/heat presets.
        for fixture in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
            zone=next((z for z in scene.get('zones',[]) if fixture.get_actor_label().startswith('Combined_'+z['id']+'_')),None)
            if not zone or not any(fixture.get_actor_label()==f['label'] for f in scene.get('fixtures',[])):
                continue
            for light in fixture.get_components_by_class(unreal.PointLightComponent):
                light.set_temperature(float(zone['lamp_kelvin']));light.set_intensity(float(zone['lamp_cd']))
            for name,source in _diversity_sources(fixture):
                value=zone['counter_k'] if 'CounterHeat' in source.get_class().get_name() else zone['lamp_heat_k']
                source.set_editor_property('temperature_kelvin',float(value),notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
        if scene.get('capture_mode')=='independent_viewpoints':
            sources[0].reset_thermal_state()
        sources[0].prewarm(float(scene.get('warmup_seconds', 25.0)))
        DIVERSITY_STATE['ready'] = True
        DIVERSITY_STATE['source_count'] = len(sources)
        DIVERSITY_STATE['last_world_time'] = float(unreal.GameplayStatics.get_time_seconds(world))
        unreal.log('SCENE_DIVERSITY_READY ' + scene['id'])
    _diversity_set_cameras(world)
    if time.monotonic() - DIVERSITY_STATE['last_publish'] > 1:
        _diversity_write(); DIVERSITY_STATE['last_publish'] = time.monotonic()


def diversity_install():
    global DIVERSITY_SCENES, DIVERSITY_CALLBACK
    DIVERSITY_SCENES = json.loads((DIVERSITY_ROOT / 'Config/SceneDiversity/scenes.json').read_text(encoding='utf-8-sig'))['scenes']
    if 'DIVERSITY_CALLBACK' in globals():
        unreal.unregister_slate_post_tick_callback(DIVERSITY_CALLBACK)
    DIVERSITY_CALLBACK = unreal.register_slate_post_tick_callback(_diversity_tick)
    return {'installed': True, 'scenes': [s['id'] for s in DIVERSITY_SCENES]}
