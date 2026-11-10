# Route Capture JSON standard — proposal 1.0.0

Date: 2026-10-19. Planning artifacts only; the add-on does not exist yet.

This is a project-specific mission format with a formal JSON Schema, rather
than an existing industry flight format or an AirSim `settings.json` file.
The editor panel and JSON import/export will represent the same settings.

- `mission.schema.json`: strict machine-readable structural contract, using
  [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12).
- `mission.example.json`: complete example containing 100 ms and 1000 ms travel
  capture plus a three-pair burst at a node. Its positions are illustrative;
  replace them with exported markers and validate the active scene before flight.
- This document: interpretation, inheritance, semantic checks, and required
  recorded metrics that cannot be expressed through structural validation alone.

## Main decisions

1. **Speed belongs to a segment.** A segment explicitly connects `from` to `to`.
   Its `speed_mps` applies on that connection, never ambiguously before/after a node.
2. **Node capture and travel capture are independent.** A node can capture once,
   take a finite burst, or take no pictures. A segment can capture by time, by
   distance, or take no pictures. Their combination provides both requested modes.
3. **A capture means one complete pair:** one RGB image and one ThermalIR image.
   100 ms targets 10 pairs/s (10 RGB + 10 IR images), rather than 10 total images.
4. **Units are in field names.** `mps`, `mps2`, `ms`, `s`, `m`, `cm`, `deg`, `k`
   and `mb` mean metres/second, metres/second squared, milliseconds, seconds,
   metres, centimetres, degrees, Kelvin and decimal megabytes (1,000,000 bytes).
5. **Targets and achieved results are separate.** Requested 100 ms capture is
   not an assertion of hardware throughput or image synchronization.

## Small editing examples

Travel from A to B at 1.5 m/s, requesting a pair every 100 ms:

```json
{
  "id": "A_to_B",
  "from": "A",
  "to": "B",
  "settings": {
    "speed_mps": 1.5,
    "capture": { "mode": "time_interval", "interval_ms": 100 }
  }
}
```

For one pair per second, change `interval_ms` to `1000`. For a pair every half
metre, replace the whole capture object with:

```json
{ "mode": "distance_interval", "interval_m": 0.5 }
```

At a node, stop, settle for 500 ms, then capture once:

```json
{
  "behavior": "stop",
  "settle_time_ms": 500,
  "capture": { "mode": "single", "delay_ms": 0 }
}
```

These are object fragments, not standalone mission files. Use the full example
for required connection, camera, defaults, route and output settings.

## Groups and adjustable controls

| Group | Controls | Why they matter |
| --- | --- | --- |
| `connection` | Local server/port, selected vehicle and camera, RPC timeout | Select the correct simulator instance and camera. Empty vehicle name means the default vehicle; a name is preferable for multiple available vehicles. |
| `camera` | Width/height, horizontal FOV, aiming mode, angular rate | Control coverage, detail and how quickly framing changes. Resolution/FOV must match the active profile and both streams. |
| `thermal` | Warm-up time, fixed display window | Make heat evolution and brightness comparisons interpretable. Preserve the scene's existing emissivity/source settings in output metadata. |
| `defaults.segment` and segment overrides | Speed, acceleration/deceleration profile, deadline, time/distance/off capture | Slow down near inspection targets or sample densely on selected connections. Acceleration values are requested speed-profile ramps, not proven hard bounds on physical motion. |
| `defaults.node` and node overrides | Stop/pass-through, arrival radius, settled-speed/aim tolerances, settling, extra hold, single/burst/off capture | Decide where to pause and what counts as a settled shot. |
| `flight` | Takeoff height/deadline, initial connection speed/deadline, completion action | Control reaching the first node and finishing the route. Entry/takeoff have no periodic capture in v1. |
| `acquisition` | Pair policy, pair pose tolerances, capture watchdog, write-queue limit and overload action | Keep pairing quality and resource use measurable. |
| `limits` | Wall-time limit, maximum pair count, free disk, clearance, route-error limit/grace | Bound a run and define abort conditions. |
| `output` | Project-relative or absolute root, PNG output, pair records/summary | Keep every run separate and retain evidence of results. |
| `metrics` | Telemetry interval, optional image-quality statistics | Balance diagnostics against measurement overhead. Timing/pose/error/commit records are always required. |

`camera.configuration_policy` and `thermal.configuration_policy` are
`require_active_match`: they describe and validate the loaded profile. They do
not silently rewrite global settings or imply that every camera setting can be
changed through RPC. Emit a clear mismatch before arming.

