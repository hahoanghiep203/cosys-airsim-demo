> Historical fixed-view report from the older AirSim_test project. Current Cosys launchers, GC fix and 720p Play measurements are documented in [MAIN_PROJECT.md](../ProjectMaintenance/MAIN_PROJECT.md) and [VALIDATION.md](../ProjectMaintenance/VALIDATION.md). Statements below about external Cosys being untouched and the old launcher behavior describe the earlier task.

# Original map performance and diversity

The original `/Game/CityPark/Maps/Showcase` map remains intact. A session-only profile applies reduced scenery draw ranges and earlier existing static-mesh LODs. No source meshes are regenerated, no actors are deleted and no map is automatically saved.

Open `Open_OriginalMap_Balanced.cmd` from the project folder to view the original map with the profile. Close another editor for this project first. The launcher refuses to start while a local llama-server/Prism inference process is running. It does not start a mission or change AirSim settings. The profile is an editor Python tool, not a packaged-game runtime feature.

Settings are in `Config/ScenePerformance/balanced.json`:

| Scenery | Maximum candidate draw range |
|---|---:|
| Grass, flowers and dry leaves | 40 m |
| Bushes | 90 m |
| Small props | 80 m |
| Other props | 150 m |
| Trees | 220 m |
| Terrain, roads and large structures | Existing range retained |

Existing shorter ranges remain shorter. Most meshes already have 2–8 LODs: 452 of the original 458 unique meshes have more than one. The profile sets `r.StaticMeshLODDistanceScale` to 1.5, making existing discrete LODs transition earlier; it does not create missing LODs or change Nanite quality. Ground and major structure draw ranges stay unchanged, although the global LOD scale also affects their existing discrete LODs.

Vehicles from VehicleVarietyPack, non-CityPark meshes, and components/actors tagged `ScenePerformanceKeep` or `RouteCaptureTarget` are exempt from scenery distance changes. Thermal-source tags beginning with `ThermalSource` are also exempt. These exclusions protect draw distance, not the global LOD bias. New target classes should receive an explicit keep tag. Instanced foliage uses its instance start/end distances; its whole component is not culled as a single cluster. Collision settings and thermal simulation are not disabled. Large instanced clusters retain per-instance culling.

These are 3D camera-to-object ranges: at 80 m altitude a 40 m grass range intentionally removes ground grass. Increase ranges for high-altitude or long-standoff capture. Range culling can visibly remove scenery; it does not preserve an identical image. Foliage fade only appears smoothly where the material supports per-instance fade. Before production capture, validate both RGB and ThermalIR at the actual mission altitude and range. No RGB/IR production parity or flight FPS test is claimed here.

The baseline can be restored in the same editor Python scope with `scene_apply('baseline')`; closing without saving also discards the session changes. Do not save the original map to make the temporary profile permanent. In another editor scope, load `Scripts/ScenePerformance/profile.py` and call `scene_apply('balanced')`, then `scene_apply('baseline')` in that same scope so its original-value snapshot is retained. A Play world can be addressed explicitly with the second argument `True`. Reapply after adding new scenery components.

## Actual validation

The original map inventory has 867 static mesh components, 458 unique meshes and 2,718,359 mesh instances. About 560 scenery components qualify for the profile. A temporary measurement probe added one component/instance and was subsequently removed.

Two baseline and two candidate runs each took 30 timed samples after 5 warmup samples. At a fixed aerial viewpoint, 960x540 SceneCapture rendering plus synchronous one-pixel GPU readback averaged **12.094 ms baseline versus 10.941 ms balanced**, a **9.53% reduction**. PNG encoding was excluded. This is one fixed-view acquisition-cost experiment; it is not packaged-game FPS, GPU-only timing, a route flight, or simultaneous RGB+IR throughput. Tail latency varied and is not proven improved. Idle editor ticks remained near 120 Hz and do not demonstrate an FPS gain.

Before/after views were inspected. They show the expected reduction in distant trees and small ground detail while roads and terrain remain. Wind/temporal state was not frozen, so these are visual review images, not pixel-identical goldens. A full rollback checked 868 live components with zero distance, instance-range or collision mismatches and restored the LOD scale to 1.0. The original map SHA256 was unchanged: `976f8cb8ad255e826b08b44762af283a1e2752e443be2c6569378e48f1cf4b95`. Helper syntax checks passed.

