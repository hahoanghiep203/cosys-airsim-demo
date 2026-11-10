"""Fixed scene camera for integration evidence, independent of drone camera."""
import time
import traceback
import unreal

if 'OBSERVER_CALLBACK' in globals():
    unreal.unregister_slate_post_tick_callback(OBSERVER_CALLBACK)

world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if not world: raise RuntimeError('Play must be active to create the observer')
observer_position=unreal.Vector(-1900,-2100,1500)
observer_target=unreal.Vector(0,0,180)
observer_rotation=unreal.MathLibrary.find_look_at_rotation(observer_position,observer_target)
observer=next(a for a in unreal.GameplayStatics.get_all_actors_of_class(world,unreal.SceneCapture2D) if a.get_actor_label()=='RouteDemo_Observer')
if not observer.get_path_name().startswith(world.get_path_name()): raise RuntimeError('Observer was spawned in the wrong world')
observer_component=observer.get_editor_property('capture_component2d')
observer_component.set_editor_property('capture_every_frame',False)
observer_component.set_editor_property('capture_on_movement',False)
observer_component.set_editor_property('always_persist_rendering_state',True)
observer_component.set_editor_property('capture_source',unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
observer_component.set_editor_property('fov_angle',55)
observer_target_texture=unreal.RenderingLibrary.create_render_target2d(world,960,540,unreal.TextureRenderTargetFormat.RTF_RGBA8,unreal.LinearColor(0,0,0,1),False,False)
observer_component.set_editor_property('texture_target',observer_target_texture)

# Labels face this one fixed observer without rotating the route/camera aim.
point_class=unreal.load_class(None,'/Script/AirSimRouteCapture.DroneRoutePoint')
for point in unreal.GameplayStatics.get_all_actors_of_class(world,point_class):
    number=point.get_editor_property('number')
    location=point.get_actor_location()+unreal.Vector(0,0,80)
    number.set_world_location(location,False,False)
    number.set_world_rotation(unreal.MathLibrary.find_look_at_rotation(location,observer_position),False,False)
    number.set_world_scale3d(unreal.Vector(.6,.6,.6))

OBSERVER_RECORDING=False
OBSERVER_BUSY=False
OBSERVER_FRAMES=[]
OBSERVER_DIRECTORY=None
OBSERVER_LAST_TIME=-1
OBSERVER_INTERVAL=.1

def observer_start(folder):
    global OBSERVER_RECORDING,OBSERVER_FRAMES,OBSERVER_DIRECTORY,OBSERVER_LAST_TIME
    OBSERVER_DIRECTORY=Path(folder)
    OBSERVER_DIRECTORY.mkdir(parents=True,exist_ok=True)
    OBSERVER_FRAMES=[]
    OBSERVER_LAST_TIME=-1
    OBSERVER_RECORDING=True

def observer_finish():
    global OBSERVER_RECORDING
    OBSERVER_RECORDING=False
    info={'frames':OBSERVER_FRAMES,'camera_position_cm':list(observer_position.to_tuple()),'camera_rotation_deg':list(observer_rotation.to_tuple()),'fov_deg':55,'width':960,'height':540,'clock':'unpaused game-world simulation seconds'}
    (OBSERVER_DIRECTORY/'frames.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    return {'frames':len(OBSERVER_FRAMES),'directory':str(OBSERVER_DIRECTORY)}

def observer_tick(_delta):
    global OBSERVER_BUSY,OBSERVER_LAST_TIME
    if not OBSERVER_RECORDING or OBSERVER_BUSY: return
    sim_time=unreal.GameplayStatics.get_time_seconds(world)
    if sim_time-OBSERVER_LAST_TIME<OBSERVER_INTERVAL: return
    OBSERVER_BUSY=True
    try:
        index=len(OBSERVER_FRAMES)
        name=f'frame_{index:06d}.png'
        observer_component.capture_scene()
        unreal.RenderingLibrary.export_render_target(world,observer_target_texture,str(OBSERVER_DIRECTORY),name)
        if not (OBSERVER_DIRECTORY/name).exists(): raise RuntimeError('Observer frame was not written')
        OBSERVER_FRAMES.append({'file':name,'sim_time_s':sim_time,'wall_monotonic_s':time.monotonic(),'position_cm':list(observer.get_actor_location().to_tuple()),'rotation_deg':list(observer.get_actor_rotation().to_tuple())})
        OBSERVER_LAST_TIME=sim_time
    except Exception:
        unreal.log_error(traceback.format_exc())
    finally:
        OBSERVER_BUSY=False

OBSERVER_CALLBACK=unreal.register_slate_post_tick_callback(observer_tick)
result={'observer':observer.get_name(),'actor_path':observer.get_path_name(),'game_world':world.get_path_name(),'camera_position_cm':list(observer_position.to_tuple())}
