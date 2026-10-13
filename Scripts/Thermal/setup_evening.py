"""Level-only dusk lighting and reusable lamp heat fixtures near the Hatchback."""
import json
import re
from pathlib import Path
import unreal

ROOT = Path(unreal.Paths.project_dir()).resolve()
OUTPUT = ROOT / 'Saved/ThermalScene'
FOLDER = '/Game/Thermal/Blueprints'
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
level = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
assets = unreal.AssetToolsHelpers.get_asset_tools()
subobjects = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
library = unreal.SubobjectDataBlueprintFunctionLibrary
all_actors = actors.get_all_level_actors()
car = next(a for a in all_actors if a.get_actor_label() == 'SM_Hatchback')
sky = next(a for a in all_actors if a.get_class().get_name() == 'BP_Sky_Sphere_C')
sun = next(a for a in all_actors if isinstance(a, unreal.DirectionalLight))
sun.set_actor_rotation(unreal.Rotator(pitch=-2, yaw=-50, roll=0), False)
sun.light_component.set_editor_property('intensity', .22)
sun.light_component.set_editor_property('light_color', unreal.Color(r=255, g=159, b=102, a=255))
sky_values = {
    'Colors determined by sun position': False,
    'Sun brightness': 2.0, 'Stars brightness': .25, 'Cloud opacity': 1.15,
    'Horizon falloff': 3.0,
    'Zenith color': unreal.LinearColor(.004, .009, .025, 1),
    'Horizon color': unreal.LinearColor(.10, .035, .017, 1),
    'Cloud color': unreal.LinearColor(.025, .030, .055, 1),
    'Overall color': unreal.LinearColor(1, 1, 1, 1),
}
for key, value in sky_values.items(): sky.set_editor_property(key, value)
sky.call_method('RefreshMaterial')
skylight = next(a for a in all_actors if isinstance(a, unreal.SkyLight))
skylight.light_component.set_editor_property('intensity', .15)
skylight.light_component.set_editor_property('light_color', unreal.Color(r=155, g=180, b=255, a=255))
skylight.light_component.recapture_sky()
# Stop adaptation from turning the evening scene back into daylight.
for a in all_actors:
    if not isinstance(a, unreal.PostProcessVolume): continue
    pp = a.get_editor_property('settings')
    for key, value in {
        'override_auto_exposure_min_brightness': True,
        'override_auto_exposure_max_brightness': True,
        'auto_exposure_min_brightness': 1.0,
        'auto_exposure_max_brightness': 1.0,
        'override_auto_exposure_bias': True,
        'auto_exposure_bias': 1.5,
    }.items(): pp.set_editor_property(key, value)
    a.set_editor_property('settings', pp)


def lamp_material(name, original, scalar, vector, strength):
    path = '/Game/Thermal/Materials/' + name
    mi = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
    if not mi:
        mi = unreal.EditorAssetLibrary.duplicate_asset(original, path)
    unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(mi, scalar, strength)
    unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(mi, vector, unreal.LinearColor(1, .45, .15, 1))
    if not unreal.EditorAssetLibrary.save_loaded_asset(mi): raise RuntimeError('Material save failed')
    return mi


