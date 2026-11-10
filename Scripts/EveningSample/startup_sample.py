"""Preview pose and one-off thermal warmup, with scalar-only persistent state."""
from pathlib import Path
import json
import unreal
SAMPLE_ROOT=Path(unreal.Paths.project_dir()).resolve()
exec((SAMPLE_ROOT/'Scripts/ScenePerformance/startup.py').read_text(encoding='utf-8-sig'))
scene_start('balanced')
SAMPLE_CONFIG=json.loads((SAMPLE_ROOT/'Config/EveningSample/scene.json').read_text())
SAMPLE_LAST_WORLD=None
SAMPLE_ELAPSED=0.
def sample_preview_tick(delta):
    global SAMPLE_LAST_WORLD,SAMPLE_ELAPSED
    SAMPLE_ELAPSED+=delta
    if SAMPLE_ELAPSED<.5:return
    SAMPLE_ELAPSED=0.
    sample_world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    key=sample_world.get_path_name() if sample_world else None
    if key and key!=SAMPLE_LAST_WORLD and 'Showcase_EveningSample' in key:
        position=unreal.Vector(*SAMPLE_CONFIG['preview_position_cm'])
        target=unreal.Vector(*SAMPLE_CONFIG['preview_target_cm'])
        rotation=unreal.MathLibrary.find_look_at_rotation(position,target)
        for camera in unreal.GameplayStatics.get_all_actors_of_class(sample_world,unreal.load_class(None,'/Script/AirSim.PIPCamera')):
            camera.set_actor_location_and_rotation(position,rotation,False,True)
        for hud in unreal.GameplayStatics.get_all_actors_of_class(sample_world,unreal.load_class(None,'/Script/AirSim.SimHUD')):
            hud.set_thermal_review_viewport_size(1280,720)
        sources=unreal.GameplayStatics.get_all_actors_of_class(sample_world,unreal.load_class(None,'/Script/AirSim.ThermalSource'))
        if sources:sources[0].prewarm(float(SAMPLE_CONFIG['warmup_seconds']))
        unreal.log('EVENING_SAMPLE_READY sources='+str(len(sources)))
    SAMPLE_LAST_WORLD=key
if 'SAMPLE_PREVIEW_CALLBACK' in globals():unreal.unregister_slate_post_tick_callback(SAMPLE_PREVIEW_CALLBACK)
SAMPLE_PREVIEW_CALLBACK=unreal.register_slate_post_tick_callback(sample_preview_tick)
