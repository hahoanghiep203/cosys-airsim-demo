"""Create four isolated scene assets and model-specific attached thermal Blueprints."""
import hashlib
import json
from pathlib import Path
import unreal


def _ground_height(world, x, y):
    ignored = [a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
               if a.get_actor_label().startswith(('Sample_','Combined_','Diversity_'))]
    hit = unreal.SystemLibrary.line_trace_single(world, unreal.Vector(x,y,2500), unreal.Vector(x,y,-2000),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, ignored, unreal.DrawDebugTrace.NONE, True)
    if not hit:
        raise RuntimeError('No ground at ' + str((x,y)))
    fields = unreal.get_default_object(unreal.GameplayStatics.static_class()).call_method('BreakHitResult',(hit,))
    label = fields[9].get_actor_label() if fields[9] else ''
    if fields[7].z < .97 or not ('Landscape' in label or 'Road' in label or 'Pavement' in label):
        raise RuntimeError('Unsafe placement on ' + label + ' at ' + str((x,y)))
    return fields[5].z


def _clear_combined_scenery(actors, scene):
    """Clear only instanced vegetation inside the four new sample lots."""
    counts = {'instances':0,'components':0}
    boxes = [unreal.Box(min=unreal.Vector(z['center_cm'][0]-2300,z['center_cm'][1]-1500,-1000),
                        max=unreal.Vector(z['center_cm'][0]+2100,z['center_cm'][1]+1500,650)) for z in scene['zones']]
    for actor in actors.get_all_level_actors():
        for c in actor.get_components_by_class(unreal.InstancedStaticMeshComponent):
            mesh=c.get_editor_property('static_mesh')
            if not mesh:
                continue
            name=mesh.get_name().lower()
            if not any(word in name for word in ('elm','amur','pine','spruce','birch','maple','oak','bush','grass','flower','fir','shrub')):
                continue
            indices=set()
            for box in boxes:
                indices.update(c.get_instances_overlapping_box(box,True))
            if indices:
                assert c.remove_instances(sorted(indices)), name
                counts['instances']+=len(indices); counts['components']+=1
    return counts


