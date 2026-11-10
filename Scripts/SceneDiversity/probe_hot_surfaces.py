"""Probe exterior render triangles rather than collision hulls or source targets."""
import json
from pathlib import Path
import unreal


def probe_hot_surfaces():
    state=diversity_snapshot();assert state.get('ready')
    rows=[]
    exact=json.loads((Path(unreal.Paths.project_dir())/'Config/SceneDiversity/hot_surface_probes.json').read_text())
    for v in state['vehicles']:
        actor=unreal.find_object(None,state['actor_paths'][v['label']])
        assert actor.static_mesh_component.static_mesh.get_name()=='SM_'+v['model']
        for name,source in _diversity_sources(actor):
            if not any(key in name.lower() for key in ('hood','headlight')):
                continue
            key=next(k for k in exact[v['model']] if k in name)
            spec=exact[v['model']][key]
            transform=actor.get_actor_transform()
            point=transform.transform_location(unreal.Vector(*spec['point_cm']))
            normal=unreal.MathLibrary.transform_direction(transform,unreal.Vector(*spec['normal']))
            rows.append({'vehicle':v['label'],'state':v['state'],'source':name,
                'target_k':float(source.temperature_kelvin),'enabled':bool(source.enabled),'hit_parent':True,
                'surface_k':float(source.get_surface_temperature_with_normal(point,normal)),
                'point_cm':[point.x,point.y,point.z],'render_probe':spec})
    assert all(r['surface_k']>0 for r in rows),'A render probe failed to resolve'
    assert all(r['surface_k']>290.15 for r in rows if r['enabled']),'An active hot part remained at ambient'
    assert all(abs(r['surface_k']-289.15)<1 for r in rows if r['state']=='parked'),'A cold parked part is unexpectedly heated'
    (Path(unreal.Paths.project_dir())/'Saved/SceneDiversity/TemperatureAudit/hot_surface_probes.json').write_text(json.dumps(rows,indent=2))
    return {'probes':len(rows),'hit_parent':sum(r['hit_parent'] for r in rows),
            'unmatched':[r for r in rows if not r['hit_parent']],
            'enabled_surface_c':[{'vehicle':r['vehicle'],'source':r['source'],'target_c':r['target_k']-273.15,'surface_c':r['surface_k']-273.15}
                for r in rows if r['enabled'] and r['hit_parent']]}


result=probe_hot_surfaces()
