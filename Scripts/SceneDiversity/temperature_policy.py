"""Explicit combined-scene assumptions, applied after Blueprint spline construction."""
import json
from pathlib import Path

POLICY_VERSION='2026-10-23.2'


def profile_for_mesh(name, ambient_k, road_residual_c=3.):
    n=name.lower()
    def p(category, delta=0., emissivity=.9, ignored=False):
        return {'category':category,'temperature_k':ambient_k+delta,'emissivity':emissivity,'ignored':ignored}
    if 'waterplane' in n or n in ('planarreflectionplane','matineecam_sm','sm_cinecam'):
        return p('decorative_or_editor_helper',ignored=True)
    if 'sky' in n:
        return {'category':'sky_effective','temperature_k':270.,'emissivity':1.,'ignored':False}
    if 'kenney_' in n:
        return p('solar_equipment' if 'solar_panel' in n else 'process_or_storage_equipment',emissivity=.90)
    if n in ('cube','sphere','cone'):
        return p('generic_calibration_shape',emissivity=.90)
    if n in ('quadrotor1','propeller'):
        return p('unpowered_capture_platform',emissivity=.90)
    if any(t in n for t in ('roadblock','trafficbarrel','barrier')):
        return p('painted_barrier' if 'roadblock' in n else 'polymer_prop',emissivity=.95)
    if any(t in n for t in ('hatchback','sedan','suv','truck','pickup','sportscar','vehicle')):
        return p('vehicle',emissivity=.92)
    tree_name=n.startswith(('tree','sm_tree')) or '_tree' in n
    if tree_name or any(t in n for t in ('ivy','bush','plant','flower','grass','lawn','elm','maple','amur','willow','pine','oak','footballfield')):
        return p('vegetation',emissivity=.97)
    if any(t in n for t in ('dryleaves','stickdebris')):
        return p('dry_vegetation',emissivity=.94)
    if any(t in n for t in ('lamp','light','fence','railing','sign','trash','bin','hydrant','pole','manhole','footballgate','baseballgate','basketballhoop','metal')):
        return p('painted_metal',emissivity=.90)
    if any(t in n for t in ('asphalt','road','street')):
        return p('road',road_residual_c,.95)
    if 'water' in n:
        return p('water',emissivity=.98)
    if any(t in n for t in ('umbrella','net','newspaper')):
        return p('textile_or_paper',emissivity=.95)
    if any(t in n for t in ('bench','wood','table','chair','pier','foodstall','bower')):
        return p('furniture_or_stall',emissivity=.90)
    if any(t in n for t in ('path','square','concrete','sidewalk','bridge','curb','floor','border','tribune','tennisfield','basketballfield','tunnel')):
        return p('concrete',road_residual_c*.5,.95)
    if any(t in n for t in ('rock','soil','dirt','ground','statue','fountain','pool','baseballfield')):
        return p('ground_or_stone',emissivity=.93)
    if any(t in n for t in ('wall','roof','building','house')):
        return p('building',emissivity=.92)
    if 'leak' in n or 'decal' in n:
        return p('decorative_surface',emissivity=.95)
    return p('generic_reviewed_assumption')


def apply_temperature_policy(scene, game=False, migrate_legacy_samples=False):
    import collections
    import unreal
    root=Path(unreal.Paths.project_dir()).resolve()
    system=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world=system.get_game_world() if game else system.get_editor_world()
    assert world and 'ThermalDiversity_05_CombinedEnvironment.' in world.get_path_name()
    counts=collections.Counter();generic=set();records=[]
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world,unreal.Actor):
        components=actor.get_components_by_class(unreal.StaticMeshComponent)
        # These copied sample props inherited arbitrary 18–20 C overrides from
        # another sky preset. Retain their emissivity; use this scene's baseline.
        if migrate_legacy_samples and actor.get_actor_label().startswith('Sample_') and components:
            at=[t for t in actor.tags if not str(t).startswith('ThermalTempK=')]
            if game:actor.set_editor_property('tags',at,notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
            else:actor.tags=at
        for component in components:
            mesh=component.get_editor_property('static_mesh')
            if not mesh:
                continue
            profile=profile_for_mesh(mesh.get_name(),scene['ambient_k'],scene['road_residual_c'])
            tags=[t for t in component.component_tags if not str(t).startswith(('ThermalBaselineK=','ThermalBaselineEmissivity=','ThermalCategory=','ThermalPolicy='))]
            tags.extend(unreal.Name(t) for t in (
                'ThermalBaselineK='+str(profile['temperature_k']),
                'ThermalBaselineEmissivity='+str(profile['emissivity']),
                'ThermalCategory='+profile['category'],'ThermalPolicy='+POLICY_VERSION))
            if profile['ignored'] and 'ThermalIgnore' not in [str(t) for t in tags]:
                tags.append(unreal.Name('ThermalIgnore'))
            if game:component.set_editor_property('component_tags',tags,notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
            else:component.component_tags=tags
            counts[profile['category']]+=1
            if profile['category']=='generic_reviewed_assumption':generic.add(mesh.get_path_name())
            records.append({'component':component.get_path_name(),'mesh':mesh.get_path_name(),**profile})
    report={'version':POLICY_VERSION,'components':sum(counts.values()),'categories':dict(counts),
        'generic_material_assumptions':sorted(generic),'records':records,
        'scope':'Controlled blue-hour surface presets, not weather-measured or radiometrically calibrated truth. Uniform mixed-material objects use approximate effective emissivity.'}
    out=root/'Saved/SceneDiversity/TemperatureAudit';out.mkdir(parents=True,exist_ok=True)
    (out/('policy_game.json' if game else 'policy_editor.json')).write_text(json.dumps(report,indent=2))
    return {k:v for k,v in report.items() if k!='records'}
