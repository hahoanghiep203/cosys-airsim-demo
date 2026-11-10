"""Reversible draw distances on original CityPark. No asset saves or deletion."""
import collections
import json
import math
import re
import time
from pathlib import Path
import unreal

SCENE_OUTPUT=Path(unreal.Paths.project_dir()).resolve()/'Saved/ScenePerformance'
SCENE_OUTPUT.mkdir(parents=True,exist_ok=True)
SCENE_SNAPSHOTS=globals().get('SCENE_SNAPSHOTS',{})
SCENE_CVARS=globals().get('SCENE_CVARS',{})
SCENE_CONFIG=json.loads((SCENE_OUTPUT.parents[1]/'Config/ScenePerformance/balanced.json').read_text(encoding='utf-8-sig'))
# Store paths and scalar values only. Keeping HISM wrappers here makes Python's
# reference collector walk their large instance containers on every Unreal GC.
if SCENE_CONFIG['schema_version']!='1.0.0' or SCENE_CONFIG['distance_unit']!='m':
    raise ValueError('Unsupported performance profile version or distance unit')
if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in SCENE_CONFIG['draw_distances'].values()):
    raise ValueError('Draw distances must be positive finite meters')
SCENE_LOD_SCALE=float(SCENE_CONFIG['static_mesh_lod_distance_scale'])
if not math.isfinite(SCENE_LOD_SCALE) or not 1<=SCENE_LOD_SCALE<=4:
    raise ValueError('LOD distance scale must be between 1 and 4')
SCENE_PROFILES={'balanced':SCENE_CONFIG['draw_distances']}

def scene_world(game=False):
    system=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world=system.get_game_world() if game else system.get_editor_world()
    if not world or 'CityPark/Maps/' not in world.get_path_name() or not any(name in world.get_path_name() for name in ('Showcase', 'ThermalDiversity_')):
        raise RuntimeError('Profile is restricted to the original CityPark Showcase world')
    return world

def scene_components(world):
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world,unreal.Actor):
        for component in actor.get_components_by_class(unreal.StaticMeshComponent):
            mesh=component.get_editor_property('static_mesh')
            if mesh: yield actor,component,mesh

def scene_category(actor,component,mesh):
    path=mesh.get_path_name().lower()
    tags=[str(t).lower() for t in actor.tags]+[str(t).lower() for t in component.component_tags]
    protected_tags=[t.lower() for t in SCENE_CONFIG['protect_actor_or_component_tags']]
    if any(t in protected_tags or t.startswith('thermalsource') for t in tags):
        return 'protected'
    if '/vehiclevarietypack/' in path or 'drone' in actor.get_class().get_name().lower(): return 'protected'
    if '/citypark/meshes/' not in path: return 'protected'
    if any(x in path for x in ('dryleaves','grass','flower','leaf')): return 'grass'
    if any(x in path for x in ('/road/','/ground/','/buildings/','/architecture/')): return 'structure'
    if any(x in path for x in ('bush','hedge')): return 'bush'
    if 'tree' in path: return 'tree'
    # Asset bounds avoid treating one huge HISM cluster as one huge prop.
    bounds=mesh.get_bounds().box_extent
    scale=component.get_world_scale()
    diameter=2*max(abs(bounds.x*scale.x),abs(bounds.y*scale.y),abs(bounds.z*scale.z))
    if diameter>1000: return 'structure'
    return 'small_prop' if diameter<=150 else 'prop'

def scene_audit(game=False):
    world=scene_world(game);rows=[];meshes={};categories=collections.Counter()
    subsystem=unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    for actor,c,m in scene_components(world):
        category=scene_category(actor,c,m);categories[category]+=1
        path=m.get_path_name()
        if path not in meshes:
            meshes[path]={'lods':subsystem.get_lod_count(m),'components':0}
        meshes[path]['components']+=1
        instanced=isinstance(c,unreal.InstancedStaticMeshComponent)
        row={'actor':actor.get_actor_label(),'component':c.get_path_name(),'mesh':path,'category':category,
             'instances':c.get_instance_count() if instanced else 1,
             'draw_distance_cm':float(c.get_editor_property('ld_max_draw_distance')),
             'never_distance_cull':bool(c.get_editor_property('never_distance_cull')),
             'collision':str(c.get_collision_enabled())}
        if instanced:row['instance_cull_cm']=[c.get_editor_property('instance_start_cull_distance'),c.get_editor_property('instance_end_cull_distance')]
        rows.append(row)
    report={'map':world.get_path_name(),'components':len(rows),'instances':sum(r['instances'] for r in rows),
            'categories':dict(categories),'unique_meshes':len(meshes),'meshes':meshes,'rows':rows}
    (SCENE_OUTPUT/('inventory_game.json' if game else 'inventory.json')).write_text(json.dumps(report,indent=2))
    return {k:v for k,v in report.items() if k not in ('meshes','rows')}

