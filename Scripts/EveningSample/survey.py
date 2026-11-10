"""Read-only scene/asset survey. Keep only plain data in the report."""
import json
from pathlib import Path
import unreal
ROOT=Path(unreal.Paths.project_dir()).resolve()
output=ROOT/'Saved/EveningSample';output.mkdir(parents=True,exist_ok=True)
world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
rows=[]
for actor in actors.get_all_level_actors():
    label=actor.get_actor_label()
    for component in actor.get_components_by_class(unreal.StaticMeshComponent):
        mesh=component.get_editor_property('static_mesh')
        if mesh and any(x in mesh.get_name() for x in ('FoodStalls','Cafe','Bench','LampPost','RoadBlock')):
            if isinstance(component,unreal.InstancedStaticMeshComponent):continue
            rows.append({'label':label,'mesh':mesh.get_path_name(),'location':list(actor.get_actor_location().to_tuple()),'rotation':str(actor.get_actor_rotation()),'bounds':str(actor.get_actor_bounds(False))})
lights=[{'label':a.get_actor_label(),'class':a.get_class().get_name(),'location':list(a.get_actor_location().to_tuple())} for a in actors.get_all_level_actors() if isinstance(a,(unreal.DirectionalLight,unreal.SkyLight,unreal.PlayerStart,unreal.PostProcessVolume)) or 'Sky_Sphere' in a.get_class().get_name()]
meshes={}
for name in ('SM_FoodStalls01','SM_FoodStalls02','SM_FoodStalls03','SM_FoodStalls04','SM_CafeTable01','SM_CafeChair01','SM_TrashCan01','SM_Bench03','SM_LampPost01'):
    mesh=unreal.load_asset('/Game/CityPark/Meshes/Props/'+name)
    if mesh:
        bounds=mesh.get_bounds()
        meshes[name]={'origin':list(bounds.origin.to_tuple()),'extent':list(bounds.box_extent.to_tuple()),'materials':[str(x.material_interface.get_path_name()) if x.material_interface else None for x in mesh.get_editor_property('static_materials')]}
result={'world':world.get_path_name(),'rows':rows,'lights_and_starts':lights,'meshes':meshes}
(output/'survey.json').write_text(json.dumps(result,indent=2))
result={'props':len(rows),'mesh_bounds':meshes,'lights_and_starts':lights}
del actor,component,mesh
