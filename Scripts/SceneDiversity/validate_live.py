"""Actual surface probes and attachment checks for the active diversity scene."""
def validate_live():
    import json
    import math
    from pathlib import Path
    import unreal
    root = Path(unreal.Paths.project_dir()).resolve()
    state = diversity_snapshot()
    assert state.get('ready'), state
    scene = next(s for s in json.loads((root / 'Config/SceneDiversity/scenes.json').read_text())['scenes'] if s['id'] == state['id'])
    assets = json.loads((root / 'Config/SceneDiversity/vehicle_geometry.json').read_text())
    actual_rims = json.loads((root / 'Config/SceneDiversity/rim_probes.json').read_text())
    results = []
    for vehicle in state['vehicles']:
        actor = unreal.find_object(None, state['actor_paths'][vehicle['label']])
        transform = actor.get_actor_transform()
        rings = assets[vehicle['model']]['tires']
        components = {c.get_name().split('_GEN_VARIABLE')[0]: c for c in actor.get_components_by_class(unreal.ChildActorComponent)}
        samples = []
        for i, ring in enumerate(rings):
            component = next(c for name, c in components.items() if name.startswith('Tire_' + str(i)))
            source = component.get_editor_property('child_actor')
            expected = transform.transform_location(unreal.Vector(*ring['center']))
            actual = source.get_actor_location()
            error = (expected - actual).length()
            assert error < .1, ('Detached tire source', vehicle['label'], i, error)
            x, y, z = ring['center'];side = 1 if y > 0 else -1
            radius = (assets[vehicle['model']]['inner_radius_cm'] + ring['extent'][0]) * .5
            normal = unreal.MathLibrary.transform_direction(transform, unreal.Vector(0, side, 0))
            def probe(local):
                return source.get_surface_temperature_with_normal(transform.transform_location(unreal.Vector(*local)), normal)
            tread = [probe((x + radius * math.cos(a), y + side * ring['extent'][1] * .9, z + radius * math.sin(a)))
                     for a in (0, math.pi / 2, math.pi, math.pi * 1.5)]
            rim_point = actual_rims[vehicle['model']][i]['point'] if vehicle['model'] in actual_rims else (x, y + side * ring['extent'][1], z)
            rim = probe(rim_point)
            samples.append({'tire': i, 'source_attachment_error_cm': error, 'tread_surface_k': tread, 'rim_surface_k': rim,
                            'source_k': source.get_editor_property('temperature_kelvin'),
                            'rim_probe_local_cm': list(rim_point),
                            'inner_radius_cm': source.get_editor_property('parent_contact_inner_radius_cm'),
                            'outer_radius_cm': source.get_editor_property('parent_contact_outer_radius_cm')})
        results.append({'label': vehicle['label'], 'model': vehicle['model'], 'state': vehicle['state'], 'tires': samples})
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    lights = []
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        if isinstance(actor, (unreal.DirectionalLight, unreal.SkyLight)):
            lights.append({'actor': actor.get_actor_label(), 'class': actor.get_class().get_name(),
                           'intensity': actor.light_component.get_editor_property('intensity')})
        if actor.get_actor_label().startswith('Sample_WarmLamp'):
            for light in actor.get_components_by_class(unreal.PointLightComponent):
                lights.append({'actor': actor.get_actor_label(), 'class': 'PointLightComponent',
                               'intensity': light.intensity, 'temperature_k': light.temperature})
    emitters = [{'class': s.get_class().get_name(), 'temperature_k': s.temperature_kelvin}
                for s in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.ThermalSource)
                if 'SampleCounterHeat' in s.get_class().get_name() or 'SampleLampHeat' in s.get_class().get_name()]
    report = {'id': state['id'], 'elapsed': state['elapsed'], 'source_count': state['source_count'],
              'vehicles': results, 'lights': lights, 'environment_emitters': emitters}
    (root / 'Saved/SceneDiversity' / (state['id'] + '_surface_checks.json')).write_text(json.dumps(report, indent=2))
    return report

result = validate_live()
