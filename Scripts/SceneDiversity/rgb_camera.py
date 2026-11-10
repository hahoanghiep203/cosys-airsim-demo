"""Apply physical exposure only to RGB/main cameras; retain no UObject wrappers."""
import json
from pathlib import Path
import unreal


def apply_rgb_camera_profile(profile=None):
    root=Path(unreal.Paths.project_dir()).resolve()
    profile=profile or json.loads((root/'Config/SceneDiversity/rgb_camera.json').read_text(encoding='utf-8-sig'))
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if not world or not profile.get('enabled'):
        return {'applied':False}
    if profile.get('scene')!='05_combined_environment' or 'ThermalDiversity_05_CombinedEnvironment.' not in world.get_path_name():
        return {'applied':False,'reason':'Different scene'}
    values={'auto_exposure_method':unreal.AutoExposureMethod.AEM_MANUAL,
        'auto_exposure_apply_physical_camera_exposure':True,
        'camera_iso':float(profile['iso']),
        'camera_shutter_speed':float(profile['shutter_denominator']),
        'depth_of_field_fstop':float(profile['f_stop']),
        'auto_exposure_bias':float(profile['exposure_compensation']),
        'film_grain_intensity':float(profile.get('film_grain_intensity',0))}
    rows=[]
    for camera in unreal.GameplayStatics.get_all_actors_of_class(world,unreal.load_class(None,'/Script/AirSim.PIPCamera')):
        components=list(camera.get_components_by_class(unreal.CameraComponent) or [])
        components += [c for c in camera.get_components_by_class(unreal.SceneCaptureComponent2D) if c.get_name()=='SceneCaptureComponent']
        for component in components:
            if isinstance(component,unreal.CineCameraComponent):
                component.set_editor_property('current_aperture',float(profile['f_stop']),notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
                if abs(component.get_editor_property('current_aperture')-float(profile['f_stop']))>.001:
                    raise RuntimeError('CineCamera aperture was clamped by its lens settings')
            settings=component.get_editor_property('post_process_settings').copy()
            for key,value in values.items():
                settings.set_editor_property('override_'+key,True)
                settings.set_editor_property(key,value)
            component.set_editor_property('post_process_settings',settings,notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
            rows.append({'camera':camera.get_path_name(),'component':component.get_name(),
                'iso':float(settings.get_editor_property('camera_iso')),
                'shutter_denominator':float(settings.get_editor_property('camera_shutter_speed')),
                'f_stop':float(settings.get_editor_property('depth_of_field_fstop')),
                'physical_exposure':bool(settings.get_editor_property('auto_exposure_apply_physical_camera_exposure'))})
    return {'applied':bool(rows),'profile':profile,'components':rows}
