# Mixed route showcase

One mission combines stopped photographs with photographs acquired during flight. A, C and D stop, settle, save one RGB/ThermalIR pair and hold for 1.5 seconds. B is a pass-through marker. Each of the three connecting legs travels at 1.5 m/s and requests an RGB/ThermalIR pair every 1,000 ms of unpaused simulation time.

Mission: `Config/RouteCapture/mixed_showcase.json`.
Map: `/Game/RouteCapture/Maps/MixedCaptureShowcase`.

The station camera keeps its position and angle fixed, with route markers visible. Route markers are excluded from drone photographs and the live drone view. The drone video uses an independent Unreal renderer following the actual configured camera 0 pose and lens; its frames are not the saved sensor photographs. The third video displays the original saved RGB and ThermalIR photographs beside the fixed station view, aligned by acquisition time.

ThermalIR is image type 12. Its PNG is a display signal, not a calibrated temperature measurement. The live drone renderer exports linear RGB; the video applies the standard linear RGB to sRGB display conversion. Original saved photographs remain unchanged.

The recordings share the same native simulation timeline. Acquisition freezes do not add repeated simulated time. Warmup and initial ground footage are trimmed consistently from all three videos.

## Reproduce

Run the project-local `Scripts/RouteCaptureDemo/launch_demo_editor.ps1`, then:

```powershell
.\.venv\Scripts\python.exe Scripts/RouteCaptureDemo/run_example.py mixed_showcase --tag unique_name --record-drone
.\.venv\Scripts\python.exe Scripts/RouteCaptureDemo/encode_mixed_showcase.py --result Saved/RouteCaptureReview/mixed_showcase_unique_name_result.json --drone-folder Saved/RouteCaptureReview/DroneView/mixed_showcase_unique_name --output Saved/RouteCaptureReview/MixedShowcase/unique_name --trim-warmup
```

Use a fresh tag and output folder for each recording to preserve evidence. The encoder checks successful route completion, collisions, original capture hashes, both capture modes, fixed station transform and the live camera pose before producing videos.

## Measured mixed flight

The recorded mission completed all four markers with zero new collisions, 29 accepted RGB/ThermalIR pairs (3 stopped and 26 in flight), no skipped triggers and no rejected pairs. All 26 eligible travel deadlines produced a pair. Simulation flight duration was 57.1845 seconds; wall duration was 65.11 seconds. The videos omit warmup and use a common 46.25349-second simulation interval.

The observer position and angle had zero measured change. The live drone view maximum camera position difference was below 1e-12 cm, angle difference 0.000106 degrees and FOV difference zero. Node position errors were 0.164–0.167 m. The largest cross-track error was 1.023 m at the pass-through corner. The configured route-completion behavior is hover; this run does not claim a landing test.

Raw result: `Saved/RouteCaptureReview/mixed_showcase_three_views_final_result.json`.
Raw run: `Saved/RouteCaptureReview/Runs/mixed_capture_showcase_20261020T191603_F342F36546DAE71F665A2085E951FC45`.

## Video outputs

The final exports are in `Saved/RouteCaptureReview/MixedShowcase/three_views_verified`:

- `01_fixed_observer.mp4`: fixed station camera, 960 x 540.
- `02_live_drone_view.mp4`: independent live camera-0 view, 640 x 480.
- `03_capture_showcase.mp4`: fixed station and original acquired RGB/ThermalIR panels, 1920 x 1080.

`manifest.json` records original pair paths, hashes, native capture timestamps, camera checks and video timing checks. Per-video `.frames.json` files map every displayed source frame to simulation time. Frame reordering is disabled for the H.264 encoder so the MP4 duration includes the final native timestamp accurately; the terminal frame is held for 1 ms. No motion is interpolated.

Final validation: all three MP4 files decoded completely without errors (407, 448 and 407 frames). Each duration is 46.254 s, just 0.510 ms longer than the native interval. Every presentation timestamp and interval passed the 1 ms validation. Decoded samples at 8, 25 and 43 seconds were visually inspected for all three videos; both modes, route visibility, moving drone, clear drone camera view and original capture panels are present. Details: `decode_validation.json` and `*_inspection.png` beside the videos.
