# Corrected GPU ThermalIR camera — 13 October 2026

The installed IR camera renders the actual visible opaque/masked surfaces at
1280×720. Transparent decorative water planes no longer appear as solid thermal
rectangles. The existing hood, four tire-rubber regions, headlights and seven
nearby evening lamp heat sources remain in place. Decorative water planes have
zero heat-source children and are excluded from receiving heat.

The preview performs surface sampling, spectral radiance conversion, blur and
display on the GPU. Geometry is uploaded once and temperature values follow the
slower persistent CPU heat solver. Explicit API image12 requests render a fresh
GPU frame and read back only that requested output. CPU heating/cooling, source
occlusion and Unreal editor assets remain in RAM.

The optimized camera combines three former input captures into one, retains
cached mesh drawing instead of Unreal's expensive unlit rich-view path, and
reuses the display material instead of rebinding it every frame. Surface IDs
use the default depth-tested stencil rule, so background roads cannot overwrite
the ID of a heated car or lamp in front.

Static annotation components no longer tick empty update functions. Baseline
lookup caches the receiver component once per owner, avoiding repeated searches
through thousands of road spline components. Unchanged baseline refreshes reuse
the existing IDs and GPU profiles; rebuilding them every second caused repeated
long frames. Decorative planar reflections use 25% resolution, LOD distance
factor 4 and a 50 m range during Play. Original map assets are unchanged.

Reading camera information no longer enables an unseen continuous RGB capture.
It computes the projection from the allocated inactive target. Explicit IR API
calls therefore leave a hidden RGB thumbnail inactive. RGB API images still
render correctly on demand. Destroyed cameras return no capture resource rather
than indexing their cleared capture arrays.

The CPU heat solver computes each source's radiation power once per update and
uses multiplication for its integer powers. The physical integration formula
and sampling density are unchanged. The IR geometry pass skips translucent color
rendering because its depth/normal inputs contain opaque and masked surfaces.

## Measured result

- Configuration: native **1280×720 main viewport render target** + 1280×720 IR, duplicate RGB thumbnail hidden.
- Duration: 60.0 s. Main viewport: **44.7 FPS**.
- Actual IR dispatch cadence: **29.93 Hz**.
- Frame median: 21.2 ms; p95: 39.3 ms; longest: 59.0 ms.
- Frames >100 ms: 0; >500 ms: 0.
- Process CPU: 45.5% averaged across 16 logical cores.
- Working RAM: 13.26 GiB; private memory: 15.88 GiB.
- GPU utilization: 32.1%; total observed VRAM: 2.66 GiB.
- Thermal GPU buffers/output counter: 52.0 MiB; scene/capture resources are additional.

The wider street view measured 23.26 Hz IR and 23.3 main FPS over 60.0 seconds, with 0 frames above 100 ms.

The final test uses Multirotor mode, native 720p rendering and the close-car view.
Overall CPU use remains comparable to or higher than the slower 10 Hz baseline,
and working RAM remains around 13 GiB. The offload removes live pixel calculation/
readbacks and supports a much faster IR preview. Heat physics, asset data and
CPU copies of thermal geometry remain.

The earlier CPU10Hz/RGB30 ComputerVision baseline measured 36.3 main FPS, 40.1% process CPU,
13.1 GiB working RAM and 3.55 GiB total VRAM. Earlier GPU previews with three
separate inputs ran at only about 11Hz. These are configuration-specific editor
measurements, not guarantees for all locations, camera motion or fullscreen
presentation. The main render target was fixed to 1280×720 for this test and
displayed in an editor panel. A separate game window's presentation overhead
can differ. Scene location and additional previews also change performance.

## Correctness and limits

Car, wide-road and street-lamp GPU images differ from an independent CPU surface/
radiance calculation by 0.83 grayscale levels
on average or less. All 15 thermal regression tests passed (0 failed), including
decorative exclusion, material masks, tire annular contact, persistent GPU heat,
occlusion, cooling and fixed radiometric display. Four decorative planes are
ignored and have no source children. Runtime stencil values are restored when Play ends.

The surface solver is simplified: no full volumetric weather/airflow/conduction
or reflected LWIR ray transport. The GPU input pass supports 255 grouped baseline
profiles/heated receiver identities; current scene: 31. Unsupported hardware or
exceeding the limit uses the older CPU path. Global RGB illumination does not
automatically assign a bulb temperature to every illuminated surface.

Evidence: packed720_final_performance.json, packed720_final_resources.json,
packed_image_parity.json, packed_scene_checks.json, packed_rectangle_pixels.json,
packed_car_gpu.png, packed_area_gpu.png, packed_lamp_gpu.png. Test results:
Evidence/thermal_regression_summary.json (full local test report: Saved/ThermalReview/FinalAutomation/index.json). Plugin rollback:
Saved/ThermalGpuBackups/20261012_225558.

The JSON measurements and independent GPU/CPU images named above are archived
in this repository under `Docs/Thermal/Evidence`. Local editor caches, binaries,
logs and rollback snapshots remain excluded from Git.
