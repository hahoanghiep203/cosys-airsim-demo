"""Original map startup. Session-only profile; never saves a map or mesh."""
from pathlib import Path
import unreal
SCENE_ROOT=Path(unreal.Paths.project_dir()).resolve()
exec((SCENE_ROOT/'Scripts/RouteCaptureDemo/editor_bridge.py').read_text())
exec((SCENE_ROOT/'Scripts/ScenePerformance/profile.py').read_text(),SCOPE,SCOPE)
def scene_apply(profile='balanced',game=False):
    """Expose the same original-value snapshot to the editor Python console."""
    return SCOPE['scene_apply'](profile,game)
def scene_start(profile='balanced'):
    SCOPE['scene_requested_profile']=profile
    SCOPE['result']=SCOPE['scene_apply'](profile)
    unreal.log('SCENE_PERFORMANCE_READY '+str(SCOPE['result']))
    # Map overrides otherwise select the original pack's third-person mode.
    SCOPE['scene_world']().get_world_settings().set_editor_property('default_game_mode',unreal.load_class(None,'/Script/AirSim.AirSimGameMode'))
    global SCENE_PIE_CALLBACK, SCENE_PIE_ELAPSED, SCENE_PIE_WORLD
    SCENE_PIE_ELAPSED=0.0
    SCENE_PIE_WORLD=None
    def scene_pie_tick(delta):
        global SCENE_PIE_ELAPSED, SCENE_PIE_WORLD
        SCENE_PIE_ELAPSED+=delta
        if SCENE_PIE_ELAPSED<1.0:return
        SCENE_PIE_ELAPSED=0.0
        world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        key=world.get_path_name() if world else None
        if key and key!=SCENE_PIE_WORLD:
            SCOPE['scene_apply'](SCOPE['scene_requested_profile'],True)
            hud_class=unreal.load_class(None,'/Script/AirSim.SimHUD')
            for hud in unreal.GameplayStatics.get_all_actors_of_class(world,hud_class):
                hud.set_thermal_review_viewport_size(1280,720)
        SCENE_PIE_WORLD=key
    if 'SCENE_PIE_CALLBACK' in globals():unreal.unregister_slate_post_tick_callback(SCENE_PIE_CALLBACK)
    SCENE_PIE_CALLBACK=unreal.register_slate_post_tick_callback(scene_pie_tick)
