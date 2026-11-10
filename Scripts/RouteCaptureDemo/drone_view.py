"""Live drone view: independent UE renders following actual RouteDrone camera 0.

Executed in the owned editor bridge namespace after Play starts. This recorder
never enables, captures, reparents, or changes a target on an AirSim component.
"""
import json
import math
import os
from pathlib import Path
import time
import traceback
import unreal

# Re-execution must not leave a second recorder ticking in the same namespace.
_previous_callback=globals().get('DRONE_VIEW_CALLBACK')
if _previous_callback is not None:
    unreal.unregister_slate_post_tick_callback(_previous_callback)

DRONE_VIEW_CALLBACK=None
DRONE_VIEW_ACTOR=None
DRONE_VIEW_COMPONENT=None
DRONE_VIEW_TARGET=None
DRONE_VIEW_RECORDING=False
DRONE_VIEW_BUSY=False
DRONE_VIEW_DIRECTORY=None
DRONE_VIEW_FRAMES=[]
DRONE_VIEW_ERRORS=[]
DRONE_VIEW_VISIBILITY_NOTES=[]
DRONE_VIEW_SENSOR_TARGET_FORMAT=None
DRONE_VIEW_SENSOR_TARGET_GAMMA=None
DRONE_VIEW_NEXT_TIME=None
DRONE_VIEW_LAST_TIME=None
DRONE_VIEW_WIDTH=640
DRONE_VIEW_HEIGHT=480
DRONE_VIEW_INTERVAL=.1
DRONE_VIEW_TOLERANCES={'position_cm':.01,'angle_deg':.01,'fov_deg':.001}
DRONE_VIEW_SOURCE_NOTE=('Live drone view: real independent Unreal SceneCapture2D renders mirroring actual '
    'RPC camera 0 world pose, FOV, projection, initial postprocess and actor exclusions. '
    'Own render target and temporal history; not replayed RPC RGB images or a same-render-frame claim.')


def _drone_view_sensor():
    game=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if not game:
        raise RuntimeError('Play must be active for live drone view')
    pawns=[a for a in unreal.GameplayStatics.get_all_actors_of_class(game,unreal.Pawn)
           if a.get_name()=='RouteDrone']
    if len(pawns)!=1:
        raise RuntimeError('Expected exactly one actual RouteDrone pawn')
    cls=unreal.load_class(None,'/Script/AirSim.PIPCamera')
    cameras=[a for a in unreal.GameplayStatics.get_all_actors_of_class(game,cls)
             if a.get_attach_parent_actor()==pawns[0] and a.get_parent_component() is None]
    # PawnSimApi::createCamerasFromSettings replaces map key "0" with a new
    # direct-root attached camera for the demo's single explicit Cameras["0"].
    # FrontCenterCamera still owns alias front_center and is not the replaced 0.
    if len(cameras)!=1:
        raise RuntimeError('Cannot identify RPC camera 0 uniquely: expected one configured direct-root PIPCamera; '
                           'found '+str([a.get_path_name() for a in cameras]))
    captures=[c for c in cameras[0].get_components_by_class(unreal.SceneCaptureComponent2D)
              if c.get_name()=='SceneCaptureComponent']
    if len(captures)!=1:
        raise RuntimeError('Selected PIPCamera has no unique SceneCaptureComponent RGB sensor')
    return game,pawns[0],cameras[0],captures[0]


DRONE_VIEW_WORLD,DRONE_VIEW_PAWN,DRONE_VIEW_SENSOR_ACTOR,DRONE_VIEW_SENSOR=_drone_view_sensor()
DRONE_VIEW_SELECTION_NOTE=('PawnSimApi configured camera override: sole direct-root PIPCamera on RouteDrone '
                          'for explicit demo Cameras[0], RGB component SceneCaptureComponent')


def _drone_view_vector(v):
    return [float(v.x),float(v.y),float(v.z)]


def _drone_view_rotation(r):
    return [float(r.pitch),float(r.yaw),float(r.roll)]


def _drone_view_angle(a,b):
    trace=0.
    for getter in ('get_forward_vector','get_right_vector','get_up_vector'):
        u=_drone_view_vector(getattr(a,getter)())
        v=_drone_view_vector(getattr(b,getter)())
        trace+=sum(x*y for x,y in zip(u,v))
    return math.degrees(math.acos(max(-1.,min(1.,(trace-1.)/2.))))