def build_assets():
    root = Path(unreal.Paths.project_dir()).resolve()
    out = root / 'Saved/SceneDiversity'
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads((root / 'Config/SceneDiversity/scenes.json').read_text())
    wheels = json.loads((out / 'wheel_candidates.json').read_text())
    folder = '/Game/Thermal/SceneDiversity'
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary
    protected = [root / 'Content/CityPark/Maps' / (n + '.umap') for n in
                 ('Showcase', 'Showcase_CoordinateCrop', 'Showcase_EveningSample')]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}

    def bp(name, parent):
        path = folder + '/' + name
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            asset = unreal.load_asset(path)
        else:
            factory = unreal.BlueprintFactory()
            factory.set_editor_property('parent_class', parent)
            asset = tools.create_asset(name, folder, unreal.Blueprint, factory)
        unreal.BlueprintEditorLibrary.compile_blueprint(asset)
        return asset, unreal.load_class(None, path + '.' + name + '_C')

    def preset(name, values):
        asset, cls = bp(name, unreal.load_class(None, '/Script/AirSim.ThermalSource'))
        for key, value in values.items():
            unreal.get_default_object(cls).set_editor_property(key, value)
        unreal.BlueprintEditorLibrary.compile_blueprint(asset)
        assert unreal.EditorAssetLibrary.save_loaded_asset(asset)
        return cls

    def component(asset, parent, name, cls):
        handles = sub.k2_gather_subobject_data_for_blueprint(asset)
        existing = next((h for h in handles if str(lib.get_variable_name(lib.get_data(h))) == name), None)
        if existing is None:
            existing, error = sub.add_new_subobject(unreal.AddNewSubobjectParams(
                parent_handle=parent, new_class=cls, blueprint_context=asset))
            assert lib.is_handle_valid(existing), str(error)
            sub.rename_subobject(existing, unreal.Text(name))
        return lib.get_object_for_blueprint(lib.get_data(existing), asset)

    model_settings = {
        'Hatchback': (25.5, 19.6, (125, 0, 93), (193, 52, 65)),
        'SUV': (33, 24, (166, 0, 106), (210, 65, 78)),
        'Pickup': (29, 22.2, (162, 5, 97), (208, 62, 62)),
        'SportsCar': (31, 27.1, (155, 0, 58), (212, 70, 42)),
        'Truck_Box': (41, 28.2, (291, 0, 126), (338, 67, 71)),
    }
    manifest = {}
    for model, (minimum, inner, hood_pos, light_pos) in model_settings.items():
        rings = [w for w in wheels[model] if min(w['extent'][0], w['extent'][2]) > minimum
                 and abs(w['extent'][0] - w['extent'][2]) < 1.2]
        assert len(rings) == (6 if model == 'Truck_Box' else 4), (model, len(rings))
        rings.sort(key=lambda w: (w['center'][0], w['center'][1]))
        tire = preset('BP_' + model + '_TireHeat', {
            'temperature_kelvin': 291.15, 'source_type': unreal.ThermalSourceType.POINT,
            'range_cm': 1., 'radius_cm': 1., 'power_scale': 1., 'occlusion': True,
            'heat_parent_surface': True, 'parent_conductance': 140.,
            'parent_contact_region': unreal.ThermalContactRegion.FINITE_CYLINDER,
            'parent_contact_inner_radius_cm': inner,
            'parent_contact_outer_radius_cm': max(w['extent'][0] for w in rings) + .8,
            'parent_contact_half_length_cm': max(w['extent'][1] for w in rings) + .4})
        hood = preset('BP_' + model + '_HoodHeat', {
            'temperature_kelvin': 291.15, 'source_type': unreal.ThermalSourceType.RECT,
            'range_cm': 95., 'radius_cm': 15., 'rect_width_cm': 100., 'rect_height_cm': 75.,
            'parent_contact_radius_cm': 12. if model == 'SportsCar' else 68.,
            'parent_material_indices': [1] if model == 'SportsCar' else [],
            'parent_conductance': 125., 'occlusion': True})
        head = preset('BP_' + model + '_HeadlightHeat', {
            'temperature_kelvin': 291.15, 'source_type': unreal.ThermalSourceType.SPOT,
            'range_cm': 80., 'radius_cm': 12., 'parent_contact_radius_cm': 23.,
            'parent_conductance': 170., 'occlusion': True})
        asset, cls = bp('BP_Thermal_' + model, unreal.StaticMeshActor)
        default = unreal.get_default_object(cls)
        mesh = unreal.load_asset('/Game/VehicleVarietyPack/Meshes/SM_' + model)
        if not mesh.get_editor_property('allow_cpu_access'):
            mesh.set_editor_property('allow_cpu_access', True)
            unreal.EditorAssetLibrary.save_loaded_asset(mesh)
        default.static_mesh_component.set_static_mesh(mesh)
        default.static_mesh_component.set_editor_property('mobility', unreal.ComponentMobility.MOVABLE)
        handles = sub.k2_gather_subobject_data_for_blueprint(asset)
        parent = next(h for h in handles if isinstance(lib.get_object(lib.get_data(h)), unreal.StaticMeshComponent))
        specifications = [('Tire_' + str(i), tire, w['center'], unreal.Rotator(yaw=90), w)
                          for i, w in enumerate(rings)]
        specifications += [('HoodHeat', hood, hood_pos, unreal.Rotator(pitch=-90), None)]
        specifications += [('Headlight_' + str(i), head, (light_pos[0], sign * light_pos[1], light_pos[2]),
                            unreal.Rotator(), None) for i, sign in enumerate((-1, 1))]
        for name, child_cls, position, rotation, wheel in specifications:
            child = component(asset, parent, name, unreal.ChildActorComponent)
            child.set_editor_property('mobility', unreal.ComponentMobility.MOVABLE)
            child.set_editor_property('child_actor_class', child_cls)
            child.set_editor_property('relative_location', unreal.Vector(*position))
            child.set_editor_property('relative_rotation', rotation)
            if name == 'HoodHeat' and model == 'SportsCar':
                template = child.get_editor_property('child_actor_template')
                if template:
                    template.set_editor_property('parent_contact_radius_cm', 12.)
                    template.set_editor_property('parent_material_indices', [1])
            if wheel:
                template = child.get_editor_property('child_actor_template')
                if template:
                    template.set_editor_property('power_scale', 1.)
                    template.set_editor_property('range_cm', 1.)
                    template.set_editor_property('radius_cm', 1.)
                    template.set_editor_property('parent_contact_outer_radius_cm', max(wheel['extent'][0], wheel['extent'][2]) + .8)
                    template.set_editor_property('parent_contact_half_length_cm', wheel['extent'][1] + .4)
        for i, sign in enumerate((-1, 1)):
            light = component(asset, parent, 'VisibleHeadlight_' + str(i), unreal.SpotLightComponent)
            for key, value in {'mobility': unreal.ComponentMobility.MOVABLE,
                               'relative_location': unreal.Vector(light_pos[0] + 5, sign * light_pos[1], light_pos[2]),
                               'intensity_units': unreal.LightUnits.CANDELAS, 'intensity': 90.,
                               'attenuation_radius': 1100., 'inner_cone_angle': 16., 'outer_cone_angle': 32.,
                               'cast_shadows': False}.items():
                light.set_editor_property(key, value)
        unreal.BlueprintEditorLibrary.compile_blueprint(asset)
        assert unreal.EditorAssetLibrary.save_loaded_asset(asset)
        manifest[model] = {'blueprint': folder + '/BP_Thermal_' + model, 'tires': rings, 'inner_radius_cm': inner,
                           'hood_cm': hood_pos, 'headlight_cm': light_pos}
    (out / 'vehicle_assets.json').write_text(json.dumps(manifest, indent=2))
    (out / 'protected_maps.json').write_text(json.dumps(hashes, indent=2))
    return {'vehicles': {k: len(v['tires']) for k, v in manifest.items()}}