glass = lamp_material('MI_EveningParkLampGlass', '/Game/CityPark/Materials/Props/MI_LampPost01Glass', 'Emissive', 'Emissive', 2)
street = lamp_material('MI_EveningStreetLamp', '/Game/CityPark/Materials/Props/MI_LampPost02', 'Emmisive Str', 'Emmisive color', 4)
glow_path = '/Game/Thermal/Materials/M_EveningLampEmitter'
glow = unreal.load_asset(glow_path) if unreal.EditorAssetLibrary.does_asset_exist(glow_path) else None
if not glow:
    glow = assets.create_asset('M_EveningLampEmitter', '/Game/Thermal/Materials', unreal.Material, unreal.MaterialFactoryNew())
    glow.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_UNLIT)
    color = unreal.MaterialEditingLibrary.create_material_expression(glow, unreal.MaterialExpressionConstant3Vector, 0, 0)
    color.set_editor_property('constant', unreal.LinearColor(5, 2.25, .75, 1))
    unreal.MaterialEditingLibrary.connect_material_property(color, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    unreal.MaterialEditingLibrary.recompile_material(glow)
    if not unreal.EditorAssetLibrary.save_loaded_asset(glow): raise RuntimeError('Glow material save failed')


def fixture(name, light_class, intensity, radius):
    path = FOLDER + '/' + name
    bp = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
    if not bp:
        factory = unreal.BlueprintFactory()
        factory.set_editor_property('parent_class', unreal.load_class(None, '/Script/AirSim.ThermalSource'))
        bp = assets.create_asset(name, FOLDER, unreal.Blueprint, factory)
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    cls = unreal.load_class(None, path + '.' + name + '_C')
    default = unreal.get_default_object(cls)
    for key, value in {
        'source_type': unreal.ThermalSourceType.POINT,
        'temperature_kelvin': 333.15, 'range_cm': 100.0, 'radius_cm': 12.0,
        'parent_contact_radius_cm': 50.0, 'parent_conductance': 200.0,
        'heat_parent_surface': True, 'occlusion': True, 'power_scale': 1.0,
    }.items(): default.set_editor_property(key, value)
    handles = subobjects.k2_gather_subobject_data_for_blueprint(bp)
    by_name = {str(library.get_variable_name(library.get_data(h))): h for h in handles}
    handle = by_name.get('VisibleLamp')
    if not handle:
        parent = next(h for h in handles if isinstance(library.get_object(library.get_data(h)), unreal.SceneComponent))
        handle, error = subobjects.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=parent, new_class=light_class, blueprint_context=bp))
        if not library.is_handle_valid(handle): raise RuntimeError(str(error))
        subobjects.rename_subobject(handle, unreal.Text('VisibleLamp'))
    light = library.get_object_for_blueprint(library.get_data(handle), bp)
    for key, value in {
        'mobility': unreal.ComponentMobility.MOVABLE,
        'relative_location': unreal.Vector(0, 0, -8),
        'intensity_units': unreal.LightUnits.CANDELAS, 'intensity': intensity,
        'attenuation_radius': radius, 'cast_shadows': False,
        'use_temperature': True, 'temperature': 3000.0,
        'volumetric_scattering_intensity': 0.0,
        'indirect_lighting_intensity': 0.0,
        'max_draw_distance': 6500.0, 'max_distance_fade_range': 1500.0,
    }.items(): light.set_editor_property(key, value)
    if light_class == unreal.SpotLightComponent:
        light.set_editor_property('relative_rotation', unreal.Rotator(pitch=-90, yaw=0, roll=0))
        light.set_editor_property('inner_cone_angle', 35.0)
        light.set_editor_property('outer_cone_angle', 50.0)
    # Give the lamp a real visible emitter surface. The original street-lamp
    # texture does not reliably expose its lens through the emissive mask.
    lens_handle = by_name.get('WarmEmitterSurface')
    if not lens_handle:
        parent = next(h for h in handles if isinstance(library.get_object(library.get_data(h)), unreal.SceneComponent))
        lens_handle, error = subobjects.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=parent, new_class=unreal.StaticMeshComponent, blueprint_context=bp))
        if not library.is_handle_valid(lens_handle): raise RuntimeError(str(error))
        subobjects.rename_subobject(lens_handle, unreal.Text('WarmEmitterSurface'))
    lens = library.get_object_for_blueprint(library.get_data(lens_handle), bp)
    lens.set_editor_property('mobility', unreal.ComponentMobility.MOVABLE)
    lens.set_editor_property('static_mesh', unreal.load_asset('/Engine/BasicShapes/Cube' if light_class == unreal.SpotLightComponent else '/Engine/BasicShapes/Sphere'))
    lens.set_editor_property('relative_location', unreal.Vector(0, 0, -3.2) if light_class == unreal.SpotLightComponent else unreal.Vector())
    lens.set_editor_property('relative_scale3d', unreal.Vector(.38, .22, .02) if light_class == unreal.SpotLightComponent else unreal.Vector(.12, .12, .12))
    lens.set_editor_property('cast_shadow', False)
    lens.set_editor_property('component_tags', [unreal.Name('ThermalTempK=328.15'), unreal.Name('ThermalEmissivity=0.95')])
    lens.set_collision_profile_name('NoCollision')
    lens.set_material(0, glow)
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    if not unreal.EditorAssetLibrary.save_loaded_asset(bp): raise RuntimeError('Fixture save failed')
    return cls


park_class = fixture('BP_EveningParkLampSource', unreal.PointLightComponent, 100, 750)
street_class = fixture('BP_EveningStreetLampSource', unreal.SpotLightComponent, 900, 1700)
selected = []
for a in all_actors:
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        mesh = c.get_editor_property('static_mesh')
        if not mesh or not mesh.get_name().startswith('SM_LampPost'): continue
        delta = a.get_actor_location() - car.get_actor_location()
        if (delta.x * delta.x + delta.y * delta.y) ** .5 > 3000: continue
        selected.append((a, c, mesh.get_name()))
