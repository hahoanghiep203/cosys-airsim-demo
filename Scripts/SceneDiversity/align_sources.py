"""Correct mesh-specific mounts in the combined map without altering shared BPs."""
import json
from pathlib import Path


def apply_source_alignment(game=False):
    import unreal
    root=Path(unreal.Paths.project_dir()).resolve()
    settings=json.loads((root/'Config/SceneDiversity/source_alignment.json').read_text())
    system=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world=system.get_game_world() if game else system.get_editor_world()
    assert world and 'ThermalDiversity_05_CombinedEnvironment.' in world.get_path_name()
    report=[]
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world,unreal.Actor):
        model=next((m for m in settings if actor.get_class().get_name()=='BP_Thermal_'+m+'_C'),None)
        if not model:continue
        spec=settings[model]
        if not game:actor.modify()
        for child in actor.get_components_by_class(unreal.ChildActorComponent):
            name=child.get_name()
            source=child.get_editor_property('child_actor')
            if not source:continue
            if not game:child.modify();source.modify()
            if 'HoodHeat' in name:
                child.set_relative_location(unreal.Vector(*spec['hood_cm']),False,True)
                child.set_relative_rotation(unreal.Rotator(pitch=spec['hood_pitch']),False,True)
                for key,value in [('parent_contact_radius_cm',spec['hood_contact_radius_cm']),('parent_material_indices',spec['hood_material_indices'])]:
                    source.set_editor_property(key,value,notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
                report.append({'actor':actor.get_actor_label(),'source':name,'model':model,'region':spec['probe']})
            elif 'Headlight_' in name and 'headlight_x_cm' in spec:
                p=child.get_editor_property('relative_location')
                child.set_relative_location(unreal.Vector(spec['headlight_x_cm'],p.y,p.z),False,True)
                report.append({'actor':actor.get_actor_label(),'source':name,'model':model,'region':'front_light'})
    return report