For aiming, `marker_rotation` uses each node's camera rotation in Unreal world
space with quaternion interpolation along the segment. `fixed_body_rotation`
keeps a fixed orientation relative to the drone, such as a -45-degree pitch.
Camera mount translation is preserved and recorded. An angular rate limit can
require additional settling at a stop; it does not guarantee that an arbitrary
short segment can attain an arbitrary final camera angle during flight.

`flight.on_complete` supports `hover` or explicitly requested `land_here`.
Landing requires a validated local descent. `on_error` always requests cancel
then hover, and the output records whether recovery was acknowledged. API
control remains owned during hover until explicit handoff or landing.

## Defaults, overrides and route identity

The full `defaults.node` and `defaults.segment` objects are required. Each
node/segment can override their scalar fields with `settings`. An omitted field
inherits its corresponding default. `capture` is replaced as one complete
object, never recursively merged: switching from time to distance must remove
the old time interval. `null`, unknown fields and misspelled keys are errors.
JSON Schema annotations do not populate missing settings; the future importer
must perform explicit resolution and store `resolved_mission.json` for each run.

The `nodes` array defines execution order. Stable node IDs identify marker data;
display numbers come from array order. For N nodes there must be exactly N-1
segments, also in order, matching each consecutive node pair. There are no
branches, cycles or repeat counts in 1.0.0. Disabled editor points are excluded
when exporting a mission, and the editor regenerates the resulting connections.

Keep original authoring data in `mission.json` and the merged effective values
in `resolved_mission.json`. Neither is changed midway through an active run.
The file may include `metadata` for free-form notes; metadata cannot alter
execution. Version 1.0.0 importers accept exactly `schema_version: "1.0.0"`;
future versions require an explicit migration, not guessed compatibility.

## Coordinates and clocks

Node `position_cm` is the drone body reference position in Unreal world space,
not a camera-lens position or AirSim NED coordinate. Rotations are Unreal editor
Euler values. At Start, convert using the selected vehicle's stored spawn-frame
transform and world scale, and record both authored and resolved coordinates.
World-origin rebasing is rejected in this version. Never subtract the vehicle's
current position to invent a new origin.

Timing fields have these fixed clock domains:

| Fields | Clock |
| --- | --- |
| Travel/node `interval_ms`, node settling/delay/hold, thermal warm-up | Unpaused simulation elapsed time. |
| `timeout_s`, `rpc_timeout_s`, `capture_timeout_ms`, `max_duration_wall_s` | Monotonic wall time; still expire if simulation/capture stalls. |
| `cross_track_grace_ms` | Active travel simulation time while route error stays above the limit; reset when back within tolerance. |
| `metrics.telemetry_interval_ms` | Target active simulation cadence; collect an additional telemetry sample at capture/arrival/failure regardless of timer. |

The integration bridge must expose accumulated unpaused simulation elapsed time,
and milestone 1 must verify it against flight/thermal advancement. Do not assume
the raw AirLib image timestamp has this behavior: preserve its nanosecond value
separately. Record simulation clock configuration, monotonic wall timing and UTC
run creation time. UTC is for identification; it does not schedule captures.

Capture policy `freeze_simulation` targets a stable scene state for each RGB/IR
pair, without promising a shared render frame. Freezes can slow wall-clock
playback. Always restore previous pause state. Pair position/angle tolerances
are checked after transforming both response poses to the same documented
frame. Keep actual per-image timestamps even if a freeze was used. A timestamp
difference alone does not prove movement, and equal timestamps alone do not
prove the same render frame.

## Exact trigger and node behavior

- Each travel segment starts its own schedule. For a time period P, deadlines
  are active segment time P, 2P, 3P... strictly before segment completion. Do not
  restart the timer after an image finishes. There is no automatic sample at
  segment start or end. Node capture explicitly covers endpoints.
- Active segment time excludes mission pause/hover, node settling/holding and
  acquisition freezes. Pause/resume retains remaining active time; it does not
  produce catch-up bursts. Overall mission simulation time still includes
  ordinary node warm-up and dwell.
- Distance triggers use accumulated actual 3D travel on the segment at D, 2D,
  3D... strictly before completion. They exclude intentional hovering and reset
  per segment. If telemetry crosses several deadlines between samples, acquire
  at most the latest eligible sample and log the earlier missed distances.
- A node with `behavior: stop` must satisfy its position, speed and aim
  tolerances continuously for `settle_time_ms`. Then wait `capture.delay_ms`,
  if applicable, and acquire the single/burst samples. Burst spacing follows
  the successful-start rule below. After the last
  node capture, wait `extra_hold_ms` before departure. For capture `off`, hold
  starts after settling. A failed node capture is never silently skipped.
