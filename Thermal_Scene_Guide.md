> **Current guidance:** Start with the [documentation index](Docs/README.md) and [illustrated heat-source tutorial](Docs/Thermal/APPLY_HEAT_SOURCE.md). This reference was written for the archived `Showcase_CoordinateCrop` scene; its scene-specific launcher, map, measurements and screenshots are historical. `Open_Thermal_Scene.cmd` now opens the combined environment using its own settings.

Current main environment: see [project guide](Docs/ProjectMaintenance/MAIN_PROJECT.md) and [measured validation](Docs/ProjectMaintenance/VALIDATION.md).

# Thermal temperatures in Showcase_CoordinateCrop

Project: `D:/F1/UE prj/airsim_test/Cosys_Airsim`

Map: `/Game/CityPark/Maps/Showcase_CoordinateCrop`

There are two controls: **whole-object baseline temperature** and **local heat
sources**. A baseline gives the unheated object its temperature. A source adds
energy to a selected region and can radiate onto nearby mesh surfaces. Sources
warm surfaces gradually; the source setting does not instantly force the
receiving surface to that temperature.

## Open the configured scene

1. Double-click `Open_Thermal_Scene.cmd` in the project folder. This opens the
   map with `Config/Thermal/settings_scene.json`.
2. Press **Play**. Use the custom **ThermalIR** subwindow, image type **12**.
3. The ordinary viewport remains RGB. Visible headlight spotlights are separate
   from the thermal system.

Your global `Documents\AirSim\settings.json` is unchanged. The project launcher
supplies the scene-specific settings. If opening the `.uproject` directly, also
supply `-settings=` with that project settings file. The hidden Scene,
DepthPlanar, Segmentation, and Normals captures need matching resolution/FOV;
the supplied file already sets this up.

RGB and IR camera output is **1280×720**. The IR preview now targets **30 Hz**
and uses one camera pass to gather the actual visible surfaces, depth and normals.
Surface lookup, radiometric conversion, optical blur and display stay on the GPU.
Live IR frames do not need CPU image readbacks. Static heat-surface geometry is
uploaded once; temperatures are uploaded at the thermal simulation cadence.

The normal main viewport and the IR window are shown. The duplicate RGB camera thumbnail is hidden to avoid rendering RGB twice. Press **3** to show it when needed; it adds another camera render.

Heating/cooling, receiver discovery and source occlusion still run on the CPU.
Unreal's editor assets and physics data still use RAM. Explicit API image **12**
requests use a fresh GPU frame on supported hardware, with a readback only to
return the requested image. The normal RGB image API remains available at 720p.

Console controls: **airsim.Thermal.LiveHz 30** restores the IR rate;
**airsim.Thermal.LiveHz 0** pauses IR requests. **airsim.Thermal.GpuPreview 0**
selects the older CPU reference path for debugging, and **airsim.Thermal.GpuPreview 1**
restores GPU rendering. **airsim.Camera.RgbPreviewHz 30** sets the optional RGB
thumbnail rate. The main viewport keeps its normal frame rate.

For a normal game window at 720p, open **Play → Advanced Settings**, set
**New Viewport Resolution** to **1280×720**, and choose
**Play → New Editor Window (PIE)**.
The project launcher now fixes the main Play render output at 1280×720 after Play starts; the editor panel can display it at a different on-screen size.

The launcher uses medium shadows, effects, post-processing, reflections and global
illumination, with a **6 GB texture pool** on this machine's 16 GB GPU. Capture
output stays at native 720p. Heat-source temperatures and material sampling are preserved.

Decorative mirror reflections use 25% resolution, coarser reflected mesh detail
and a 50 m range while Play runs. This avoids another expensive full-scene render.
The normal objects and IR camera retain their own detail. To restore the original
mirror quality, change **airsim.Rendering.PlanarReflectionBudget 1** to **0** in
the launcher before starting the editor. This preset changes runtime copies only.

### Decorative objects and the old black rectangles

CityPark's `SM_WaterPlane` actors are transparent decorative puddle/reflection
layers. The older segmentation camera treated their full quads as opaque objects,
which created dark rectangles on the road. The GPU IR camera uses actual opaque
and masked geometry and respects foliage cutouts. It excludes these decorations
and keeps the temperature of the real road beneath them. No heat sources were
added to the water planes.

To exclude another decorative object from local heat simulation, add the actor
or mesh component tag **ThermalIgnore**. Leave real roads, trees and receiving
surfaces untagged. The new IR input path supports up to **255 distinct temperature/
emissivity groups and heated receiver identities**; this scene uses 31. It falls
back to the CPU path if that limit or hardware support is unavailable. The old
debug path can still show the old segmentation artifacts.