def _drone_view_visibility():
    sensor=DRONE_VIEW_SENSOR
    markers=list(unreal.GameplayStatics.get_all_actors_with_tag(DRONE_VIEW_WORLD,'RouteCaptureMarker'))
    hidden=list(sensor.get_editor_property('hidden_actors'))
    for marker in markers:
        if marker not in hidden:
            hidden.append(marker)
    values=[('hidden_actors',hidden),('show_only_actors',list(sensor.get_editor_property('show_only_actors')))]
    for prop in ('hidden_components','show_only_components'):
        try:
            value=list(sensor.get_editor_property(prop))
            list(DRONE_VIEW_COMPONENT.get_editor_property(prop))
        except Exception:
            note='UE Python does not expose '+prop+'; actor exclusions and all route-marker exclusions are applied independently.'
            if note not in DRONE_VIEW_VISIBILITY_NOTES:
                DRONE_VIEW_VISIBILITY_NOTES.append(note)
            continue
        values.append((prop,value))
    for prop,value in values:
        if list(DRONE_VIEW_COMPONENT.get_editor_property(prop))!=value:
            DRONE_VIEW_COMPONENT.set_editor_property(prop,value)
    hidden_paths={a.get_path_name() for a in DRONE_VIEW_COMPONENT.get_editor_property('hidden_actors') if a}
    return all(a.get_path_name() in hidden_paths for a in markers),len(markers)


def drone_view_start(folder):
    global DRONE_VIEW_ACTOR,DRONE_VIEW_COMPONENT,DRONE_VIEW_TARGET,DRONE_VIEW_CALLBACK
    global DRONE_VIEW_RECORDING,DRONE_VIEW_DIRECTORY,DRONE_VIEW_FRAMES,DRONE_VIEW_ERRORS
    global DRONE_VIEW_NEXT_TIME,DRONE_VIEW_LAST_TIME,DRONE_VIEW_INITIAL_FOV
    global DRONE_VIEW_SENSOR_TARGET_FORMAT,DRONE_VIEW_SENSOR_TARGET_GAMMA
    if DRONE_VIEW_RECORDING:
        raise RuntimeError('Live drone view is already recording')
    directory=Path(folder)
    if directory.exists() and any(directory.iterdir()):
        raise RuntimeError('Use a fresh drone-view folder; previous evidence is preserved')
    if not unreal.SystemLibrary.is_valid(DRONE_VIEW_SENSOR):
        raise RuntimeError('The selected sensor no longer belongs to the active Play world')
    if DRONE_VIEW_SENSOR.get_editor_property('projection_type')!=unreal.CameraProjectionMode.PERSPECTIVE:
        raise RuntimeError('Demo live drone view requires a perspective RGB sensor')
    if DRONE_VIEW_SENSOR.get_editor_property('use_custom_projection_matrix'):
        raise RuntimeError('Custom sensor projection requires explicit recorder support')
    directory.mkdir(parents=True,exist_ok=True)
    actors=[a for a in unreal.GameplayStatics.get_all_actors_of_class(DRONE_VIEW_WORLD,unreal.SceneCapture2D)
            if a.get_actor_label()=='RouteDemo_LiveDroneView']
    if len(actors)!=1:
        raise RuntimeError('Expected one preplaced RouteDemo_LiveDroneView SceneCapture2D in the active Play world')
    actor=actors[0]
    if not actor.get_path_name().startswith(DRONE_VIEW_WORLD.get_path_name()):
        raise RuntimeError('Live-view capture actor does not belong to the active Play world')
    DRONE_VIEW_ACTOR=actor
    DRONE_VIEW_COMPONENT=actor.get_editor_property('capture_component2d')
    try:
        component=DRONE_VIEW_COMPONENT
        component.set_editor_property('capture_every_frame',False)
        component.set_editor_property('capture_on_movement',False)
        component.set_editor_property('always_persist_rendering_state',True)
        for prop in ('capture_source','projection_type','post_process_settings','post_process_blend_weight',
                     'primitive_render_mode','show_flag_settings','lod_distance_factor',
                     'max_view_distance_override','use_ray_tracing_if_enabled','overscan',
                     'override_custom_near_clipping_plane','custom_near_clipping_plane',
                     'enable_clip_plane','clip_plane_base','clip_plane_normal'):
            component.set_editor_property(prop,DRONE_VIEW_SENSOR.get_editor_property(prop))
        DRONE_VIEW_INITIAL_FOV=float(DRONE_VIEW_SENSOR.get_editor_property('fov_angle'))
        component.set_editor_property('fov_angle',DRONE_VIEW_INITIAL_FOV)
        DRONE_VIEW_TARGET=unreal.RenderingLibrary.create_render_target2d(
            DRONE_VIEW_WORLD,DRONE_VIEW_WIDTH,DRONE_VIEW_HEIGHT,
            unreal.TextureRenderTargetFormat.RTF_RGBA8,unreal.LinearColor(0,0,0,1),False,False)
        source_target=DRONE_VIEW_SENSOR.get_editor_property('texture_target')
        if source_target:
            DRONE_VIEW_SENSOR_TARGET_FORMAT=str(source_target.get_editor_property('render_target_format'))
            DRONE_VIEW_SENSOR_TARGET_GAMMA=float(source_target.get_editor_property('target_gamma'))
            if (source_target.get_editor_property('size_x'),source_target.get_editor_property('size_y'))!=(DRONE_VIEW_WIDTH,DRONE_VIEW_HEIGHT):
                raise RuntimeError('Actual RGB target dimensions differ from the demo 640x480 profile')
            DRONE_VIEW_TARGET.set_editor_property('target_gamma',source_target.get_editor_property('target_gamma'))
        component.set_editor_property('texture_target',DRONE_VIEW_TARGET)
        _drone_view_visibility()
        component.set_world_transform(DRONE_VIEW_SENSOR.get_world_transform(),False,True)
        actor.set_actor_enable_collision(False)
    except Exception:
        # The actor is a deliberate editor fixture copied into PIE, never ours
        # to destroy. Only its independent capture component is configured.
        raise
    DRONE_VIEW_DIRECTORY=directory
    DRONE_VIEW_FRAMES=[]
    DRONE_VIEW_ERRORS=[]
    DRONE_VIEW_NEXT_TIME=None
    DRONE_VIEW_LAST_TIME=None
    DRONE_VIEW_RECORDING=True
    if DRONE_VIEW_CALLBACK is not None:
        unreal.unregister_slate_post_tick_callback(DRONE_VIEW_CALLBACK)
    DRONE_VIEW_CALLBACK=unreal.register_slate_post_tick_callback(_drone_view_tick)
    return {'directory':str(directory),'sensor_actor_path':DRONE_VIEW_SENSOR_ACTOR.get_path_name(),
            'sensor_component_path':DRONE_VIEW_SENSOR.get_path_name(),'source_note':DRONE_VIEW_SOURCE_NOTE}