def scene_apply(profile='balanced',game=False):
    if profile not in ('baseline',*SCENE_PROFILES):raise ValueError(profile)
    world=scene_world(game);key=world.get_path_name();snapshots=SCENE_SNAPSHOTS.setdefault(key,{})
    editor_key=re.sub(r'UEDPIE_\d+_','',key) if game else key
    editor_snapshot=SCENE_SNAPSHOTS.get(editor_key,{}) if game else {}
    if not SCENE_CVARS:
        SCENE_CVARS['r.StaticMeshLODDistanceScale']=unreal.SystemLibrary.get_console_variable_float_value('r.StaticMeshLODDistanceScale')
        for name in SCENE_CONFIG.get('console_variables', {}):
            SCENE_CVARS[name]=unreal.SystemLibrary.get_console_variable_float_value(name)
    counts=collections.Counter();changed=0
    for actor,c,m in scene_components(world):
        path=c.get_path_name();instanced=isinstance(c,unreal.InstancedStaticMeshComponent)
        if path not in snapshots:
            snapshots[path]={'distance':float(c.get_editor_property('ld_max_draw_distance')),
                             'collision':str(c.get_collision_enabled()),'never':bool(c.get_editor_property('never_distance_cull')),
                             'instance':(int(c.get_editor_property('instance_start_cull_distance')),int(c.get_editor_property('instance_end_cull_distance'))) if instanced else None}
            # PIE duplicates the editor's already-adjusted components. Restore
            # from the editor baseline so baseline in Play is truly original.
            original=editor_snapshot.get(path.replace(key,editor_key,1))
            if original:snapshots[path]={name:value for name,value in original.items() if name!='component'}
        old=snapshots[path]
        category=scene_category(actor,c,m);counts[category]+=1
        # Preserve deliberate never-cull flags, all non-scenery targets and existing shorter ranges.
        distance=old['distance'];instance=old['instance']
        if profile!='baseline' and category in SCENE_PROFILES[profile] and not old['never']:
            proposed=SCENE_PROFILES[profile][category]*100
            if instanced:
                original_end=old['instance'][1]
                end=int(min(original_end,proposed) if original_end>0 else proposed)
                instance=(min(int(end*.8),old['instance'][0]) if old['instance'][0]>0 else int(end*.8),end)
            else:
                distance=min(distance,proposed) if distance>0 else proposed
            changed+=1
        c.set_cull_distance(distance)
        if instanced:c.set_cull_distances(*instance)
        if str(c.get_collision_enabled())!=old['collision']:raise RuntimeError('Collision changed unexpectedly')
    scale=SCENE_CVARS['r.StaticMeshLODDistanceScale'] if profile=='baseline' else SCENE_LOD_SCALE
    unreal.SystemLibrary.execute_console_command(world,'r.StaticMeshLODDistanceScale '+str(scale))
    actual_cvars={}
    for name, value in SCENE_CONFIG.get('console_variables', {}).items():
        unreal.SystemLibrary.execute_console_command(world,name+' '+str(SCENE_CVARS[name] if profile=='baseline' else value))
        actual_cvars[name]=unreal.SystemLibrary.get_console_variable_float_value(name)
    report={'profile':profile,'map':key,'changed_components':changed,'categories':dict(counts),'lod_distance_scale':scale,
            'collision_unchanged':True,'saved_assets':False,'distances_m':SCENE_PROFILES.get(profile,{}),'actual_console_variables':actual_cvars}
    (SCENE_OUTPUT/('profile_game.json' if game else 'profile.json')).write_text(json.dumps(report,indent=2))
    return report

result={'loaded':True}

