# Route Capture validation results

Validated on 2026-10-20 in this UE 5.7 project with its customized AirSim plugin and SimpleFlight vehicle `RouteDrone`.

The add-on is implemented in `Plugins/AirSimRouteCapture`. Start with [USAGE.md](USAGE.md), [the JSON standard](JSON_STANDARD.md), and `Open_RouteCaptureDemo.cmd` at the project root. The saved example is `/Game/RouteCapture/Maps/RouteCaptureDemo`.

## Real completed missions

Each pair contains one original 640x480 RGB PNG and one custom ThermalIR type 12 PNG, plus a record with hashes, camera poses, trigger and timing data. All completed missions visited four route nodes with zero new collisions.

| Mission | RGB/IR pairs | Native simulation seconds | Wall seconds | Skipped deadlines | Maximum cross-track error, m |
| --- | ---: | ---: | ---: | ---: | ---: |
| at_nodes | 4 | 52.755 | 54.391 | 0 | 0.142 |
| during_travel | 71 | 43.055 | 57.609 | 3 | 1.383 |
| during_distance | 35 | 43.531 | 51.046 | 0 | 1.413 |

The timed example requests 1000 ms on the first two segments and 100 ms on `C_to_D`. The latter achieved **9.255 pairs per native simulation second**, or 3.347 pairs per wall second. Its 58 committed pairs, 61 eligible deadlines and 3 skipped deadlines are measured results, not an assumed 10 Hz. There were no rejected pairs. The distance example requests 1 m on all three segments and committed all 35 eligible samples; actual cumulative distances and derived spacing are in the integration report.

Native simulation advancement during acquisition setup is counted. Actual freezes contribute no native world-time advancement. All three uninterrupted missions have equal active and native simulation durations. World-origin rebasing is rejected. Vehicle spawn origin (-800,-650,120) cm and scale 100 cm/m resolve node A (-600,-600,250) cm to local NED (2,0.5,-1.3) m; all four resolved nodes are retained in each preflight/context snapshot.

## Fixed observer videos and inspected images

Final media is in `Saved/RouteCaptureReview/Deliverables`:

- `at_nodes_fixed_observer.mp4`
- `during_travel_fixed_observer.mp4`
- `during_distance_fixed_observer.mp4`
- `rgb_ir_examples.png` and `observer_video_examples.png`
- `integration_report.json`, `video_decode_checks.json`, and each video's `.camera_check.json`

Every video frame was decoded successfully. All three actual observer recordings have **zero measured position and rotation change**, at world position (-1900,-2100,1500) cm and fixed FOV 55 degrees. Source frame manifests retain every sampled transform and native simulation timestamp. The videos show the moving physical drone and visible route nodes/guides; overlays add labels only. RGB/IR stills were visually inspected and all 110 original pair directories passed hash, dimensions, image-type and pose-quality checks. All pairs measured zero RGB/IR camera-position separation; maximum camera-angle separation was below 0.000003 degrees.

A live capture-component audit confirms that all 12 tagged route visuals are hidden from every drone capture component. Thermal geometry uses the same hidden-actor list. Sample drone images contain no route labels or guides. IR PNG luminance is display-mapped signal, **not calibrated Kelvin**. Sequential native captures do not prove a shared render-frame identifier.

## Flight controls and landing

The final real control probe paused capture with one committed pair, resumed, then stopped the route. During the sampled pause, active mission time changed by 0.000000 s while native world time advanced 2.187511 s. Capture count stayed fixed and the drone settled to hover. Stop acknowledged cancellation, unfreeze and hover with no recovery errors. Segment wall-rate denominators exclude operator pauses and retain a separate raw wall duration.

Land Here passed independently after a completed mission and again after Stop-and-Hover. Actual backend `Landed` was confirmed, velocity was zero, disarm succeeded, API control was released, and the terminal editor acknowledgement persisted across later ticks. Evidence: `landing_after_completion.json` and `landing_probe.json` in Deliverables.

For this project's SimpleFlight simulator, the guarded touchdown step is enabled only by actual native firmware identity. It requires fresh matching physical ground contact, geometry and stable linear/angular motion before reducing motor output. It still requires the returned Landed state before disarm/handoff. Unknown/PX4 firmware does not receive that step. Its 2 s watchdog is a cooperative target; the installed RPC library checks timeouts once per second, so a requested 0.2 s timeout is not a hard 200 ms bound. The native 45 s stale-heartbeat threshold starts termination/recovery attempts; it does not guarantee hover within 45 s.

## Build, tests and review

- Final development editor build: **passed**, 28.47 s.
- Final Python suite: **61/61 passed**; `Saved/RouteCaptureReview/python_tests.log`.
- Native RouteCapture automation: **5/5 passed**; `Saved/RouteCaptureReview/ReleaseAutomation/index.json`.
- Prior unchanged thermal automation: **15/15 passed**; earlier automation evidence preserved.
- All four example JSON files validate with the strict importer. Native tests cover arbitrary segment IDs, inherited settings and endpoint association through import/export/reordering.
- Independent Astra review found no remaining material defect after the landing and timing fixes; the subsequent live gates above passed.

The external Cosys_Airsim project and unrelated assets were not modified. Earlier failed and superseded experiment folders remain under Saved for traceability. Current final run directories and configuration hashes are listed in `integration_report.json`.
