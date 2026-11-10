# Verified project maintenance — 21 October 2026

Cosys_Airsim is the main environment. Original CityPark, the existing evening thermal scene and the newer route demo are available through its project launchers. Old shortcuts forward to this project. Native project/plugin build succeeds; all 15 thermal and 61 route offline checks pass. Native route import/validation also passes in the migrated demo with four points, canonical relative JSON and Python paths.

## Stutter cause and correction

The old performance snapshot retained 1,822 Unreal component wrappers across editor and Play worlds. UE's Python reference collector recursively examines reflected structs/containers in retained object wrappers, including large foliage instance arrays. The installed engine source confirms this in `PyWrapperObject.cpp` / `FPyWrapperObjectMetaData::AddInstanceReferencedObjects`.

Before the fix, natural GC reference traversal repeatedly took about 1,855–2,254 ms once per minute. A CPU trace isolated the cost to reachability, rather than deletion: 732,770 references, 74,090 objects, zero unreachable objects; gather took 0.2 ms. Serial GC still stalled. The fixed profile stores object paths and plain rollback values only. After dropping the unused wrappers, repeated scans took 13.7–17.7 ms in a deliberately accelerated5-second-GC probe. Normal parallel GC and its 60-second interval were restored; experimental incremental reachability remains off.

Two subsequent 90-second original-map moving-camera runs and a fresh 65-second heated-scene run had zero engine frames over 100 ms. These are bounded observations, not a guarantee against every future hitch. Thermal CPU receiver lookup also now caches the owner/component lookup within each GPU-frame construction while retaining live per-component overrides.

## Actual 720p Play measurements

RTX 5060 Ti (16 GB), i5-14400F, 32 GB RAM; UE5.7.4, D3D12. One hidden/offscreen owned editor, normal RGB Play viewport plus visible GPU IR preview. Both outputs confirmed 1280×720; no duplicate RGB thumbnail. Cameras followed the same repeatable moving sweep. IR Hz is **completed GPU dispatch count divided by wall time**, not the configured target. Engine FPS/p95/max come from the engine CSV profiler; UI callback timing is separately retained in JSON.

| Run | Duration | Engine FPS mean | IR dispatch Hz | Engine p95 | Engine max | Frames >100 ms |
|---|---:|---:|---:|---:|---:|---:|
| Original balanced, run 1 | 90s | 97.1 | 30.00 | 13.0 ms | 52.2 ms | 0 |
| Original baseline | 30s | 78.2 | 29.83 | 16.6 ms | 60.0 ms | 0 |
| Original balanced, run 2 | 90s | 83.1 | 29.91 | 15.8 ms | 57.8 ms | 0 |
| Heated scene | 65s | 46.3 | 29.57 | 36.4 ms | 67.5 ms | 0 |

The heated map is the user's current, denser CoordinateCrop version; it has different scene cost from the original map. IR targets 30 Hz and measured 29.57–30.00 Hz in these runs. Do not interpret this as every view sustaining exactly 30 Hz or as packaged-game/physical-flight/paired-dataset throughput. The shorter baseline run is a limited combined distance/LOD/texture-budget comparison; no universal percentage speedup is claimed. Earlier A/B runs inherited editor culls in their Play baselines and are superseded by the corrected runs above.

The balanced texture budget is 6 GB instead of the 800 MB value observed after scalability in the earlier log. Its actual value is logged and capped to VRAM; it does not reserve all GPU memory. Native GPU IR avoids live CPU image readbacks. Heat simulation, physics, object management and paired recording still require CPU work. Recordings intentionally pause simulation while matching RGB/IR images; that contract is unchanged.

## Heating and image correctness

The user-modified CoordinateCrop map's SHA256 remains `3140cc603d7405faf5f845ee2c8b1266e18bed52c86596657b83514aab14ac6a`. Seven car sources remain: four tire-rubber annular regions, hood and two headlights. Seven nearby evening-lamp sources remain. All four decorative water planes are tagged ignored and have zero thermal child sources. Car and wide IR views were visually inspected; the former decorative road rectangles are absent and tire rims remain dark.

Independent CPU radiance/surface lookup on the corrected opaque/masked inputs agrees with GPU output at car, street and lamp views. Mean differences are0.00189,0.000177 and 0.0000966 of an8-bit display count;95th percentile is zero for all three views; maximum differences10,4,2 counts. This checks numerical parity on shared geometry inputs, not measured real-world thermometry. Geometry exclusion is separately checked by the decorative tags and visual inspection.

## Cleanup and recovery

The audit protected every map, authored thermal/route/developer content, the vehicle library for scene diversity, plugin content and literal runtime path references; it followed hard/soft/searchable/manage registry dependencies synchronously.26 unreachable CityPark packages totaling 64,597,120 bytes were moved out of active Content into `AssetArchive/unused_20261021`. Post-cleanup registry contains 1,271 protected/reachable packages and zero further candidates under that policy. Hashes of all archived files were rechecked.

The archive remains on disk, so this is active-project cleanup rather than permanent space reclamation. Keep it for recovery. No user map was overwritten, no original map was deleted, and the old project remains available. The migrated route-demo map alone was saved to replace its old absolute JSON path with a canonical relative path. Original editor distances and collision rollback passed with zero mismatches; all snapshot entries are plain values.

See [MAIN_PROJECT.md](MAIN_PROJECT.md) for launchers, render-distance/VRAM controls, whole-object/source temperature guidance and asset recovery. `validation_summary.json`, `engine_frame_summary.json` and `asset_quarantine.json` provide compact evidence. Raw CSVs, reports, before-fix CPU trace/export and backups remain in Saved/ProjectMaintenance (the large trace is also in the local visualization folder). No new commit or push was performed.

## Team

Used the explicitly requested [astra-team skill](C:/Users/Admin/.agents/skills/astra-team/SKILL.md). Native adviser traced the implementation; Antigravity gemini-4-argon-medium and local Qwen3-Coder30B supplied generic technical reviews, not proof of project correctness. Local inference completed and unloaded before Unreal opened. A further native escalation could not start because the app reported its agent limit; its unused reservation was released and the root completed profiling/integration. No model ran alongside Unreal.
