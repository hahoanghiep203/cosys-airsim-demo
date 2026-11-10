> **Map cleanup (2026-11-10):** Only the combined environment remains in the active project. References below to individual maps and their launchers are historical.

# Thermal capture environments

Latest: [whole-environment temperature audit and added props](TEMPERATURE_AUDIT.md), with a [refreshed verified gallery](TemperatureAudit/INDEX.html). Earlier collections below remain preserved.

The current sample combines the four layouts into **one environment** and captures **independent still viewpoints**. Open `Open_Thermal_CombinedEnvironment.cmd`, then run `Capture_Thermal_Angles.cmd` for one batch. See [combined environment guide](COMBINED_ENVIRONMENT.md) and [50-view gallery](Combined/INDEX.html).

The four separate maps and continuous-route examples below are preserved as earlier variants.

The canonical environment is **Cosys_Airsim**. Each scene is a separate CityPark map with its own added arrangement and lighting; the original Showcase, CoordinateCrop and EveningSample maps are protected. Open one of the four shortcuts, then press Play. Use only one editor at a time and keep local inference unloaded.

| Shortcut | Setting | Objects and heat states | Capture allocation |
|---|---|---|---:|
| Open_Thermal_DuskCafe.cmd | Warm sunset / dusk café | Moving hatchback, cold SUV, cooling pickup, added seating and stall | 13 pairs |
| Open_Thermal_BlueHourService.cmd | Cool blue hour / service area | Moving box truck, cold pickup, cooling sports car, barriers and traffic barrels | 13 pairs |
| Open_Thermal_NightMarket.cmd | Dark warm-lit market | Moving pickup, cold hatchback, cooling SUV, additional stalls/tables/furniture | 12 pairs |
| Open_Thermal_MoonlitParking.cmd | Dim cool moonlight / parking | Moving sports car, cold box truck/SUV, cooling hatchback, benches/fences/props | 12 pairs |

All five installed vehicle meshes have reusable thermal Blueprints in `/Game/Thermal/SceneDiversity`: hatchback, SUV, pickup, sports car and box truck. The intact geometry remains intact. Per-model tire centers and rubber annuli come from connected actual mesh geometry. Cars have four tire sources; the truck has six, including its dual rear tires. Hood/front-panel and headlight sources are model-specific child actors. Colored visible light and thermal temperature remain independent.

## Tire correction and movement

The older showcase preset kept tires at 60 C continuously. These scenes use operating states: **parked** sources are disabled at ambient; **driving** tires gradually approach a 35 C demonstration target; **cooling** cars retain moderate residual warmth and cool toward scene ambient. Hood/headlight heating follows operating state. Parked headlights are off. Temperatures are demonstration assumptions, not measured values or a calibrated tire dynamics model.

The existing thermal solver already samples receiver coordinates relative to current actor transforms. New regression coverage tests translation, rotation, an excluded rim bore, GPU transform matrices and residual cooling. Runtime vehicle motion is kinematic along the configured road segment, with child sources attached. Vehicle wheels are part of the original static mesh, so the visual tire geometry does not independently spin; this is not a wheel/suspension physics simulation.

## Edit or follow a route

Select `Diversity_Route_Camera` or `Diversity_Route_<vehicle>` in the Outliner to see the editor-only spline and numbered points. These are guides to the configured capture/driving segments; they do not appear in sensor frames and carry no thermal sources. Edit `Config/SceneDiversity/scenes.json` to change the authoritative scripted routes, operating states, lamp color/intensity and heat presets, then reopen the scene. Sun/sky settings are saved per map; edit the Light Source, SkyLight and sky sphere in Unreal to change that baked scene setup. Moving the guide points alone does not change that scripted configuration. The existing route plugin can be used separately for physical drone flight; the supplied diversity capture uses controlled camera poses along a route rather than claiming flight dynamics.

The initial view is elevated to show the street, warm café area and cold controls. The car moves while Play runs. Capturing briefly suspends scripted movement and simulation for each registered RGB/IR pair, then resumes between pairs. The camera progresses along the configured route; metadata verifies actual camera and car displacement rather than merely requested positions.

## Capture and outputs

With the selected map open, run the project's Python environment against `Scripts/SceneDiversity/capture_routes.py --scene <id>`. IDs are `01_dusk_cafe`, `02_bluehour_service`, `03_night_market`, `04_moonlit_parking`. The script uses RPC41471, vehicleEveningSample, camera0 and Scene0/ThermalIR12 at1280x720. It refuses an occupied output folder; use a fresh `--output` folder for another run.

Default allocations total **50 pairs / 100 images**, plus per-pair pose/timestamp/vehicle/source metadata. Files are under `Saved/SceneDiversity/captures/<id>`. `Scripts/SceneDiversity/audit_captures.py` checks all four manifests, dimensions, frozen pairing, parked/driving source states, unique IR images, actual displacement and protected-map hashes. Only a successful live audit proves collection finished; a valid script or map build does not.

IR PNGs are 8-bit display images, not radiometric Kelvin ground truth. No class/instance mask bundle or ThermalGen model training is performed here. Keep train/validation splits separated by route/scene and review registration after camera changes. Captured-pair disk throughput is distinct from the live-preview update rate.

## Reuse heat on another asset

Duplicate a model Blueprint and its source presets before independent changes. Align the `Tire_*` child components to the wheel centers, keep the finite-cylinder axis along the axle, and set inner radius outside the rim and outer radius over rubber. The model-specific source class and child template both matter; examine IR and surface probes after changing either. Keep the parent mesh and child components movable when the object moves. Do not heat the entire wheel or use a bounding-box proxy.

Ordinary trees, grass, road and cold props use scene/category baselines, without emitters. Added water or translucent decorative planes remain excluded. A local heat source is for genuinely warm parts; a visible lamp also needs an independent light component. Prewarming is performed once per world, not once per source.

Actual live validation, captures and performance belong in the generated report; implementation/offline checks alone are not a claim that all scenes have been verified.

The accepted capture preset uses a controlled 95 cd for the two fixtures in every scene; color temperature, ambient sun/sky and thermal operating states provide the lighting/heat diversity. Dataset cameras remove the default RGB distortion blendables so their projection matches the geometry-based IR view. Runtime component changes avoid editor reconstruction notifications.

Open `Docs/SceneDiversity/INDEX.html` for the four-scene gallery and `route_preview.mp4` for saved-sample playback. The ready-to-use paired layout is `Saved/SceneDiversity/thermalgen50/{rgb,ir,metadata}` with matching image basenames and `pairs.csv` (50 pairs total). Original accepted captures and manifests remain under `Saved/SceneDiversity/captures`. See `VALIDATION.md` for actual frame timing and the remaining preview-rate limitation.