- Node bursts are finite. Hold at the node and retry a missed node sample
  until it succeeds, the bad-pair limit is reached, or the node/operation
  deadline fails, whichever occurs first. For a burst, `interval_ms` is the
  minimum simulation-time spacing between successful sample starts; schedule
  the next sample from the previous successful sample's start plus that
  interval. Retries retain the same sample index. This finite node-burst policy
  can extend the burst under delays and differs from the absolute travel
  schedule. Record both requested and actual spacing. Never substitute repeated
  files or pretend a late image was captured at an earlier deadline. The node watchdog
  uses the incoming segment's `timeout_s` (or `flight.entry_leg.timeout_s` for
  the first node), restarted on entering node handling; it bounds the whole
  settling/burst/hold operation separately from that segment's flight deadline.
- A `fly_through` node requires capture `off`, settling 0 and extra hold 0.
  Pass within the arrival radius and preserve progress into the next segment.
  Intermediate stop-only speed/aim thresholds do not require hovering there.
  The final node must be `stop` so the run can finish with verified hover/landing.
- Travel capture is suspended during node handling. Endpoint deadlines are
  excluded, so travel and node trigger windows do not overlap in 1.0.0 and
  require no merge heuristic. There is exactly one settled node event per
  visit, which may itself be a finite burst. A shot taken before a node has
  settled cannot be relabelled as a settled node shot.

For **node-only capture**, set the default segment capture to `off`. For
**travel-only capture**, set the default node capture to `off` and choose
`fly_through` with zero settling/hold for intermediate nodes if continuous
movement is desired. For **both**, enable both independently. The full example
uses both and stops at all three nodes.

## Backpressure, invalid pairs and limits

Allow one image request in flight. Bound completed-pair disk writes by
`max_pending_writes`; reserve capacity before beginning acquisition. If an
interval trigger cannot run, `skip_and_log` skips it, increments counters and
advances to the next deadline. `stop_mission` aborts instead. There is no queue
of old image requests, no backfill of missed views, and no silent rate reduction.
The consecutive-missed-trigger counter counts skipped eligible interval
deadlines; reset it when an interval trigger is admitted for acquisition or a
new segment starts. An acquired but rejected pair is counted by the bad-pair
counter instead. Node work neither increments nor resets interval-miss counts.
Abort once the consecutive-missed-trigger threshold is reached.

Interval pairs with invalid/empty/mismatched image data or excessive camera
pose separation are rejected and logged; abort at the bad-pair threshold. A
successful valid pair clears that counter. Reaching the bad-pair threshold
aborts immediately, including at a node; it takes precedence over node retries.
Mandatory node samples otherwise hold and retry within their watchdog. RPC loss, collision,
capture watchdog expiry, unwritable output or unrecoverable write errors stop
the mission immediately and attempt cancel/unfreeze/hover. An independent
supervisor handles a blocked worker; the transport timeout remains a separate
hard bound on the blocked connection.

`max_pairs` counts committed complete pairs. Reaching a limit before all
mandatory work finishes yields `limit_reached` with an incomplete route, not
`completed`. Normal completion requires all route and mandatory node work.
Write failures never increase the valid-pair count. Pair pose tolerances and
the chosen cadence must be checked against measured hardware capability.

## Required semantic and preflight validation

Structural schema validation is necessary but insufficient. The importer must:

1. Reject duplicate JSON property names, nonfinite numbers, unsupported version,
   duplicate node/segment IDs, missing endpoints and out-of-order connections.
2. Require distinct adjacent positions, exactly N-1 segments, and a stop at the
   final node. Resolve defaults, then validate effective stop/pass-through and
   capture combinations, including inherited values.
3. Require `display_window_k.min < max`, and require camera/thermal configuration
   to match the active profile. Verify the map, Multirotor mode, selected vehicle,
   camera, image types, coordinate context and freeze behavior.
4. Check requested node burst/settle/delay/hold duration against the wall-time
   node watchdog using the active and measured simulation rate at runtime;
   never compare milliseconds of simulation directly with seconds of wall time.
   The JSON-only check cannot prove that feasibility. Check limits against
   mandatory node counts; warn when speed,
   distance and interval suggest a much larger run than configured limits.
5. Check loaded-scene obstacles including takeoff/entry/descent, writable output,
   free disk, worker/runtime dependencies, and support for every execution field.
   Unimplemented execution options must fail preflight rather than be ignored.
6. Export a resolved mission and configuration hash. Include original and
   resolved configuration in the run so inheritance and profile changes are
   auditable. Hash the actual resolved JSON representation used for execution.

Example-only schema validation does not establish safe paths, real camera
compatibility, throughput, or flight accuracy.

## Metrics to record

The following are requirements for the future run writer, not measured results
from this planning phase. Missing measurements are `null` with an explanation,
never zero. Raw timestamps are decimal strings where needed to preserve
nanosecond precision. Quantiles state their method and sample count.