## Change temperatures across the whole scene

1. Stop Play and select **Thermal Scene Settings** in the World Outliner.
2. In Details, expand **Thermal Scene → Temperatures**.
3. Edit the category temperatures. These fields use **Celsius**.
4. Click **Apply Scene Temperatures** in Details, then save the level.
5. Play again to inspect IR.

The starting values are editable demonstration values, not measured weather:

| Objects | Baseline °C | Kelvin | Emissivity |
|---|---:|---:|---:|
| Trees | 20 | 293.15 | 0.97 |
| Bushes and water plants | 19 | 292.15 | 0.97 |
| Grass / landscape | 18 | 291.15 | 0.97 |
| Asphalt / roads | 32 | 305.15 | 0.95 |
| Paved paths / concrete | 28 | 301.15 | 0.95 |
| Soil / rocks | 25 | 298.15 | 0.93 |
| Water | 20 | 293.15 | 0.98 |
| Buildings | 24 | 297.15 | 0.92 |
| Metal props | 24 | 297.15 | 0.75 |
| Wood / benches | 22 | 295.15 | 0.90 |
| Vehicle bodies | 25 | 298.15 | 0.93 |

Categories are inferred from mesh asset names. Per-object overrides below take
priority, so a specially configured object keeps its own temperature when you
apply the scene defaults again.

## Give one simple object its own temperature

For a tree, road tile, rock, wall, cube, or ordinary mesh actor:

1. Stop Play and select the object.
2. In Details, click **Add Component** and search **Thermal Receiver**.
3. Select the new component.
4. Set **Baseline Temperature Kelvin**. For example, `303.15` is **30°C**.
5. Set **Emissivity**, usually `0.97` for vegetation or `0.95` for asphalt.
6. Save the level and Play again.

No source is needed for this whole-object setting, and the mesh/material does
not need editing. If another source heats this object, the affected region can
rise above its baseline and then cool back toward it.

**Conversion:** Kelvin = Celsius + 273.15. The receiver component and source
actors use Kelvin; the scene settings actor uses Celsius.

An alternative is to search **Tags** in the object's Details and add these
**Actor Tags**:

```text
ThermalTempK=303.15
ThermalEmissivity=0.95
```

To override just one mesh component of an actor, put those values in its
**Component Tags**. Priority is: Thermal Receiver component, explicit component
tags, explicit actor tags, automatic scene baseline. If a receiver component
already exists, edit its fields instead of adding competing tags.

## Foliage and landscape

Use the scene settings actor to change all trees, bushes, or grass. Instanced
foliage shares a baseline per mesh component; one value applies to all instances
in that group. A separately placed Static Mesh Actor is the simplest choice
when one plant needs a different individual baseline.

The grass in this map also includes a **Landscape**, which receives one uniform
landscape temperature. You can change it with **Grass Temperature Celsius**, or
override the Landscape actor with `ThermalTempK=...` in Actor Tags. Different
painted landscape material layers are not separate objects, so this setting
does not give grass and soil textures on the same terrain different values.

Local source heating is supported for ordinary static meshes, nearby foliage
instances, and deformed spline meshes. Landscape heightfield heating is not
simulated by the mesh-surface solver; its whole-terrain baseline still works.

## Add a local heat source manually

1. In Content Browser, open `/Game/Thermal/Blueprints`.
2. Drag **BP_ThermalPoint** into the level.
3. Position it near the region to heat. For radiation, place it outside the
   surface so the object's collision does not block the emitter.
4. In Details, set **Temperature Kelvin**, for example `343.15` for **70°C**.
5. Set **Parent Receiver** with the eyedropper to the object you want to heat
   directly, and enable **Heat Parent Surface**.
6. Set **Parent Contact Radius Cm** for the local heated area, for example `100`
   for a 1 m radius. **Parent Conductance** controls how quickly it warms.
7. Set **Range Cm**, for example `300` for radiation within 3 m. **Radius Cm**
   describes the emitter size; **Power Scale** multiplies its contribution.
8. Leave **Occlusion** enabled to block radiation with Visibility collision.
9. Save, Play, and let the simulation warm up. Turning **Enabled** off stops
   energy input; stored surface heat remains and cools gradually.

The explicit Parent Receiver is useful for a separate source actor. When the
source is a child actor of the object, its parent is used automatically.

