"""Enumerate effective object baselines and heat sources without retaining UE wrappers."""
import collections
import json
import math
from pathlib import Path
import unreal


def audit_environment(game=False, suffix='editor'):
    root=Path(unreal.Paths.project_dir()).resolve()
    system=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world=system.get_game_world() if game else system.get_editor_world()
    assert world and 'ThermalDiversity_05_CombinedEnvironment.' in world.get_path_name()
    actors=unreal.GameplayStatics.get_all_actors_of_class(world,unreal.Actor)
    rows=[];sources=[];categories=collections.Counter();issues=[]
    def tags(values):
        return {str(t).split('=',1)[0]:str(t).split('=',1)[1] for t in values if '=' in str(t)}
    for actor in actors:
        if isinstance(actor,unreal.ThermalSource):
            parent=actor.get_editor_property('parent_receiver') or actor.get_attach_parent_actor() or actor.get_parent_actor()
            p=actor.get_actor_location()
            sources.append({'path':actor.get_path_name(),'parent':parent.get_actor_label() if parent else None,
                'kelvin':float(actor.get_editor_property('temperature_kelvin')),'enabled':bool(actor.get_editor_property('enabled')),
                'range_cm':float(actor.get_editor_property('range_cm')),'parent_contact_radius_cm':float(actor.get_editor_property('parent_contact_radius_cm')),
                'position_cm':[p.x,p.y,p.z]})
        for c in actor.get_components_by_class(unreal.StaticMeshComponent):
            mesh=c.get_editor_property('static_mesh')
            if not mesh:
                continue
            at=tags(actor.tags);ct=tags(c.component_tags)
            values={'temperature_k':295.,'emissivity':.9,'temperature_origin':'fallback','emissivity_origin':'fallback'}
            for owner,tagset,prefix in [('actor',at,'ThermalBaseline'),('component',ct,'ThermalBaseline'),('actor',at,'ThermalTemp'),('component',ct,'ThermalTemp')]:
                tk='ThermalBaselineK' if prefix=='ThermalBaseline' else 'ThermalTempK'
                ek='ThermalBaselineEmissivity' if prefix=='ThermalBaseline' else 'ThermalEmissivity'
                if tk in tagset:values.update(temperature_k=float(tagset[tk]),temperature_origin=owner+':'+tk)
                if ek in tagset:values.update(emissivity=float(tagset[ek]),emissivity_origin=owner+':'+ek)
            response=actor.get_component_by_class(unreal.load_class(None,'/Script/AirSim.ThermalReceiverComponent'))
            if response:
                values.update(temperature_k=float(response.get_editor_property('baseline_temperature_kelvin')),
                              emissivity=float(response.get_editor_property('emissivity')),
                              temperature_origin='ThermalReceiverComponent',emissivity_origin='ThermalReceiverComponent')
            category=ct.get('ThermalCategory',at.get('ThermalCategory','missing'))
            ignored=any(str(t)=='ThermalIgnore' for t in list(actor.tags)+list(c.component_tags))
            instances=c.get_instance_count() if isinstance(c,unreal.InstancedStaticMeshComponent) else 1
            name=mesh.get_name();lower=name.lower()
            row={'actor':actor.get_actor_label(),'component':c.get_path_name(),'mesh':mesh.get_path_name(),
                'instances':instances,'category':category,'ignored':ignored,'visible':c.is_visible(),
                'materials':[c.get_material(i).get_name() if c.get_material(i) else None for i in range(c.get_num_materials())],**values}
            row['temperature_c']=row['temperature_k']-273.15
            rows.append(row);categories[category]+=instances
            if not ignored and (values['temperature_origin']=='fallback' or values['emissivity_origin']=='fallback'):
                issues.append({'component':row['component'],'issue':'missing_explicit_baseline','mesh':name})
            if 'roadblock' in lower and category=='road':
                issues.append({'component':row['component'],'issue':'roadblock_classified_as_asphalt','mesh':name})
            if 'pickup' in lower and category!='vehicle':
                issues.append({'component':row['component'],'issue':'pickup_classification','mesh':name})
            if any(token in lower for token in ('lamp','trafficlight','streetlight')) and category=='road':
                issues.append({'component':row['component'],'issue':'light_classified_as_road','mesh':name})
            if not all(math.isfinite(values[k]) for k in ('temperature_k','emissivity')) or not 0<values['emissivity']<=1:
                issues.append({'component':row['component'],'issue':'invalid_thermal_value','mesh':name})
    water=[r for r in rows if 'waterplane' in r['mesh'].lower()]
    bad_sources=[s for s in sources if s['parent'] and 'water' in s['parent'].lower()]
    report={'world':world.get_path_name(),'scope':'effective per-component uniform baseline; source targets separate from surface solution',
        'components':len(rows),'instances':sum(r['instances'] for r in rows),'categories_by_instance':dict(categories),
        'issue_count':len(issues),'issues':issues,'decorative_water_components':len(water),
        'decorative_water_all_ignored':all(r['ignored'] for r in water),'water_sources':bad_sources,
        'rows':rows,'sources':sources}
    out=root/'Saved/SceneDiversity/TemperatureAudit';out.mkdir(parents=True,exist_ok=True)
    (out/('environment_'+suffix+'.json')).write_text(json.dumps(report,indent=2))
    summary={k:v for k,v in report.items() if k not in ('rows','sources','issues')}
    summary['issues_by_type']=dict(collections.Counter(i['issue'] for i in issues))
    return summary


result=audit_environment()
