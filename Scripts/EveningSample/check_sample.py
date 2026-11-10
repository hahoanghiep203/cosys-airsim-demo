"""Read scene-specific thermal evidence without retaining foliage wrappers."""
def check_sample():
    import json
    import unreal
    from pathlib import Path
    root=Path(unreal.Paths.project_dir()).resolve()
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    assert world and 'Showcase_EveningSample' in world.get_path_name()
    source_class=unreal.load_class(None,'/Script/AirSim.ThermalSource')
    sources=unreal.GameplayStatics.get_all_actors_of_class(world,source_class)
    sample_actors=[a for a in unreal.GameplayStatics.get_all_actors_of_class(world,unreal.Actor) if a.actor_has_tag('EveningSample')]
    car=next(a for a in sample_actors if a.get_actor_label()=='Sample_Vehicle_HotHatchback')
    cold=next(a for a in sample_actors if a.get_actor_label()=='Sample_Vehicle_ColdSUV')
    counter=next(a for a in sample_actors if a.get_actor_label()=='Sample_HotFoodCounter')
    counter_source=counter.get_components_by_class(unreal.ChildActorComponent)[0].get_editor_property('child_actor')
    sample_sources=[]
    for source in sources:
        sample_sources.append({'name':source.get_name(),'source_type':str(source.get_editor_property('source_type')),'temperature_k':source.get_editor_property('temperature_kelvin'),'parent':str(source.get_editor_property('parent_receiver'))})
    samples=[]
    for local in (unreal.Vector(0,0,155),unreal.Vector(30,0,135),unreal.Vector(0,0,25)):
        point=counter.get_actor_transform().transform_location(local)
        samples.append({'counter_local':list(local.to_tuple()),'surface_k':counter_source.get_surface_temperature(point)})
    hud=unreal.GameplayStatics.get_all_actors_of_class(world,unreal.load_class(None,'/Script/AirSim.SimHUD'))[0]
    report={'map':world.get_path_name(),'sources':sample_sources,'source_count':len(sources),
        'car_child_count':len(car.get_components_by_class(unreal.ChildActorComponent)),
        'cold_vehicle_sources':len(cold.get_components_by_class(unreal.ChildActorComponent)),
        'counter_probes':samples,'gpu':json.loads(hud.get_thermal_gpu_stats()),
        'source_sample_count':sources[0].get_thermal_sample_count()}
    assert len(sources)==10 and report['car_child_count']==7 and report['cold_vehicle_sources']==0
    assert max(s['surface_k'] for s in samples)>305,report['counter_probes']
    (root/'Saved/EveningSample/scene_check.json').write_text(json.dumps(report,indent=2))
    return report
result=check_sample()
