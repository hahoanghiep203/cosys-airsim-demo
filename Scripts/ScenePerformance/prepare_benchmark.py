exec((ROOT/'Scripts/ScenePerformance/profile.py').read_text())
scene_apply('baseline')
world=scene_world()
for previous in unreal.GameplayStatics.get_all_actors_of_class(world,unreal.SceneCapture2D):
 if previous.get_actor_label()=='ScenePerformance_TransientProbe':
  unreal.get_editor_subsystem(unreal.EditorActorSubsystem).destroy_actor(previous)
location,rotation=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_level_viewport_camera_info()
scene_probe_actor=unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(unreal.SceneCapture2D,location,rotation)
scene_probe_actor.set_actor_label('ScenePerformance_TransientProbe')
scene_probe_component=scene_probe_actor.get_editor_property('capture_component2d')
scene_probe_component.set_editor_property('capture_source',unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
scene_probe_component.set_editor_property('capture_every_frame',True)
scene_probe_target=unreal.RenderingLibrary.create_render_target2d(world,960,540,unreal.TextureRenderTargetFormat.RTF_RGBA8,unreal.LinearColor(0,0,0,1),False,False)
scene_probe_component.set_editor_property('texture_target',scene_probe_target)
result={'frame_stat':unreal.AutomationLibrary.get_stat_inc_average('STAT_FrameTime'),'probe_location':str(location),'probe_rotation':str(rotation),'profile':scene_apply('baseline')}