def _drone_view_tick(_delta):
    global DRONE_VIEW_BUSY,DRONE_VIEW_RECORDING,DRONE_VIEW_NEXT_TIME,DRONE_VIEW_LAST_TIME
    if not DRONE_VIEW_RECORDING or DRONE_VIEW_BUSY:
        return
    sim_time=None
    DRONE_VIEW_BUSY=True
    try:
        game=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if game!=DRONE_VIEW_WORLD or not unreal.SystemLibrary.is_valid(DRONE_VIEW_SENSOR):
            raise RuntimeError('Live-view Play world or actual sensor changed')
        sim_time=float(unreal.GameplayStatics.get_time_seconds(DRONE_VIEW_WORLD))
        if DRONE_VIEW_LAST_TIME is not None and sim_time<DRONE_VIEW_LAST_TIME-1e-6:
            raise RuntimeError('Native world simulation clock moved backwards')
        if DRONE_VIEW_LAST_TIME is not None and sim_time<=DRONE_VIEW_LAST_TIME+1e-6:
            return  # Acquisition freezes must never repeat a live-view frame.
        if DRONE_VIEW_NEXT_TIME is not None and sim_time+1e-6<DRONE_VIEW_NEXT_TIME:
            return
        sensor=DRONE_VIEW_SENSOR
        component=DRONE_VIEW_COMPONENT
        component.set_world_transform(sensor.get_world_transform(),False,True)
        sensor_fov=float(sensor.get_editor_property('fov_angle'))
        if abs(float(component.get_editor_property('fov_angle'))-sensor_fov)>1e-8:
            component.set_editor_property('fov_angle',sensor_fov)
        all_hidden,marker_count=_drone_view_visibility()
        position=_drone_view_vector(component.get_world_location())
        sensor_position=_drone_view_vector(sensor.get_world_location())
        distance=math.sqrt(sum((a-b)**2 for a,b in zip(position,sensor_position)))
        angle=_drone_view_angle(component,sensor)
        # Snapshot both rotations before capture/export can pump the game thread.
        # Later sensor reads can describe a different instant of a turning drone.
        rotation=_drone_view_rotation(component.get_world_rotation())
        sensor_rotation=_drone_view_rotation(sensor.get_world_rotation())
        fov=float(component.get_editor_property('fov_angle'))
        if distance>DRONE_VIEW_TOLERANCES['position_cm'] or angle>DRONE_VIEW_TOLERANCES['angle_deg'] or abs(fov-sensor_fov)>DRONE_VIEW_TOLERANCES['fov_deg'] or not all_hidden:
            raise RuntimeError('Independent live-view pose/FOV/marker visibility differs from the actual RGB sensor')
        name='frame_%06d.png'%len(DRONE_VIEW_FRAMES)
        component.capture_scene()
        unreal.RenderingLibrary.export_render_target(DRONE_VIEW_WORLD,DRONE_VIEW_TARGET,str(DRONE_VIEW_DIRECTORY),name)
        with (DRONE_VIEW_DIRECTORY/name).open('rb') as image:
            header=image.read(24)
        if header[:8]!=b'\x89PNG\r\n\x1a\n' or (int.from_bytes(header[16:20],'big'),int.from_bytes(header[20:24],'big'))!=(DRONE_VIEW_WIDTH,DRONE_VIEW_HEIGHT):
            raise RuntimeError('Independent UE capture did not produce the expected PNG dimensions')
        DRONE_VIEW_FRAMES.append({'file':name,'sim_time_s':sim_time,'wall_monotonic_s':time.monotonic(),
            'position_cm':position,'rotation_deg':rotation,
            'sensor_position_cm':sensor_position,'sensor_rotation_deg':sensor_rotation,
            'fov_deg':fov,'sensor_fov_deg':sensor_fov,'position_delta_cm':distance,'angle_delta_deg':angle,
            'fov_delta_deg':abs(fov-sensor_fov),'all_markers_hidden':all_hidden,'marker_count':marker_count})
        if DRONE_VIEW_NEXT_TIME is None:
            DRONE_VIEW_NEXT_TIME=sim_time+DRONE_VIEW_INTERVAL
        else:
            DRONE_VIEW_NEXT_TIME+=(math.floor(max(0.,sim_time-DRONE_VIEW_NEXT_TIME)/DRONE_VIEW_INTERVAL)+1)*DRONE_VIEW_INTERVAL
        DRONE_VIEW_LAST_TIME=sim_time
    except Exception:
        DRONE_VIEW_RECORDING=False
        error=traceback.format_exc()
        DRONE_VIEW_ERRORS.append({'sim_time_s':sim_time,'error':error})
        unreal.log_error(error)
    finally:
        DRONE_VIEW_BUSY=False


