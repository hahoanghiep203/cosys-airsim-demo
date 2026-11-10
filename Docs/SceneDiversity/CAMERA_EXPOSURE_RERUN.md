# Night RGB exposure and ThermalGen rerun - 2026-10-23

The combined environment now applies a reversible **RGB camera exposure profile** at Play startup: **ISO 25,600, f/1.4, 1/30 s, +1 EV**, manual exposure with physical camera exposure enabled. Scene lighting and the thermal source presets are retained. This is rendered exposure gain, **not a calibrated high-ISO sensor-noise model**; no additional film grain was added.

Open `CameraExposure/INDEX.html` for all 50 before/after comparisons. Each row shows previous RGB, new RGB, previous ThermalGen, new ThermalGen and new simulated IR.

## Measured result

| Check | Before | After |
|---|---:|---:|
| Severely dark RGB views (>70% grayscale pixels <=8/255) | 40/50 | **0/50** |
| Mean RGB grayscale value across views | 10.95/255 | 27.58/255 |
| Mean fraction of dark pixels | 82.86% | 40.78% |
| Low-global-contrast IR views (standard deviation <5/255) | 24/50 | 25/50 |

The new mean fraction of RGB pixels at or above 250/255 is **0.112%**; the worst view is **0.547%**. These are encoded-image screening statistics, not a measured camera response or physical calibration. Shadows remain in the scene, but the new camera retains more useful structure. No view meets the previous severe-darkness threshold.

All 50 fresh 1280x720 paired captures passed pose, timestamp, clearance and frozen-source checks: 50 distinct positions, 18 orientations, matching positive RGB/IR timestamps and unique image hashes. Export hashes were verified. Before/after vehicle source comparisons covered 95 source entries per view: target-temperature difference **0 K**, enabled-state differences **zero**. Camera positions match the previous batch. Six PIP cameras, each with main/RGB capture components, yielded **600 camera component checks** across the 50-view metadata.

Source settings match, but the native thermal field may continue settling between views. The new IR is not claimed pixel-identical to the earlier capture. Its contrast did not improve through changing RGB ISO; it remains an independent issue.

## Camera selection and persistence

Three fixed views were rendered at ISO 1600, 6400 and 25600. ISO 25600 retained the clearest scene detail without a large clipped-pixel area in those trials. The corrected-aperture comparison is `Saved/SceneDiversity/CameraExposure_20261023/f14_corrected/iso_comparison.jpg`; earlier diagnostic images are retained separately and are not the accepted dataset.

The profile is `Config/SceneDiversity/rgb_camera.json`. `Scripts/SceneDiversity/rgb_camera.py` applies it once through `runtime.py` only in the combined environment. It sets both the CineCamera's current aperture and its post-process f-stop, and uses copied settings with property change notifications disabled. Only main camera and RGB `SceneCaptureComponent` settings are targeted. Geometry, FOV, IR source values and materials are not edited.

Launch the usual `Open_Thermal_CombinedEnvironment.cmd` and start Play to use the new settings. Edit ISO, f-stop, shutter denominator and exposure compensation in the profile, then restart Play. To restore the inherited camera exposure, set `enabled` to `false` and restart Play. No native rebuild or map resave is required. Older captures and the earlier PDF remain records of their original exposure.

## ThermalGen rerun

Used cached ThermalGen-XL/2 on RTX 5060 Ti with the **same M3FD style 7, CFG 1, float32/high matmul precision, original adaptive Dopri5 sampler, 256x256 resize and per-view seeds** as the preceding M3FD run. The checkpoint hash and sampler settings match. RGB was rendered with the new camera before saving; no exposure brightening was applied to old PNGs.

All **50 generated PNGs** decoded successfully, were nonconstant and unique, and matched the recorded output hashes. The original sample control also completed. Batch wall time was **147.3 seconds**, with median measured inference **2.36 seconds per view**. This is offline generation, not an Unreal preview FPS benchmark. Original captures are 720p; generated outputs remain 256x256. Square-generated images are reshaped to 16:9 only in comparison displays.

Visual review of the full contact sheet and representative full comparisons found improved scene structure in some outputs, especially the service truck and brighter building regions. The hatchback/hood heat is still missing or altered, and blurred or invented structure persists. Better RGB visibility therefore **does not establish realistic thermal ground truth**. The model receives RGB/style, not engine state or the simulated temperatures; no calibrated-temperature or training-benefit claim is made.

## Files and safety checks

- Fresh captures: `Saved/SceneDiversity/captures/iso25600_20261023/`.
- Matching-name dataset: `Saved/SceneDiversity/thermalgen_iso25600_20261023/`.
- Generated images, manifests, before/after panels, statistics and validation: `Saved/SceneDiversity/ThermalGenISO_20261023/`.
- Repeatable comparison script: `Scripts/SceneDiversity/compare_rgb_exposure.py`.

Original and fresh capture hashes remained unchanged during inference. Three protected original maps retained their stored SHA256 hashes. Camera/runtime scripts passed Python syntax checks. Only owned test editor PID 19580 was used and closed after Play ended; its exit was verified before loading ThermalGen. Local LLM inference stayed unloaded. No map assets were saved, no paid API was used, and no commit or push was made.