for a in all_actors:
    if a.actor_has_tag('ThermalEveningFixture'): actors.destroy_actor(a)
report = {'map': '/Game/CityPark/Maps/Showcase_CoordinateCrop', 'radius_m': 30, 'lamps': [], 'short_lamps_off': []}
shorts = sorted((a for a, c, name in selected if name == 'SM_LampPost01'), key=lambda a: int(re.search(r'(\d+)$', a.get_actor_label()).group(1)))
enabled_shorts = {a.get_path_name() for a in shorts[::3]}
for a, c, name in selected:
    if name == 'SM_LampPost01':
        if a.get_path_name() not in enabled_shorts:
            c.set_material(1, unreal.load_asset('/Game/CityPark/Materials/Props/MI_LampPost01Glass'))
            report['short_lamps_off'].append(a.get_actor_label())
            continue
        positions = [unreal.Vector(0, 0, 364.4355)]
        cls = park_class
        c.set_material(1, glass)
    elif name in ('SM_LampPost02_1', 'SM_LampPost02_2'):
        positions = [unreal.Vector(-269.445, 0, 1039.72)]
        if name == 'SM_LampPost02_2': positions.append(unreal.Vector(269.445, 0, 1039.72))
        cls = street_class
        c.set_material(0, street)
    else:
        positions = [unreal.Vector(0, 0, 458.05)]
        cls = park_class
        c.set_material(0, street)
    for index, local in enumerate(positions):
        world = c.get_world_transform().transform_location(local)
        source = actors.spawn_actor_from_class(cls, world, unreal.Rotator())
        source.set_actor_label('Evening_' + a.get_actor_label() + '_' + str(index + 1))
        source.set_editor_property('tags', [unreal.Name('ThermalEveningFixture')])
        source.set_editor_property('parent_receiver', a)
        source.attach_to_actor(a, '', unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, False)
        source.set_folder_path('Thermal/EveningStreetLights')
        report['lamps'].append({'pole': a.get_actor_label(), 'mesh': name, 'source': source.get_actor_label(), 'location': list(world.to_tuple())})
report['fixture_count'] = len(report['lamps'])
report['pole_count'] = len(selected)
report['active_short_lamps'] = len(enabled_shorts)
report['active_tall_lamps'] = len(report['lamps']) - len(enabled_shorts)
report['source_celsius'] = 60
report['visible_light_kelvin'] = 3000
# Only two large trees overlap these small emitters. Their default 8 cm heat
# sampling stores the entire canopy; 32 cm is sufficient for diffuse tree heat.
# Keep the car and the small lamp receivers at their existing detailed spacing.
report['coarse_tree_receivers'] = []
receiver_class = unreal.load_class(None, '/Script/AirSim.ThermalReceiverComponent')
emitter_positions = [row['location'] for row in report['lamps']]
for a in all_actors:
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        tags = [str(t) for t in c.get_editor_property('component_tags')]
        if 'ThermalCategory=tree' not in tags: continue
        origin, extent, _ = unreal.SystemLibrary.get_component_bounds(c)
        if not any(sum(max(0, abs(p[i] - origin.to_tuple()[i]) - extent.to_tuple()[i]) ** 2 for i in range(3)) <= 100 ** 2 for p in emitter_positions): continue
        responses = a.get_components_by_class(receiver_class)
        if responses:
            response = responses[0]
        else:
            handles = subobjects.k2_gather_subobject_data_for_instance(a)
            handle, error = subobjects.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=receiver_class))
            if not library.is_handle_valid(handle): raise RuntimeError(str(error))
            subobjects.rename_subobject(handle, unreal.Text('ThermalTreeResponse'))
            response = library.get_object(library.get_data(handle))
            values = {'ThermalBaselineK': 293.15, 'ThermalBaselineEmissivity': .97}
            for raw in [str(t) for t in a.get_editor_property('tags')] + tags:
                key, _, value = raw.partition('=')
                if key in values: values[key] = float(value)
            response.set_editor_property('baseline_temperature_kelvin', values['ThermalBaselineK'])
            response.set_editor_property('emissivity', values['ThermalBaselineEmissivity'])
        response.set_editor_property('sample_spacing_cm', 32.0)
        report['coarse_tree_receivers'].append(a.get_actor_label())
if not level.save_current_level(): raise RuntimeError('Evening map save failed')
(OUTPUT / 'evening_setup.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
unreal.log('THERMAL_EVENING_SAVED: ' + json.dumps(report))
