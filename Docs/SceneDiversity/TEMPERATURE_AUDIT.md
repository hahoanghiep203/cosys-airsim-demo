The combined environment now has an explicit, audited temperature policy in `Scripts/SceneDiversity/temperature_policy.py`. This corrects missing ivy/spline baselines, the road-barrier/asphalt name collision, pickup classification, and inherited furniture temperatures from a previous lighting preset. It also classifies runtime camera helpers separately from scene objects. Explicit user `ThermalTempK` / `ThermalEmissivity` overrides retain priority.

The checks verify **configuration coverage, actual sampled hot surfaces and digital rendering consistency**. They do not establish measured real-world temperatures for every instance. Thermal cameras measure surface radiation; emissivity, reflection, distance and environmental conditions affect the result. See [FLIR surface measurement guidance](https://docs.flir.com/T810603/en-US/latest/s07.html) and [FLIR emissivity/reflection explanation](https://www.flir.com/en-asia/discover/professional-tools/how-does-emissivity-affect-thermal-imaging/).

Current blue-hour assumptions:

| Object/state | Assigned baseline or target | Meaning |
|---|---:|---|
| Vegetation, dry leaves, furniture, buildings, inactive equipment and cold parked vehicles | 16 °C baseline | Controlled ambient assumption; all instances of a component share its baseline |
| Asphalt roads | 19 °C baseline | Assumed residual daytime heat |
| Concrete paving | 17.5 °C baseline | Assumed smaller residual daytime heat |
| Added inactive tank, storage container and solar panel | 16 °C surface preset | Unpowered objects |
| Added warm process tank | 35 °C surface preset | Hypothetical warm casing, deliberately paired with the identical cold model |
| Warm operating vehicle tires | 35 °C source target | Rubber-only contact region; actual solved surface can be cooler |
| Warm vehicle hood / headlights | 80 / 60 °C source targets | Localized heating; source target is not the measured surface temperature |
| Cooling vehicles | Temperature curves toward ambient | Recently operated state, not a fixed core/engine temperature |
| Café / market counter | 90 / 110 °C source targets | Heated local region, not the entire stall |
| Local lamp housings | 40–65 °C source targets | Local fixture presets; visible-light color is independent |
| Decorative water/reflection planes and editor camera helpers | Excluded | No heat sources or independent thermal surface |

These are experimental presets, not universal temperatures of those object classes. Weather, wind, elapsed time after sunset, surface wetness, material finish and operating load are not calibrated from real measurements. A uniform mixed-material mesh uses an approximate effective emissivity. Reflections and atmosphere use the existing synthetic camera model; a numeric CPU/GPU match does not validate that model against a real camera. The saved PNGs are display-mapped 8-bit images, not radiometric Kelvin maps.

The complete audit covers 936 editor mesh components and 1,022 components in Play, including approximately 2.71 million mesh instances. Construction-generated ivy had 109 components without baseline tags; two other missing-tag components were editor/reflection helpers. Six road-block components (126 instances) had been classified as road. Three pickup components now have an explicit vehicle category. All scene meshes now have finite explicit baseline/emissivity settings, with no unresolved generic material category after runtime helpers are classified. Seven decorative water-plane components remain ignored, with zero attached sources.

All 13 configured vehicles were checked again: tire-source attachment error was zero; rims and cold parked tire samples remained within floating-point precision of 16 °C. Source mounts were corrected for the SUV hood and the cab-over truck's front engine cover/headlights. Thirty-nine hood/engine-cover/headlight probes use exterior triangles from the original exported render meshes. Simple collision hulls differed from the SUV's rendered hood by about 8 cm and could return an unrelated road sample, so collision-hull queries are not accepted as hot-part ground truth. The final independent CPU/GPU comparison at 1280×720 had mean absolute error **0.00073 / 255**, 95th percentile zero and maximum difference 9 / 255. It passed the configured mean/percentile tolerances, with small localized differences; it was not a pixel-identical match. The earlier tank-view comparison was pixel-identical. Both comparisons use the same geometry input and independently evaluate thermal arithmetic.

Four additional objects use three mesh types from [Kenney City Kit Industrial](https://kenney.nl/assets/city-kit-industrial): two process tanks (warm and cold), one storage container and one solar panel. The creator page and included `License.txt` identify CC0. The downloaded archive, original files, license and SHA256 provenance are retained under `SourceAssets/ThirdParty/KenneyCityIndustrial/`. Imported mesh assets are isolated under `/Game/Thermal/SceneDiversity/ThirdParty/KenneyIndustrial`. The three meshes have 282, 453 and 344 imported vertices respectively. They are stylized examples and should not be described as photorealistic assets.

The four props use whole-object surface presets. They add **zero simulated emitters**: nearby heat transfer from the warm tank is not simulated. Existing car and lamp sources remain enabled according to their operating state; no decorative planes receive heat. The combined map's previous slow live preview remains a limitation. No 30 Hz or performance improvement is claimed by this audit.

The creator-hosted [Quaternius posed-human pack](https://quaternius.com/packs/backgroundposedhumans.html) was researched, but its public Drive download returned “Quota exceeded.” No human asset was imported. No purchase or paid service was used.

Use the refreshed gallery at `TemperatureAudit/INDEX.html` and dataset `Saved/SceneDiversity/thermalgen_audited50/`. Original captures and the previous gallery remain preserved. `Capture_Thermal_Angles.cmd` uses the updated viewpoints and makes one new independent-view batch per invocation. To edit the four prop presets, change their actor's `ThermalTempK` and `ThermalEmissivity` tags in Unreal and save the map; `Config/SceneDiversity/imported_props.json` records their initial settings. Edit scene ambient/residual heat in the combined scene entry in `Config/SceneDiversity/scenes.json`. The policy runs after Blueprint construction at Play startup, preserving explicit object overrides.

Machine-readable evidence is in `Saved/SceneDiversity/TemperatureAudit/` and `Docs/SceneDiversity/TemperatureAudit/VALIDATION.json`. See the component CSV for effective settings, tag precedence, materials, categories and instance counts. Previously captured images remain tied to their original source state; use the refreshed dataset for the corrected policy.
