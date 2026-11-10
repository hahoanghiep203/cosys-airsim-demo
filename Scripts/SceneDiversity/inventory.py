def inventory():
 import json
 from pathlib import Path
 out=Path(unreal.Paths.project_dir()).resolve()/'Saved/SceneDiversity';out.mkdir(parents=True,exist_ok=True)
 result={}
 for name in ('Hatchback','SUV','Pickup','SportsCar','Truck_Box'):
  mesh=unreal.load_asset('/Game/VehicleVarietyPack/Meshes/SM_'+name)
  task=unreal.AssetExportTask();task.object=mesh;task.filename=str(out/(name+'.obj'));task.automated=True;task.prompt=False;task.replace_identical=True;task.exporter=unreal.StaticMeshExporterOBJ()
  ok=unreal.Exporter.run_asset_export_task(task)
  bounds=mesh.get_bounds()
  result[name]={'exported':ok,'origin':list(bounds.origin.to_tuple()),'extent':list(bounds.box_extent.to_tuple()),'materials':[{'index':i,'name':str(s.material_slot_name),'asset':s.material_interface.get_path_name()} for i,s in enumerate(mesh.static_materials)]}
 bp=unreal.load_asset('/Game/Thermal/Blueprints/BP_ThermalHatchback')
 sub=unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem);lib=unreal.SubobjectDataBlueprintFunctionLibrary
 result['existing_components']=[]
 for h in sub.k2_gather_subobject_data_for_blueprint(bp):
  c=lib.get_object_for_blueprint(lib.get_data(h),bp)
  if isinstance(c,unreal.SceneComponent):result['existing_components'].append({'name':c.get_name(),'class':c.get_class().get_name(),'mobility':str(c.mobility),'relative':str(c.relative_location)})
 (out/'inventory.json').write_text(json.dumps(result,indent=2));return result
result=inventory()