| Blueprint | Shape / placement |
|---|---|
| BP_ThermalPoint | Emits in all directions. |
| BP_ThermalSpot | Cone along the source's red **+X** axis; set inner/outer angles. |
| BP_ThermalRect | Rectangular emitter facing **+X**; set width and height. |
| BP_ThermalDirectional | Bounded directional beam along **+X**. |
| BP_ThermalCapsule | Extended emitter along the local **Z** axis. |

## Put multiple sources on a reusable object Blueprint

1. Open the object's Blueprint.
2. Add a **Child Actor Component** under its mesh.
3. Set **Child Actor Class** to a thermal source Blueprint.
4. Position and rotate the child over the desired region.
5. Expand **Child Actor Template** to edit its source properties.
6. Add more child sources for other regions, then Compile and Save.

The existing `BP_ThermalHatchback` is an example with a hood source, two front
light sources, and four tire sources. It preserves the original car mesh.
Its source temperatures are 80°C for the hood, 70°C for the lamps, and 60°C for
the tires. Its two visible spotlights are ordinary RGB lights; their 5,500 K
**color temperature** is unrelated to the physical thermal-source temperature.

For a complete tire band, use **Parent Contact Region → Finite Cylinder**.
Local **+X** is the wheel axle. Set the inner radius to exclude the rim, the
outer radius to cover the tire, and the half-length to cover tire width.
`BP_HatchbackTireHeat` is fitted to this Hatchback; adjust its dimensions for
other models. **Parent Material Indices** can limit direct contact to selected
material slots when an object has distinct rubber/metal materials.

## Checking the result

- Use **ThermalIR = 12**. Stock **Infrared = 7** is a different image mode.
- Keep the same **DisplayTempMin / DisplayTempMax** when comparing IR images.
  The supplied scene settings use 280–380 K. Hotter pixels are brighter, with
  brightness also affected by emissivity and distance.
- Whole-object baselines need no CPU triangle data. Local mesh heating in a
  packaged build needs **Allow CPU Access** on receiving mesh assets.
- Source geometry and occlusion refresh in small batches across frames. Make baseline
  edits while stopped and restart Play for a clean comparison.
- This is simplified surface heat transfer. It does not calculate weather,
  airflow, full material conduction, or reflected thermal-ray transport.

The original map/project files and replaced plugin files are preserved under
`Saved/ThermalSetupBackups`. Scene setup and verification reports are under
`Saved/ThermalScene`.

## Evening lamps near the car

The map now uses a dim sunset sky and fixed exposure. Within 30 metres of `SM_Hatchback`, three of nine short park lamps are on (one in every three), and all four tall street lamps are on. These seven fixtures have warm visible lights and local IR heat sources.
Find them in the Outliner folder **Thermal/EveningStreetLights**.

- `BP_EveningParkLampSource` combines a small point light with an IR point source.
- `BP_EveningStreetLampSource` combines a downward spotlight with an IR point source.
- Visible light color: **3,000 K**. Physical heat-source temperature: **333.15 K / 60°C**.
- Heat affects the nearby lamp housing through contact and radiates within **100 cm**.
  The illuminated ground is not automatically assigned the bulb temperature.
- Lights have no dynamic shadows and fade out between roughly **50 and 65 metres**.
  The 720p captures and existing preview rates remain in use.

To add another fixture, drag either Blueprint into the level, position it at the
lamp head, and set **Thermal → Parent Receiver** to that lamp-post actor. Attach
it to the pole with **Keep World Transform**. For the street preset, its spotlight points straight downward, with a 35° inner cone and 50° outer cone. Adjust **VisibleLamp → Intensity / Attenuation Radius** for RGB
lighting and the actor's **Thermal** properties for physical heat separately.

Each fixture also has a small emitter surface with a steady 55°C baseline. Its housing warms dynamically from the 60°C source. The source starts warming its receiver when Play begins. For an already-warm
lamp, call **Prewarm** once at startup; that advances the entire thermal scene
and can delay startup. Source temperatures are adjustable artistic simulation
values, rather than measured specifications of this lamp model.

Selected poles use new material instances under `/Game/Thermal/Materials` for
the warm lens glow. Original CityPark mesh and material assets are preserved.
The map before the evening edit is backed up under `Saved/ThermalEveningBackups`.

For this lamp setup, `Elm1756` and `AmurCork388` use a **ThermalTreeResponse** component with **Sample Spacing Cm = 32** to keep tree heat simulation inexpensive. Car and lamp sampling remain detailed. To change these two trees' whole-object temperature, edit **Baseline Temperature Kelvin** on that component, which takes precedence over actor tags.
