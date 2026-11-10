"""Package compact verified local evidence; raw traces stay in Saved."""
import hashlib
import json
import shutil
import re
from pathlib import Path
root=Path(__file__).resolve().parents[2]
out=root/'Docs/ProjectMaintenance'
out.mkdir(parents=True,exist_ok=True)
saved=root/'Saved/ProjectMaintenance'
labels=['original_fixed_balanced_720p_1','original_fixed_baseline_720p','original_fixed_balanced_720p_2','crop_fixed_720p']
rows=[]
for label in labels:
    report=json.loads((saved/(label+'.json')).read_text())
    report.pop('wall_intervals',None);report.pop('world_deltas',None)
    assert report['gpu_after']['main_width']==1280 and report['gpu_after']['main_height']==720
    rows.append(report)
checks={name:json.loads((saved/(name+'.json')).read_text()) for name in ('rollback_check','crop_heating_check','canonical_ir_parity','route_install_check')}
audit=json.loads((saved/'asset_audit.json').read_text())
assert audit['candidate_count']==0 and audit['package_count']==1271
tests=json.loads((saved/'ThermalTests/index.json').read_text(encoding='utf-8-sig'))
assert tests['succeeded']==15 and tests['failed']==0
assert 'Ran 61 tests' in (saved/'route_tests.txt').read_text() and 'OK' in (saved/'route_tests.txt').read_text()
manifest=json.loads((out/'asset_quarantine.json').read_text())
for record in manifest['files']:
    archive=root/'AssetArchive/unused_20261021'/record['path']
    assert archive.is_file() and hashlib.sha256(archive.read_bytes()).hexdigest()==record['sha256']
    assert not (root/record['path']).exists()
