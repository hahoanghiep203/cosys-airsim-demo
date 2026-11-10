# Map cleanup validation

On 2026-11-10 Unreal Engine 5.7 commandlet loaded the three retained maps and inspected the asset registry for hard and soft package referencers to the 13 archived maps. No such referencers were reported. The maps loaded as follows:

- Showcase: 827 editor actors; map check: zero errors and warnings.
- Showcase_NotOptimized: 23,086 editor actors; map check: zero errors, one warning about repaired painted vertex colors. Unreal reports this repair will repeat until the map is resaved.
- ThermalDiversity_05_CombinedEnvironment: 1,001 editor actors; map check: zero errors; the commandlet carried forward the vertex-color warning.

This was a headless, null-renderer editor load, not a visual, Play-in-Editor, camera, thermal, or performance test. No map was saved. Old scene construction and capture scripts, route-demo mission configurations, and historical documentation may reference archived maps and are not active workflows. Restore the associated maps from the external archive before attempting those historical workflows.

## Offscreen Play checks

`Showcase` and `ThermalDiversity_05_CombinedEnvironment` each reached a Play world and ran for at least five seconds in offscreen editor tests (855 and 1,029 actors respectively). Those tests used default AirSim settings, not the launchers' full startup profiles; they did not verify camera images or temperatures.

`Showcase_NotOptimized` created a Play world, but the test did not complete after a 240-second wait, including a retry with `Config/Thermal/settings_scene.json`. AirSim reported completed instance-segmentation annotation but the test did not reach a responsive Play tick. Unreal also reported invalid convex collision geometry on spline-mesh components and no positively rated PlayerStart. The cause of the delay has not been established.

The first Play automation attempt crashed Unreal due to a reentrant map load in the test harness; subsequent tests corrected the harness.
