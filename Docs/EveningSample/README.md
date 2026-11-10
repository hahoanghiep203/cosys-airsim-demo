# Evening thermal sample

Open `Open_Evening_Sample.cmd` in the canonical **Cosys_Airsim** folder, then press **Play**. The sample opens `/Game/CityPark/Maps/Showcase_EveningSample`. Allow startup and thermal prewarming to finish before judging the image. The launcher applies the balanced distance/LOD profile and opens RGB plus thermal preview at 1280 x 720. Local inference must be unloaded first. The launcher refuses a duplicate AirSim editor; close the existing one yourself when appropriate.

## What to look for

The added corner is a small food stall and seating area beside a parking bay. Fifteen placed sample objects include a warm hatchback, a cold SUV, food stall/counter, two tables, four chairs, bench, two bins and two warm lamps. Look for actors prefixed `Sample_` in the Outliner. Visible lighting uses warm local pools against a dark blue evening sky. The vehicles intentionally remain difficult to see in RGB under low light.

There are ten thermal sources: the hatchback's existing seven children (hood, two headlights and four tire-rubber sources), one rectangular counter source and two point sources inside lamp fixtures. The cold SUV has a baseline temperature with no source. Props such as tables, chairs and bins use surface baselines. Decorative water/translucent planes have no added sources. Original `Showcase` and the user's `Showcase_CoordinateCrop` maps are preserved.

| Element | Source setting | Intended effect |
|---|---:|---|
| Hood | 80 C | Local warm engine cover |
| Four tires | 60 C | Rubber only; existing rim exclusion preserved |
| Two headlights | 70 C | Warm lamps, separate visible lights |
| Counter | 90 C | Hot upper counter; lower cart stays near ambient |
| Two park lamps | 55 C | Warm fixture, modest local heating |
| Cold SUV | 16 C baseline | Unpowered comparison vehicle |

These are demonstration presets, not measured operating temperatures. Source temperature is not the resulting surface temperature: heat transfer, time and surface location matter. Evening baselines retain warmer road/paving and cooler vegetation. Visible light does not automatically set thermal temperature. This is a synthetic surface/radiance model, not a calibrated real camera or a full conduction solver.

## Apply it to another object

For a simple unpowered object, set its thermal baseline rather than adding a source. Select the object and use the plugin's existing thermal tags/settings workflow described in `Thermal_Scene_Guide.md`. Use an object-specific baseline for a cold parked vehicle; use scene/category baselines for ordinary road, grass, tree and furniture surfaces. Keep decorative translucent/water surfaces excluded.

For local heat, duplicate the sample Blueprint into your own folder. `BP_SampleHotCounter` and `BP_SampleWarmLamp` live under `/Game/Thermal/EveningSample/Blueprints`. Open the parent Blueprint, select its **LocalHeat** Child Actor Component and inspect its Child Actor Class. The child is a native thermal source Blueprint: `BP_SampleCounterHeat` or `BP_SampleLampHeat`. Change its source temperature, range, shape and contact settings in that child Blueprint's Class Defaults; position/rotate the Child Actor Component to align the affected part. A rectangle faces local +X; the counter uses a downward rotation. Start with a short range and verify the footprint in IR. Add further child sources when one object has several independently warm parts. No mesh split is needed for a local surface field, although targeting a complicated material/part still requires receiver configuration and visual checking.

Edit a **duplicate** source class for independent temperatures. Editing an existing source class changes every instance of that class. The two sample lamps deliberately share one source class. Sample-private Blueprints keep shared car and park assets unchanged.

A visible Point/Spot Light Component is configured independently from the thermal child. Leave cast shadows off for these small demo lights unless the visual improvement justifies the cost. Add a few heat sources near the capture route, not one on every distant prop. Keep source occlusion enabled; test that a wall blocks heating rather than treating IR as see-through vision. Prewarm once through one source: prewarm advances the whole thermal world, so do not call it once per source.

## RGB/IR capture

The sample settings use RPC port **41471**, vehicle **EveningSample**, camera **0**, Scene image type **0**, ThermalIR image type **12**, and matching 1280 x 720 / 65-degree views. The supplied `Scripts/EveningSample/capture_sample.py` briefly freezes simulation, requests both channels and always resumes it. It saves `Saved/EveningSample/sample_rgb.png`, `sample_ir.png` and pose/timestamp metadata in `capture_pair.json`. Paused captures are suitable for static paired samples; this script does not establish 30 paired saved images per second.

Before ThermalGen collection, vary object pose, operating state, lighting and camera position; keep RGB/IR alignment and a consistent display/radiance mapping. Split train/validation by scene or route rather than neighbouring frames. The 8-bit IR PNG is a display image, not a per-pixel temperature ground-truth map. This sample does not yet export radiometric Kelvin arrays or class/instance labels as a dataset bundle. No person/dog/motorcycle meshes were installed; this sample reuses existing licensed project assets.

## Verification

See `VALIDATION.md` and the evidence images beside it for the actual measurements and limitations. The target is a 30 Hz live IR preview; explicit saved-image readback has a separate cost. The balanced profile culls grass at 40 m, bushes at 90 m, trees at 220 m, small props at 80 m and other props at 150 m, using existing LODs earlier. It does not permanently edit original meshes.

Use the dedicated launcher to reproduce the sample settings. Opening the map through another shortcut may use different camera, exposure, render distances or IR settings. `Config/EveningSample/scene.json` sets the initial preview position, aim and world prewarm duration. The one-off builder deliberately refuses to overwrite an existing sample.

Advisory work used the invoked astra-team skill: Antigravity and a local Qwen adviser completed generic design reviews. Local inference was unloaded before Unreal. After the user's routing change, no further native Codex subagents were used. GPT Web and Gemini Web model discovery failed before any prompt was sent; their advice was not fabricated.