user_map=root/'Content/CityPark/Maps/Showcase_CoordinateCrop.umap'
assert hashlib.sha256(user_map.read_bytes()).digest()==hashlib.sha256((saved/'before_20261021_155302/Showcase_CoordinateCrop.umap').read_bytes()).digest()
summary={'date':'2026-10-21','build':'UE5.7.4 Cosys_AirsimEditor Win64 Development succeeded','thermal_tests':15,'route_tests':61,'post_cleanup_packages':audit['package_count'],'unused_remaining_under_protected_root_policy':audit['candidate_count'],'quarantined_packages':len(manifest['packages']),'quarantined_bytes':manifest['bytes'],'user_map_sha256':hashlib.sha256(user_map.read_bytes()).hexdigest(),'measurements':rows,'checks':checks}
(out/'validation_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
engines=json.loads((saved/'engine_frame_summary.json').read_text())
selected=['Profile(20261021_161609).csv','Profile(20261021_161739).csv','Profile(20261021_161810).csv','Profile(20261021_162347).csv']
compact=[]
for label,filename in zip(labels,selected):
    report=next(r for r in engines if r['csv']==filename)
    compact.append({'label':label,'csv':filename,'frames':report['frames'],'engine_frame_time':report['summary']['FrameTime']})
(out/'engine_frame_summary.json').write_text(json.dumps(compact,indent=2),encoding='utf-8')
for name in ('car_gpu.png','area_gpu.png','lamp_gpu.png'):
    shutil.copy2(saved/name,out/name)
table='\n'.join(f"| {r['label'].replace('original_fixed_','Original ').replace('crop_fixed_','Heated scene ')} | {r['seconds']:.0f}s | {e['engine_frame_time']['fps']:.1f} | {r['ir_dispatch_hz']:.2f} | {e['engine_frame_time']['p95']:.1f}ms | {e['engine_frame_time']['max']:.1f}ms | {e['engine_frame_time']['over_100ms']} |" for r,e in zip(rows,compact))
text=f'''# Verified project maintenance — 21 October 2026

Cosys_Airsim is the main environment. Original CityPark, the existing evening thermal scene and the newer route demo are available through its project launchers. Old shortcuts forward to this project. Native project/plugin build succeeds; all15 thermal and61 route offline checks pass. Native route import/validation also passes in the migrated demo with four points, canonical relative JSON and Python paths.

## Stutter cause and correction

The old performance snapshot retained1,822 Unreal component wrappers across editor and Play worlds. UE's Python reference collector recursively examines reflected structs/containers in retained object wrappers, including large foliage instance arrays. The installed engine source confirms this in `PyWrapperObject.cpp` / `FPyWrapperObjectMetaData::AddInstanceReferencedObjects`.

Before the fix, natural GC reference traversal repeatedly took about1,855–2,254ms once per minute. A CPU trace isolated the cost to reachability, rather than deletion:732,770 references,74,090 objects, zero unreachable objects; gather took0.2ms. Serial GC still stalled. The fixed profile stores object paths and plain rollback values only. After dropping the unused wrappers, repeated scans took13.7–17.7ms in a deliberately accelerated5-second-GC probe. Normal parallel GC and its60-second interval were restored; experimental incremental reachability remains off.

Two subsequent90-second original-map moving-camera runs and a fresh65-second heated-scene run had zero engine frames over100ms. These are bounded observations, not a guarantee against every future hitch. Thermal CPU receiver lookup also now caches the owner/component lookup within each GPU-frame construction while retaining live per-component overrides.

## Actual 720p Play measurements

RTX5060Ti16GB, i5-14400F,32GB RAM; UE5.7.4, D3D12. One hidden/offscreen owned editor, normal RGB Play viewport plus visible GPU IR preview. Both outputs confirmed1280×720; no duplicate RGB thumbnail. Cameras followed the same repeatable moving sweep. IR Hz is **completed GPU dispatch count divided by wall time**, not the configured target. Engine FPS/p95/max come from the engine CSV profiler; UI callback timing is separately retained in JSON.

| Run | Duration | Engine FPS mean | IR dispatch Hz | Engine p95 | Engine max | Frames >100ms |
|---|---:|---:|---:|---:|---:|---:|
{table}

The heated map is the user's current, denser CoordinateCrop version; it has different scene cost from the original map. IR targets30Hz and measured29.57–30.00Hz in these runs. Do not interpret this as every view sustaining exactly30Hz or as packaged-game/physical-flight/paired-dataset throughput. The shorter baseline run is a limited combined distance/LOD/texture-budget comparison; no universal percentage speedup is claimed. Earlier A/B runs inherited editor culls in their Play baselines and are superseded by the corrected runs above.

The balanced texture budget is6GB instead of the800MB value observed after scalability in the earlier log. Its actual value is logged and capped to VRAM; it does not reserve all GPU memory. Native GPU IR avoids live CPU image readbacks. Heat simulation, physics, object management and paired recording still require CPU work. Recordings intentionally pause simulation while matching RGB/IR images; that contract is unchanged.

## Heating and image correctness

The user-modified CoordinateCrop map's SHA256 remains `{summary['user_map_sha256']}`. Seven car sources remain: four tire-rubber annular regions, hood and two headlights. Seven nearby evening-lamp sources remain. All four decorative water planes are tagged ignored and have zero thermal child sources. Car and wide IR views were visually inspected; the former decorative road rectangles are absent and tire rims remain dark.

Independent CPU radiance/surface lookup on the corrected opaque/masked inputs agrees with GPU output at car, street and lamp views. Mean differences are0.00189,0.000177 and0.0000966 of an8-bit display count;95th percentile is zero for all three views; maximum differences10,4,2counts. This checks numerical parity on shared geometry inputs, not measured real-world thermometry. Geometry exclusion is separately checked by the decorative tags and visual inspection.

## Cleanup and recovery

The audit protected every map, authored thermal/route/developer content, the vehicle library for scene diversity, plugin content and literal runtime path references; it followed hard/soft/searchable/manage registry dependencies synchronously.26 unreachable CityPark packages totaling64,597,120bytes were moved out of active Content into `AssetArchive/unused_20261021`. Post-cleanup registry contains1,271 protected/reachable packages and zero further candidates under that policy. Hashes of all archived files were rechecked.

The archive remains on disk, so this is active-project cleanup rather than permanent space reclamation. Keep it for recovery. No user map was overwritten, no original map was deleted, and the old project remains available. The migrated route-demo map alone was saved to replace its old absolute JSON path with a canonical relative path. Original editor distances and collision rollback passed with zero mismatches; all snapshot entries are plain values.

See [MAIN_PROJECT.md](MAIN_PROJECT.md) for launchers, render-distance/VRAM controls, whole-object/source temperature guidance and asset recovery. `validation_summary.json`, `engine_frame_summary.json` and `asset_quarantine.json` provide compact evidence. Raw CSVs, reports, before-fix CPU trace/export and backups remain in Saved/ProjectMaintenance (the large trace is also in the local visualization folder). No new commit or push was performed.

## Team

Used the explicitly requested [astra-team skill](C:/Users/Admin/.agents/skills/astra-team/SKILL.md). Native adviser traced the implementation; Antigravity gemini-4-argon-medium and local Qwen3-Coder30B supplied generic technical reviews, not proof of project correctness. Local inference completed and unloaded before Unreal opened. A further native escalation could not start because the app reported its agent limit; its unused reservation was released and the root completed profiling/integration. No model ran alongside Unreal.
'''
text=text.replace('RTX5060Ti16GB','RTX 5060 Ti (16 GB)').replace('Original balanced_720p_1','Original balanced, run 1').replace('Original balanced_720p_2','Original balanced, run 2').replace('Original baseline_720p','Original baseline').replace('Heated scene 720p','Heated scene')
text=re.sub(r'\b(all|and|retained|about|took|subsequent|fresh|over|confirmed|targets|measured|exactly|is|the|totaling|contains|views|its|reference traversal repeatedly took)(?=\d)',r'\1 ',text)
text=re.sub(r'(?<=\d)(ms|Hz|GB|MB|bytes|points|counts|views)\b',r' \1',text)
text=text.replace('deletion:732','deletion: 732').replace('references,74','references, 74').replace('i5-14400F,32','i5-14400F, 32').replace('newer route demo','newer route demo')
(out/'VALIDATION.md').write_text(text,encoding='utf-8')
print(json.dumps({'report':str(out/'VALIDATION.md'),'checks':'passed','packages':audit['package_count']}))
