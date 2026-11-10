"""Add four deliberately configured examples to the existing combined environment."""
import json
from pathlib import Path
import unreal


def place_props():
    root=Path(unreal.Paths.project_dir()).resolve()
    actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    assert '/ThermalDiversity_05_CombinedEnvironment.' in world.get_path_name()
    specifications=[
        {'label':'Combined_service_ProcessTank_Warm','mesh':'detail_tank','xy_cm':[-23600,13800],'height_cm':120,'yaw':0,'temperature_c':35.,'state':'controlled warm casing; hypothetical operating process tank'},
        {'label':'Combined_service_ProcessTank_Cold','mesh':'detail_tank','xy_cm':[-24100,13800],'height_cm':120,'yaw':0,'temperature_c':16.,'state':'inactive tank at ambient'},
        {'label':'Combined_service_StorageContainer','mesh':'shipping_container_a','xy_cm':[-22100,13900],'height_cm':220,'yaw':90,'temperature_c':16.,'state':'unpowered storage container'},
        {'label':'Combined_market_SolarPanel','mesh':'solar_panel_landscape','xy_cm':[-13800,10000],'height_cm':65,'yaw':20,'temperature_c':16.,'state':'inactive solar panel at blue-hour ambient'},
    ]
    existing={a.get_actor_label():a for a in actors.get_all_level_actors()}
    for spec in specifications:
        mesh_path='/Game/Thermal/SceneDiversity/ThirdParty/KenneyIndustrial/SM_Kenney_'+spec['mesh']
        mesh=unreal.load_asset(mesh_path);assert mesh,mesh_path
        b=mesh.get_bounds();scale=spec['height_cm']/(2*b.box_extent.z)
        x,y=spec['xy_cm'];floor=_ground_height(world,x,y)
        position=unreal.Vector(x,y,floor+(b.box_extent.z-b.origin.z)*scale+1)
        actor=existing.get(spec['label']) or actors.spawn_actor_from_class(unreal.StaticMeshActor,position,unreal.Rotator(yaw=spec['yaw']))
        actor.static_mesh_component.set_static_mesh(mesh)
        actor.set_actor_location_and_rotation(position,unreal.Rotator(yaw=spec['yaw']),False,True)
        actor.set_actor_scale3d(unreal.Vector(scale,scale,scale))
        actor.set_actor_label(spec['label']);actor.set_folder_path('Thermal Diversity/'+('service' if 'service' in spec['label'] else 'market')+'/Imported Props')
        actor.tags=[unreal.Name(t) for t in ('ScenePerformanceKeep','ThermalDiversity','ThermalTempK='+str(spec['temperature_c']+273.15),'ThermalEmissivity=0.90','ThermalPresetAssumption')]
        spec.update(asset=mesh_path,position_cm=[position.x,position.y,position.z],scale=scale,emissivity=.90)
    (root/'Config/SceneDiversity/imported_props.json').write_text(json.dumps({'license':'CC0','creator':'Kenney','source':'https://kenney.nl/assets/city-kit-industrial','props':specifications},indent=2))
    return {'objects':len(specifications),'new_thermal_sources':0,'props':specifications}


exec((ROOT/'Scripts/SceneDiversity/build_scenes.py').read_text(),globals(),globals())
result=place_props()