def drone_view_finish():
    global DRONE_VIEW_RECORDING,DRONE_VIEW_CALLBACK,DRONE_VIEW_ACTOR
    DRONE_VIEW_RECORDING=False
    if DRONE_VIEW_CALLBACK is not None:
        unreal.unregister_slate_post_tick_callback(DRONE_VIEW_CALLBACK)
        DRONE_VIEW_CALLBACK=None
    if DRONE_VIEW_DIRECTORY is None:
        raise RuntimeError('Live drone view has not been started')
    info={'frames':DRONE_VIEW_FRAMES,'width':DRONE_VIEW_WIDTH,'height':DRONE_VIEW_HEIGHT,
          'fov':DRONE_VIEW_INITIAL_FOV,'fov_deg':DRONE_VIEW_INITIAL_FOV,
          'clock':'absolute native unpaused game-world simulation seconds',
          'requested_interval_sim_s':DRONE_VIEW_INTERVAL,'source_note':DRONE_VIEW_SOURCE_NOTE,
          'sensor_actor_path':DRONE_VIEW_SENSOR_ACTOR.get_path_name(),
          'sensor_component_path':DRONE_VIEW_SENSOR.get_path_name(),
          'camera_selection_note':DRONE_VIEW_SELECTION_NOTE,'rotation_order':['pitch','yaw','roll'],
          'mirror_tolerances':DRONE_VIEW_TOLERANCES,'errors':DRONE_VIEW_ERRORS,
          'visibility_copy_notes':DRONE_VIEW_VISIBILITY_NOTES,
          'sensor_capture_source':str(DRONE_VIEW_SENSOR.get_editor_property('capture_source')),
          'sensor_target_format':DRONE_VIEW_SENSOR_TARGET_FORMAT,'sensor_target_gamma':DRONE_VIEW_SENSOR_TARGET_GAMMA,
          'exported_png_color_space':'linear_rgb',
          'target_format':str(DRONE_VIEW_TARGET.get_editor_property('render_target_format'))}
    temporary=DRONE_VIEW_DIRECTORY/'frames.json.tmp'
    with temporary.open('w',encoding='utf-8') as stream:
        json.dump(info,stream,indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    deadline=time.monotonic()+.75
    while True:
        try:
            os.replace(temporary,DRONE_VIEW_DIRECTORY/'frames.json')
            break
        except PermissionError:
            if time.monotonic()>=deadline:
                raise
            time.sleep(.01)
    return {'frames':len(DRONE_VIEW_FRAMES),'directory':str(DRONE_VIEW_DIRECTORY)}


result={'ready':True,'sensor_actor_path':DRONE_VIEW_SENSOR_ACTOR.get_path_name(),
        'sensor_component_path':DRONE_VIEW_SENSOR.get_path_name(),'selection_note':DRONE_VIEW_SELECTION_NOTE}
