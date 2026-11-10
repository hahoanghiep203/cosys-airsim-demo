> **Map cleanup (2026-11-10):** The active project retains Showcase, Showcase_NotOptimized, and ThermalDiversity_05_CombinedEnvironment. Other maps were archived outside the project. References below to removed maps and launchers are historical. Use `Open_Cosys_Airsim.cmd`, `Open_Showcase_NotOptimized.cmd`, or `Open_Thermal_CombinedEnvironment.cmd`.

# Main Unreal project

Use **D:/F1/UE prj/airsim_test/Cosys_Airsim/Cosys_Airsim.uproject**. The older `AirSim_test` directory is retained as recovery/history; its original-map and route-demo shortcuts now forward here. Its `Repair_Showcase_SavePermissions.cmd` repairs only the **old** map. The canonical original map already has Admin Full Control; do not run the old repair for this project.

## Open a scene

- `Open_Cosys_Airsim.cmd`: original CityPark Showcase, balanced render range/LOD, RGB and IR preview.
- `Open_Thermal_Scene.cmd`: existing evening CoordinateCrop scene with tire-rubber, hood, headlight and nearby street-lamp heating.
- `Open_RouteCaptureDemo.cmd`: route-capture demo and its own recording settings.
- Pass `-Profile baseline` to the main launcher for original scenery distances/LOD and the engine's texture budget. Close the existing editor before launching another.

The launchers refuse to start a second AirSim editor or run alongside a local inference server. Both camera outputs target 1280×720; the main Play viewport is explicitly fixed to that size after Play starts. IR requests 30 Hz; achieved dispatch timing depends on the view and machine load. Opening the `.uproject` directly selects the original map but does not run the launcher's performance script.

## Performance controls

Edit `Config/ScenePerformance/balanced.json` before launching. Current distances are grass40 m, bushes90 m, trees220 m, small props80 m, other props150 m. Existing shorter ranges are preserved. Existing source LODs are used earlier at scale1.5; no mesh LODs were regenerated. Roads, terrain, large structures, vehicles and keep-tagged targets retain their original draw distances. **The global LOD scale still affects protected targets.** Distances are three dimensional; test visibility at the intended flight altitude.

The balanced profile budgets 6144 MB for texture streaming on this machine's 16 GB GPU, capped to the available VRAM budget. This is a texture budget, not a reservation for the entire GPU. Other render targets, geometry and desktop applications also use VRAM. The custom IR preview remains on the GPU; explicit image downloads and paired recording still have CPU/readback costs. CPU simulation cannot generally be transferred to VRAM by changing a setting.

Settings apply to both the editor and its Play world. In the Python console, `scene_apply('baseline')` restores the editor's original distances/LOD; `scene_apply('baseline', True)` restores Play. The Play baseline is seeded from the original editor snapshot, rather than inheriting its reduced ranges. **Do not save a map while temporary performance overrides are active**; restore first or close the session without saving. Collision is unchanged.

The recurring GC stall was caused by keeping Python wrappers for foliage components in the performance rollback dictionary. Unreal's Python reference collector walks reflected containers in those wrappers. The fixed snapshot contains paths and plain values only, so it can restore the same settings without retaining the large component wrappers. Garbage collection remains enabled with its normal interval; experimental incremental reachability is not enabled.

Route recording deliberately pauses the simulation to obtain a matched RGB/IR pair. That data-capture pause is separate from live-preview stutter and remains in place.

## Asset organization and recovery

The existing CityPark, VehicleVarietyPack, Thermal and RouteCapture folders remain separate. Asset paths were retained to avoid breaking Blueprint and native references. Every map, developer content, future vehicle library and thermal/route/plugin library was protected during the audit, along with native/config/Python path references and all registry dependency types.

26 unreachable CityPark packages (64,597,120 bytes, about61.6 MiB) were removed from active `Content` and moved to `AssetArchive/unused_20261021`. This is reversible quarantine, not permanent disk reclamation: the archive still occupies disk. Removing unloaded assets is not an FPS optimization. The manifest `Docs/ProjectMaintenance/asset_quarantine.json` records every path, size and SHA256.

To restore, close Unreal and run `.venv/Scripts/python.exe Scripts/ScenePerformance/restore_unused_assets.py` from this project. It verifies hashes and refuses to overwrite changed assets. Keep the local archive until you are satisfied; Git also retains previously committed assets. Neither user-authored map changes nor the old project were deleted.

The native project module and newer route-capture plugin are now installed here. The independent `.venv` uses CPython3.12; installed versions are recorded in `Config/RouteCapture/requirements-win-py312.txt`. Local models must be unloaded before using Unreal. Backups of overwritten scripts/configuration and the pre-existing modified CoordinateCrop map are in `Saved/ProjectMaintenance/before_*` and `config_before_finalization`.

## Adding whole-object temperature or heat sources

See `Thermal_Scene_Guide.md` for the existing Blueprint properties and units. Use receiver/whole-object temperature settings for tree, grass, road and other baseline surfaces. Use `BP_ThermalSource` child actors for localized heating, choose the appropriate source shape, and align its contact region to the hood or tire rubber. Do not put sources on decorative water planes; they remain excluded from thermal heating. Visible lights and IR heat are configured independently.

Keep new scene diversity sparse: start with3–5 vehicles and10–20 nearby benches, bins, rocks or barriers using existing libraries. Profile a representative RGB/IR route before adding dense foliage. Check visibility and thermal labels at the actual recording distance; the balanced profile does not establish dataset equivalence.

Validation measurements and remaining limits are in `VALIDATION.md`.
