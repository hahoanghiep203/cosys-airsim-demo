"""Read actual capture-component marker exclusions in the owned PIE world."""
import unreal

game=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if not game:
    raise RuntimeError('Play is required')
markers=list(unreal.GameplayStatics.get_all_actors_with_tag(game,'RouteCaptureMarker'))
marker_paths={actor.get_path_name() for actor in markers}
camera_class=unreal.load_class(None,'/Script/AirSim.PIPCamera')
captures=[]
for camera in unreal.GameplayStatics.get_all_actors_of_class(game,camera_class):
    for component in camera.get_components_by_class(unreal.SceneCaptureComponent2D):
        hidden={actor.get_path_name() for actor in component.get_editor_property('hidden_actors') if actor}
        captures.append({'camera':camera.get_name(),'component':component.get_name(),
                         'hidden_marker_count':len(marker_paths & hidden),
                         'all_markers_hidden':marker_paths.issubset(hidden)})
if not markers or not captures or not all(item['all_markers_hidden'] for item in captures):
    raise RuntimeError('A drone capture component exposes route markers')
result={'marker_count':len(markers),'captures':captures,'all_markers_hidden':True}