def build_scene(scene_id, resume=False):
    root = Path(unreal.Paths.project_dir()).resolve()
    out = root / 'Saved/SceneDiversity'
    config = json.loads((root / 'Config/SceneDiversity/scenes.json').read_text())
    scene = next(s for s in config['scenes'] if s['id'] == scene_id)
    target = scene['map']
    if resume:
        current=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        assert scene.get('ground_trace') and target+'.' in current.get_path_name(), 'Resume only the currently open combined map'
    else:
        assert not unreal.EditorAssetLibrary.does_asset_exist(target), 'Refuse to overwrite existing scene: ' + target
        assert unreal.EditorLevelLibrary.new_level_from_template(target, '/Game/CityPark/Maps/Showcase_EveningSample')
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    for a in actors.get_all_level_actors():
        if a.get_actor_label() in ('Sample_Vehicle_HotHatchback', 'Sample_Vehicle_ColdSUV'):
            actors.destroy_actor(a)
        elif resume and a.get_actor_label().startswith(('Combined_','Diversity_')):
            actors.destroy_actor(a)
    clearance = _clear_combined_scenery(actors,scene) if scene.get('ground_trace') else None
    records = []
    for v in scene['vehicles']:
        model = v['model']
        path = '/Game/Thermal/SceneDiversity/BP_Thermal_' + model
        cls = unreal.load_class(None, path + '.BP_Thermal_' + model + '_C')
        if scene.get('ground_trace'):
            v['start_cm'][2] = _ground_height(world,*v['start_cm'][:2])+4
            v['end_cm'][2] = v['start_cm'][2]
        actor = actors.spawn_actor_from_class(cls, unreal.Vector(*v['start_cm']), unreal.Rotator(yaw=v.get('yaw', 0)))
        actor.set_actor_label(v['label']);actor.set_folder_path('Thermal Diversity/'+v.get('zone','Vehicles')+'/Vehicles')
        actor.tags = [unreal.Name('ScenePerformanceKeep'), unreal.Name('ThermalDiversity'),
                      unreal.Name('ThermalTempK=' + str(scene['ambient_k'])), unreal.Name('ThermalEmissivity=0.92')]
        records.append({'label': v['label'], 'asset': path, 'state': v['state']})
    for i, spec in enumerate(scene['props']):
        name, x, y, yaw = spec
        mesh = unreal.load_asset('/Game/CityPark/Meshes/Props/' + name)
        assert mesh, name
        b = mesh.get_bounds()
        floor = _ground_height(world,x,y)+1 if scene.get('ground_trace') else 110
        actor = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(x, y, floor - b.origin.z + b.box_extent.z), unreal.Rotator(yaw=yaw))
        actor.static_mesh_component.set_static_mesh(mesh)
        actor.set_actor_label('Diversity_' + name + '_' + str(i));actor.set_folder_path('Thermal Diversity/Props')
        actor.tags = [unreal.Name('ScenePerformanceKeep'), unreal.Name('ThermalDiversity')]
        records.append({'label': actor.get_actor_label(), 'asset': name})
    for fixture in scene.get('fixtures',[]):
        name=fixture['blueprint'].split('/')[-1]
        cls=unreal.load_class(None,fixture['blueprint']+'.'+name+'_C')
        x,y=fixture['xy_cm']
        actor=actors.spawn_actor_from_class(cls,unreal.Vector(x,y,_ground_height(world,x,y)+1),unreal.Rotator(yaw=fixture.get('yaw',0)))
        actor.set_actor_label(fixture['label']);actor.set_folder_path('Thermal Diversity/'+fixture['zone']+'/Fixtures')
        actor.tags=[unreal.Name('ScenePerformanceKeep'),unreal.Name('ThermalDiversity')]
        zone=next(z for z in scene['zones'] if z['id']==fixture['zone'])
        for light in actor.get_components_by_class(unreal.PointLightComponent):
            light.set_temperature(float(zone['lamp_kelvin']));light.set_intensity(float(zone['lamp_cd']))
        records.append({'label':fixture['label'],'asset':fixture['blueprint']})
    for a in actors.get_all_level_actors():
        if isinstance(a, unreal.DirectionalLight):
            a.set_actor_rotation(unreal.Rotator(pitch=scene['sun_pitch'], yaw=-35), False)
            a.light_component.set_editor_property('intensity', scene['sun_intensity'])
            a.light_component.set_editor_property('light_color', unreal.Color(*scene['sun_color'], 255))
        if isinstance(a, unreal.SkyLight):
            a.light_component.set_editor_property('intensity', scene['sky_intensity'])
            a.light_component.set_editor_property('light_color', unreal.Color(*scene['sky_color'], 255))
            a.light_component.recapture_sky()
        if a.get_class().get_name() == 'BP_Sky_Sphere_C':
            a.set_editor_property('Zenith color', unreal.LinearColor(*scene['zenith'], 1))
            a.set_editor_property('Horizon color', unreal.LinearColor(*scene['horizon'], 1))
            a.set_editor_property('Stars brightness', scene['stars'])
            a.call_method('RefreshMaterial')
        if a.get_actor_label().startswith('Sample_WarmLamp'):
            for light in a.get_components_by_class(unreal.PointLightComponent):
                light.set_temperature(float(scene['lamp_kelvin']))
                light.set_intensity(float(scene['lamp_cd']))
        if a.get_actor_label() == 'Sample_ThermalBaselines':
            celsius = scene['ambient_k'] - 273.15
            for key in ('tree', 'bush', 'grass', 'ground', 'building', 'metal', 'wood', 'vehicle', 'default'):
                a.set_editor_property(key + '_temperature_celsius', celsius)
            a.set_editor_property('road_temperature_celsius', celsius + scene['road_residual_c'])
            a.set_editor_property('concrete_temperature_celsius', celsius + scene['road_residual_c'] * .5)
            a.apply_scene_temperatures()
    position = unreal.Vector(*scene['preview_position_cm']);target_point = unreal.Vector(*scene['preview_target_cm'])
    rotation = unreal.MathLibrary.find_look_at_rotation(position, target_point)
    # Existing route plugin draws editable editor-only splines; markers stay out of sensor images.
    route_class = unreal.load_class(None, '/Script/AirSimRouteCapture.DroneCaptureRoute')
    point_class = unreal.load_class(None, '/Script/AirSimRouteCapture.DroneRoutePoint')
    assert route_class and point_class, 'Installed route capture plugin is required'
    routes = [('Camera', scene['camera_route_cm'])] if scene['camera_route_cm'] else []
    routes += [(v['model'], [v['start_cm'], v['end_cm']]) for v in scene['vehicles'] if v['state'] == 'driving' and v.get('motion_enabled',True)]
    for route_name, positions in routes:
        route = actors.spawn_actor_from_class(route_class, unreal.Vector(), unreal.Rotator())
        route.set_actor_label('Diversity_Route_' + route_name)
        route.set_folder_path('Thermal Diversity/Routes')
        route.set_editor_property('route_name', scene_id + ' ' + route_name)
        route.set_editor_property('vehicle_name', 'EveningSample')
        route.set_editor_property('rpc_port', 41471)
        points = []
        for i, point in enumerate(positions):
            point_position = unreal.Vector(*point)
            point_rotation = unreal.MathLibrary.find_look_at_rotation(point_position, target_point) if route_name == 'Camera' else unreal.Rotator()
            node = actors.spawn_actor_from_class(point_class, point_position, point_rotation)
            node.set_actor_label('Diversity_' + route_name + '_Node_' + str(i + 1))
            node.set_folder_path('Thermal Diversity/Routes')
            node.set_editor_property('demo_visible_in_game', False)
            node.tags = [unreal.Name('RouteCaptureMarker'), unreal.Name('ThermalIgnore')]
            points.append(node)
        route.set_editor_property('ordered_points', points)
        route.refresh_preview()
    for a in actors.get_all_level_actors():
        if isinstance(a, unreal.PlayerStart):
            a.set_actor_location_and_rotation(unreal.Vector(position.x, position.y, 220), rotation, False, True)
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(position, rotation)
    world.get_world_settings().set_editor_property('default_game_mode', unreal.load_class(None, '/Script/AirSim.AirSimGameMode'))
    assert unreal.EditorLevelLibrary.save_current_level()
    hashes = json.loads((out / 'protected_maps.json').read_text())
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    if scene.get('ground_trace'):
        (root/'Config/SceneDiversity/scenes.json').write_text(json.dumps(config,indent=2)+'\n')
    report = {'id': scene_id, 'map': scene['map'], 'new_objects': records, 'clearance':clearance, 'protected_maps_unchanged': True}
    (out / (scene_id + '_build.json')).write_text(json.dumps(report, indent=2))
    return report
