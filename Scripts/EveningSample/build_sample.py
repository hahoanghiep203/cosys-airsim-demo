"""Create a sample-private evening corner. Never save the template/user maps."""
import hashlib
import json
from pathlib import Path
import unreal

def build_sample():
    root=Path(unreal.Paths.project_dir()).resolve()
    output=root/'Saved/EveningSample';output.mkdir(parents=True,exist_ok=True)
    target='/Game/CityPark/Maps/Showcase_EveningSample'
    protected=[root/'Content/CityPark/Maps'/name for name in ('Showcase.umap','Showcase_CoordinateCrop.umap')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    assert not unreal.EditorAssetLibrary.does_asset_exist(target),'Sample exists: use a deliberate revision, never overwrite blindly'
    assert unreal.EditorLevelLibrary.new_level_from_template(target,'/Game/CityPark/Maps/Showcase')
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    asset_tools=unreal.AssetToolsHelpers.get_asset_tools()
    subobjects=unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    library=unreal.SubobjectDataBlueprintFunctionLibrary
    folder='/Game/Thermal/EveningSample/Blueprints'
    records=[]
    ground_helper=unreal.get_default_object(unreal.GameplayStatics.static_class())
    def ground(x,y):
        hit=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(x,y,1100),unreal.Vector(x,y,-1500),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,[],unreal.DrawDebugTrace.NONE,True)
        assert hit is not None,('No ground',x,y)
        fields=ground_helper.call_method('BreakHitResult',(hit,))
        assert fields[0] and fields[7].z>.75,('Not walkable',x,y)
        return fields[5].z
    def spawn(cls,label,x,y,yaw=0,z=None):
        z=ground(x,y) if z is None else z
        actor=actors.spawn_actor_from_class(cls,unreal.Vector(x,y,z),unreal.Rotator(yaw=yaw))
        assert actor,label
        actor.set_actor_label('Sample_'+label)
        actor.set_folder_path('Evening Sample/'+('Vehicles' if 'Vehicle' in label else 'Cafe Corner'))
        actor.tags=[unreal.Name('EveningSample'),unreal.Name('ScenePerformanceKeep')]
        return actor
    def baseline(actor,k,emissivity=.94):
        actor.tags=list(actor.tags)+[unreal.Name('ThermalTempK='+str(k)),unreal.Name('ThermalEmissivity='+str(emissivity))]
    def mesh_actor(name,path,x,y,yaw=0,k=292.15):
        mesh=unreal.load_asset(path);assert mesh,path
        bounds=mesh.get_bounds();z=ground(x,y)-bounds.origin.z+bounds.box_extent.z+.4
        actor=spawn(unreal.StaticMeshActor,name,x,y,yaw,z)
        component=actor.static_mesh_component
        component.set_static_mesh(mesh)
        baseline(actor,k)
        records.append({'label':actor.get_actor_label(),'asset':path,'location':list(actor.get_actor_location().to_tuple()),'baseline_k':k})
        return actor
    def blueprint(name,parent):
        path=folder+'/'+name
        assert not unreal.EditorAssetLibrary.does_asset_exist(path),path
        factory=unreal.BlueprintFactory();factory.set_editor_property('parent_class',parent)
        bp=asset_tools.create_asset(name,folder,unreal.Blueprint,factory);assert bp,path
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        return bp,unreal.load_class(None,path+'.'+name+'_C')
    def source_preset(name,values):
        bp,cls=blueprint(name,unreal.load_class(None,'/Script/AirSim.ThermalSource'))
        default=unreal.get_default_object(cls)
        for key,value in values.items():default.set_editor_property(key,value)
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        assert unreal.EditorAssetLibrary.save_loaded_asset(bp)
        return cls
    def component(bp,root_handle,name,cls):
        handle,error=subobjects.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=root_handle,new_class=cls,blueprint_context=bp))
        assert library.is_handle_valid(handle),str(error)
        subobjects.rename_subobject(handle,unreal.Text(name))
        return library.get_object_for_blueprint(library.get_data(handle),bp)
    counter_heat=source_preset('BP_SampleCounterHeat',{
        'source_type':unreal.ThermalSourceType.RECT,'temperature_kelvin':363.15,
        'range_cm':110.,'radius_cm':18.,'rect_width_cm':75.,'rect_height_cm':50.,
        'parent_contact_radius_cm':65.,'parent_conductance':110.,'power_scale':1.,'occlusion':True,'heat_parent_surface':True})
    lamp_heat=source_preset('BP_SampleLampHeat',{
        'source_type':unreal.ThermalSourceType.POINT,'temperature_kelvin':328.15,
        'range_cm':85.,'radius_cm':10.,'parent_contact_radius_cm':25.,'parent_conductance':150.,
        'power_scale':1.,'occlusion':True,'heat_parent_surface':True})
    for name,mesh_path,heat_class,source_pos,source_rot,light_pos,intensity,radius in [
        ('BP_SampleHotCounter','/Game/CityPark/Meshes/Props/SM_FoodStalls02',counter_heat,unreal.Vector(0,0,150),unreal.Rotator(pitch=-90),unreal.Vector(70,0,185),85.,500.),
        ('BP_SampleWarmLamp','/Game/CityPark/Meshes/Props/SM_LampPost01',lamp_heat,unreal.Vector(0,0,364.4),unreal.Rotator(),unreal.Vector(0,0,361),95.,850.)]:
        bp,cls=blueprint(name,unreal.StaticMeshActor)
        default=unreal.get_default_object(cls)
        default.static_mesh_component.set_static_mesh(unreal.load_asset(mesh_path))
        if 'Lamp' in name:default.static_mesh_component.set_material(1,unreal.load_asset('/Game/Thermal/Materials/MI_EveningParkLampGlass'))
        handles=subobjects.k2_gather_subobject_data_for_blueprint(bp)
        root_handle=next(h for h in handles if isinstance(library.get_object(library.get_data(h)),unreal.StaticMeshComponent))
        child=component(bp,root_handle,'LocalHeat',unreal.ChildActorComponent)
        child.set_editor_property('child_actor_class',heat_class)
        child.set_editor_property('relative_location',source_pos)
        child.set_editor_property('relative_rotation',source_rot)
        light=component(bp,root_handle,'WarmVisibleLight',unreal.PointLightComponent)
        for key,value in {'mobility':unreal.ComponentMobility.MOVABLE,'relative_location':light_pos,
            'intensity_units':unreal.LightUnits.CANDELAS,'intensity':intensity,'attenuation_radius':radius,
            'use_temperature':True,'temperature':3000.,'cast_shadows':False,
            'volumetric_scattering_intensity':0.,'indirect_lighting_intensity':0.,'max_draw_distance':6500.}.items():light.set_editor_property(key,value)
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        assert unreal.EditorAssetLibrary.save_loaded_asset(bp)
    # Keep all existing park geometry. Add a small, readable arrangement on pavement.
    stall=mesh_actor('FoodStall','/Game/CityPark/Meshes/Props/SM_FoodStalls03',-28800,10280,180)
    hot_counter_class=unreal.load_class(None,folder+'/BP_SampleHotCounter.BP_SampleHotCounter_C')
    counter=spawn(hot_counter_class,'HotFoodCounter',-29000,10270,180);baseline(counter,293.15)
    records.append({'label':counter.get_actor_label(),'asset':folder+'/BP_SampleHotCounter','role':'localized heated metal counter; source90C, not whole cart'})
    props=[
        ('CafeTable_A','SM_CafeTable02',-29360,9900,12),('CafeTable_B','SM_CafeTable01',-29600,10400,-8),
        ('Chair_A1','SM_CafeChair01',-29360,9790,90),('Chair_A2','SM_CafeChair02',-29360,10010,-90),
        ('Chair_B1','SM_CafeChair03',-29600,10290,90),('Chair_B2','SM_CafeChair04',-29600,10510,-90),
        ('Bench','SM_Bench03',-28900,10820,0),('Bin_A','SM_TrashCan01',-28880,10540,0),
        ('Bin_B','SM_TrashCan02',-29900,10770,20)]
    for name,mesh,x,y,yaw in props:mesh_actor(name,'/Game/CityPark/Meshes/Props/'+mesh,x,y,yaw)
    hatchback=unreal.load_class(None,'/Game/Thermal/Blueprints/BP_ThermalHatchback.BP_ThermalHatchback_C')
    hot_car=spawn(hatchback,'Vehicle_HotHatchback',-30320,11150,-150)
    baseline(hot_car,293.15,.88)
    for light in hot_car.get_components_by_class(unreal.SpotLightComponent):light.set_editor_property('cast_shadows',False)
    records.append({'label':hot_car.get_actor_label(),'asset':'/Game/Thermal/Blueprints/BP_ThermalHatchback','role':'existing seven hood/headlight/tire-only child heat sources'})
    cold_car=mesh_actor('Vehicle_ColdSUV','/Game/VehicleVarietyPack/Meshes/SM_SUV',-30080,11900,-150,289.15)
    lamp_class=unreal.load_class(None,folder+'/BP_SampleWarmLamp.BP_SampleWarmLamp_C')
    for name,x,y in [('WarmLamp_A',-29220,10730),('WarmLamp_B',-29750,9730)]:
        lamp=spawn(lamp_class,name,x,y);baseline(lamp,291.15,.92)
        records.append({'label':lamp.get_actor_label(),'asset':folder+'/BP_SampleWarmLamp','role':'localized55C housing source, independent3000K visible light'})
    scene=spawn(unreal.load_class(None,'/Script/AirSim.ThermalSceneSettings'),'ThermalBaselines',-29000,9800,z=120)
    for key,value in {'tree_temperature_celsius':16.,'bush_temperature_celsius':16.,'grass_temperature_celsius':15.,
        'road_temperature_celsius':24.,'concrete_temperature_celsius':21.,'ground_temperature_celsius':18.,
        'water_temperature_celsius':18.,'building_temperature_celsius':21.,'metal_temperature_celsius':18.,
        'wood_temperature_celsius':18.,'vehicle_temperature_celsius':19.,'default_temperature_celsius':18.}.items():scene.set_editor_property(key,value)
    scene.apply_scene_temperatures()
    all_actors=actors.get_all_level_actors()
    sun=next(a for a in all_actors if isinstance(a,unreal.DirectionalLight))
    sun.set_actor_rotation(unreal.Rotator(pitch=-4,yaw=-35),False)
    sun.light_component.set_editor_property('intensity',.16)
    sun.light_component.set_editor_property('light_color',unreal.Color(255,171,116,255))
    sky=next(a for a in all_actors if a.get_class().get_name()=='BP_Sky_Sphere_C')
    for key,value in {'Colors determined by sun position':False,'Sun brightness':1.2,'Stars brightness':.5,
        'Cloud opacity':1.,'Horizon falloff':3.,'Zenith color':unreal.LinearColor(.004,.009,.025,1),
        'Horizon color':unreal.LinearColor(.07,.03,.023,1),'Cloud color':unreal.LinearColor(.025,.032,.055,1),
        'Overall color':unreal.LinearColor(1,1,1,1)}.items():sky.set_editor_property(key,value)
    sky.call_method('RefreshMaterial')
    skylight=next(a for a in all_actors if isinstance(a,unreal.SkyLight))
    skylight.light_component.set_editor_property('intensity',.28)
    skylight.light_component.set_editor_property('light_color',unreal.Color(160,185,255,255))
    skylight.light_component.recapture_sky()
    for a in all_actors:
        if not isinstance(a,unreal.PostProcessVolume):continue
        pp=a.get_editor_property('settings')
        for key,value in {'override_auto_exposure_min_brightness':True,'override_auto_exposure_max_brightness':True,
            'auto_exposure_min_brightness':1.,'auto_exposure_max_brightness':1.,'override_auto_exposure_bias':True,'auto_exposure_bias':1.}.items():pp.set_editor_property(key,value)
        a.set_editor_property('settings',pp)
    view=unreal.Vector(-31800,11900,950);aim=unreal.Vector(-29450,10850,180)
    rotation=unreal.MathLibrary.find_look_at_rotation(view,aim)
    for start in all_actors:
        if isinstance(start,unreal.PlayerStart):start.set_actor_location_and_rotation(unreal.Vector(view.x,view.y,ground(view.x,view.y)+110),rotation,False,True)
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(view,rotation)
    world.get_world_settings().set_editor_property('default_game_mode',unreal.load_class(None,'/Script/AirSim.AirSimGameMode'))
    assert unreal.EditorLevelLibrary.save_current_level()
    for p in protected:assert hashlib.sha256(p.read_bytes()).hexdigest()==hashes[str(p)],'Protected map changed'
    report={'map':target,'objects':records,'preview_position_cm':list(view.to_tuple()),'preview_target_cm':list(aim.to_tuple()),
        'protected_map_hashes':hashes,'notes':'Existing assets reused; warm counter, seven-source hatchback, two warm lamp fixtures, cold SUV and ambient cafe props. Demonstration temperatures, not measurements. No character assets added.'}
    (output/'build.json').write_text(json.dumps(report,indent=2))
    return {'map':target,'added_objects':len(records),'protected_maps_unchanged':True}

result=build_sample()