| Scope | Required metrics | Interpretation |
| --- | --- | --- |
| Each pair | Pair/trigger/node-or-segment IDs; scheduled and actual simulation time; both original image timestamps and camera poses; vehicle position/orientation/velocity; target and actual segment speed; file paths/dimensions/types/bytes; thermal elapsed time | Relate every saved view to its route position and physical state. Never invent one shared source timestamp. |
| Pair quality | Absolute RGB/IR timestamp difference; camera position/angle difference; actual acquisition policy/backend; pose-normalization frame; invalid/partial reasons; optional actual snapshot/frame ID | Measure alignment; mark unproven frame synchronization explicitly. Quaternion angle uses the shortest rotation and treats q and -q as equivalent. |
| Capture performance | Requested interval/rate; eligible deadlines; attempted/valid/rejected/skipped samples; per-request acquisition latency, encoding/write/commit latency; schedule lateness; actual pair spacing; queue high-water mark | Show where a rate target was missed. Report latency p50/p95/max and counts. Acquisition latency and end-to-end commit latency are different. |
| Each segment | Target speed/profile; actual speed mean/max/p95; travelled distance; duration; maximum/RMS cross-track error; pair rate and drops | Compare commanded travel with what the drone actually did. Cross-track error is shortest distance to the commanded segment, not merely distance to its endpoint. |
| Each stopped node | Arrival position/aim error; settling/holding duration; burst target/actual spacing; mandatory samples expected/committed; retries | Confirm that shots satisfy the node's intended framing and stability. |
| Image quality, when enabled | RGB luminance mean, dark/clipped fraction, labelled blur proxy; IR min/max/percentiles and lower/upper display clipping fraction | Detect poor exposure, blur and a thermal window that hides useful contrast. IR PNG statistics are display signal, not calibrated temperature. Label any blur proxy rather than treating it as a universal sharpness score. |
| Thermal context | Warm-up requested/actual; elapsed thermal simulation time; display window; actual source/receiver settings or references; receiver sample/backend diagnostics when available | Explain scene changes over the route. Do not reset thermal state between nodes. |
| Run summary | Completion state/reason; route progress; total pairs/images/bytes; periodic target/achieved pair rates; missed/rejected totals; alignment/latency statistics; max route error; collisions; wall vs simulation duration; recovery acknowledgement | Distinguish complete, aborted and limit-reached runs, with actual output counts. |

Rate definitions:

- Requested time-cadence pair rate = `1000 / interval_ms`.
- Periodic achieved simulation rate = valid travel-trigger pairs / active
  travel simulation seconds, reported per segment when cadence varies.
- Periodic achieved wall rate = valid travel-trigger pairs / wall seconds
  spent in that segment's capture-enabled travel, excluding operator pauses
  and node handling but including acquisition freezes and processing.
- Whole-run pair rate = all committed pairs / run duration, with simulation and
  wall versions; label it separately because it includes node bursts and holds.
- Deadline success ratio = valid eligible travel deadlines / eligible travel
  deadlines. Record skipped and rejected categories separately. Report `null`
  if there were no eligible deadlines.
- Distance cadence reports actual between-pair travel distance/error as well
  as image count; do not express a distance trigger as a fixed requested FPS.

The panel should surface actual pairs/s, missed captures, pair-alignment status,
current/target speed, remaining route, elapsed time and storage. Detailed
statistics belong in the output report rather than filling the main panel.

## Later extensions, kept outside 1.0.0

Useful later controls include tracked-object aiming, repeat/loop routes,
exposure/shutter profile authoring, image-footprint overlap planning, terrain-
relative altitude and true radiometric outputs. Add them only with defined
semantics and a schema migration; 1.0.0 rejects unknown execution fields.

## Validation status and references

Schema/example checks are recorded in `validation_report.json`. They cover
structural rules and a bounded set of documented semantic checks. The native
importer and mission runner are implemented and validated separately: see
[RESULTS.md](RESULTS.md) for real node, timed and distance flights, measured
100 ms throughput, paired-state checks and recovery evidence.

- [JSON Schema specification](https://json-schema.org/draft/2020-12) and
  [validation vocabulary](https://json-schema.org/draft/2020-12/json-schema-validation).
- [AirSim image API](https://microsoft.github.io/AirSim/image_apis/): per-image
  metadata and paused state acquisition.
- [AirSim settings](https://microsoft.github.io/AirSim/settings/): simulation
  clock configuration and camera profiles; local fork behavior must be verified.
- Local `Plugins/AirSim/Source/UnrealImageCapture.cpp`: sequential GPU ThermalIR
  and Scene capture; one RPC batch does not by itself prove one render frame.
