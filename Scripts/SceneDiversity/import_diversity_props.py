"""Import only selected CC0 props, retaining the downloaded creator license."""
import json
from pathlib import Path
import unreal


def import_props():
    root=Path(unreal.Paths.project_dir()).resolve()
    source=root/'SourceAssets/ThirdParty/KenneyCityIndustrial/unpacked'
    assert 'CC0' in (source/'License.txt').read_text()
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    previous=unreal.SystemLibrary.get_console_variable_int_value('Interchange.FeatureFlags.Import.FBX')
    unreal.SystemLibrary.execute_console_command(world,'Interchange.FeatureFlags.Import.FBX 0')
    output=[]
    try:
        for filename in ('detail-tank','shipping-container-a','solar-panel-landscape'):
            folder='/Game/Thermal/SceneDiversity/ThirdParty/KenneyIndustrial'
            name='SM_Kenney_'+filename.replace('-','_')
            path=folder+'/'+name
            if unreal.EditorAssetLibrary.does_asset_exist(path):
                output.append({'file':filename,'mesh':path,'existing':True});continue
            options=unreal.FbxImportUI()
            options.set_editor_property('import_as_skeletal',False)
            options.set_editor_property('mesh_type_to_import',unreal.FBXImportType.FBXIT_STATIC_MESH)
            options.set_editor_property('automated_import_should_detect_type',False)
            options.set_editor_property('import_materials',True)
            options.set_editor_property('import_textures',True)
            options.static_mesh_import_data.set_editor_property('combine_meshes',True)
            options.static_mesh_import_data.set_editor_property('generate_lightmap_u_vs',True)
            task=unreal.AssetImportTask()
            for key,value in {'filename':str(source/'Models/FBX format'/(filename+'.fbx')),
                              'destination_path':folder,'destination_name':name,
                              'automated':True,'replace_existing':False,'save':True,'options':options}.items():
                task.set_editor_property(key,value)
            unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
            mesh=unreal.load_asset(path)
            assert isinstance(mesh,unreal.StaticMesh),(filename,list(task.imported_object_paths))
            bounds=mesh.get_bounds()
            output.append({'file':filename,'mesh':path,'extent_cm':[bounds.box_extent.x,bounds.box_extent.y,bounds.box_extent.z],
                'origin_cm':[bounds.origin.x,bounds.origin.y,bounds.origin.z],'vertices':mesh.get_num_vertices(0),
                'materials':[mesh.get_material(i).get_name() if mesh.get_material(i) else None for i in range(len(mesh.static_materials))]})
    finally:
        unreal.SystemLibrary.execute_console_command(world,'Interchange.FeatureFlags.Import.FBX '+str(previous))
    (root/'Saved/SceneDiversity/TemperatureAudit/imported_props.json').write_text(json.dumps(output,indent=2))
    return output


result=import_props()