Raw evidence: `Saved/ScenePerformance/validation.json`, `inventory_balanced.json`, `restoration.json`, `render_*.json`, and `comparison.png`. No external Cosys_Airsim assets were modified.

## Suggested object diversity, in order

| Addition using available assets | Useful variations | Cost control / IR consideration |
|---|---|---|
| Hatchback, SUV, pickup, sports car, box truck | Color, heading, parking position, partial occlusion; engine hot/cold states | Begin with 3–5 vehicles near a route. Reuse meshes/materials. Configure actual thermal sources; RGB color is not a temperature model. |
| Benches and trash cans | Wood/metal appearance, clusters, orientation, clutter around targets | Existing `SM_Bench01/02/03` and `SM_TrashCan01/02`. Instance repeated static clutter; simple collision. |
| Rocks, shrubs and selected trees | Size, spacing and occlusion rather than large density increases | Reuse existing flora/ground assets. Avoid adding more dense grass before profiling; it already dominates instance count. |
| Roadside context | Existing lamp posts, signs and sparse barriers near junctions | Prefer unlit props and shared materials. Emissive light appearance does not automatically heat a ThermalIR target. |
| Surface variation | Existing asphalt/ground materials, restrained dirt/wear decals | Change roughness/color and supported thermal baselines separately. Decals still have rendering cost and do not automatically affect custom ThermalIR. |
| Controlled capture scenarios | Dry/wet appearance, light direction, time of day, parked/active vehicle states | Record seeds, positions, asset IDs and thermal parameters. Do not assume fog, lighting or material parameters propagate into this custom IR pipeline. |

Start with several layouts containing 3–5 vehicle targets plus 10–20 small props around the route, rather than filling the entire map. Keep takeoff, route and stopping clearances intact. Distribute hot and ambient objects across backgrounds to avoid learning one vehicle/background association. Benchmark a real representative RGB+IR mission before increasing counts.

## Team and sources

Antigravity `gemini-4-argon-medium` provided a read-only optimization review. Local `qwen_coder30` supplied a one-shot advisory proposal while Unreal was closed, and its process/model fully unloaded before Unreal started. Local advice mixed inconsistent distance values and confused occlusion with distance culling; those suggestions were not applied. Antigravity assumed an IR stencil/material implementation and suggested generic fog/decal thermal effects; those claims were not accepted as facts about this custom type-12 renderer. The root validated the actual map, engine APIs and reversible changes.

Epic documents that `r.ViewDistanceScale` multiplies existing draw distances; objects with unlimited draw distance remain unlimited. Setting a camera far clip is therefore not the general scenery optimization used here. [Scalability reference](https://dev.epicgames.com/documentation/en-us/unreal-engine/scalability-reference-for-unreal-engine?application_version=5.7). Epic also recommends retaining large structures when selecting distance-culling ranges. [Cull distance volumes](https://dev.epicgames.com/documentation/en-us/unreal-engine/cull-distance-volumes-in-unreal-engine?application_version=5.7). The LOD scale direction was verified against the installed UE5.7 `SceneVisibility.cpp` console-variable definition.

A fresh isolated launcher test also passed: it loaded the original map and automatically applied all 560 candidate scenery components with LOD scale 1.5. The owned editor was restored to baseline and closed afterward. Launching the profile does not select a different AirSim settings file or start Play. Benchmark helpers create fresh timestamped evidence folders on reruns to avoid reading stale measurements.

## Save-permission issue (2026-10-21)
The interactive Admin editor reported Windows Error5 replacing original Showcase.umap. It is owned by CodexSandboxOffline; Users has Write/ReadAndExecute but lacks Delete, needed by Unreal temporary-file replacement. Map is not read-only, only one editor was running, and disk space was sufficient. This is a filesystem ACL issue, not demonstrated map corruption. Direct ACL repair from this session was denied; no permissions or map bytes were changed.

`Repair_Showcase_SavePermissions.cmd` requests Windows administrator approval, grants only DESKTOP-ASRBKR8\Admin Modify on this one map, preserves the prior ACL and writes Saved/ScenePerformance/permission_repair_result.json. It neither replaces the map nor closes Unreal. After successful repair, Retry saving in the existing editor. If needed, Cancel the save dialog and use Save Current Level As with a new name to preserve in-memory edits. No recursive permission changes or ownership takeover are used.
