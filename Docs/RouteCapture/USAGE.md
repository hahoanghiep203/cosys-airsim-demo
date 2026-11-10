# Drone Route Capture

The project add-on lives in `Plugins/AirSimRouteCapture`. It depends on this
project's customized AirSim/ThermalIR plugin and its narrow native route bridge.
It controls simulated multirotors through the existing AirSim API.

## Open the example

1. Open `Open_RouteCaptureDemo.cmd` from the project folder. It loads the example
   map with its project-local flight/camera profile; global AirSim settings are
   not replaced. Change the editor executable path if UE 5.7 is installed elsewhere.
2. Open **Window → Drone Route Capture** and select `RouteDemo_Route`.
3. Set its **Json File** to one of the examples below and click **Import JSON**.
4. Click **Validate route**, enter **Play**, then click **Start (in Play)**.
   Starting Play alone does not start a flight.
5. Watch status and use **Pause**, **Resume**, **Stop and Hover**, or **Land Here**.
   The default completion action is hover, retaining API control until handoff
   or explicit landing. Landing requires the native local descent check.
6. Use **Open output folder** to inspect the run and its actual results.

| Example JSON | Behavior |
| --- | --- |
| `Config/RouteCapture/at_nodes.json` | Stop and capture an RGB/IR pair at each of four nodes; no travel sampling. |
| `Config/RouteCapture/during_travel.json` | Travel sampling at 1000 ms on the first two segments and a target 100 ms on the last; intermediate nodes are pass-through with no node shots. |
| `Config/RouteCapture/during_distance.json` | Travel sampling every 1 m along each segment; intermediate nodes are pass-through. |
| `Config/RouteCapture/combined.json` | Travel sampling plus settled node shots. |

These examples use vehicle `RouteDrone`, local port 41469, camera `0`, and
640 × 480 RGB/ThermalIR. The 100 ms value is a requested simulation-time cadence;
inspect achieved rates and skipped deadlines rather than assuming 10 pairs/s.
The demo camera sits 0.6 m below the drone body so its rotating view remains
clear of the airframe. Camera mount settings belong to the active AirSim profile.

## Author another route

Use **Create route**, then **Add point** or **Create point at selection**.
Move each marker to the drone body's intended position and rotate it to set the
desired camera aim. The selected existing object is left intact when creating
a point at its location. Move the new marker clear of physical geometry.

The ordered point list controls execution. Select a point number to move it
up/down, select its actor, or remove it from the route. Removing a reference
does not delete a user-owned actor. Points can be disabled before export.

Route Details provide defaults and per-segment settings. A segment connects
explicit From/To points; its speed applies on that connection. Node settings
control arrival/settling/hold and single/burst/off captures. Point settings can
override defaults. The **Waypoint**, **Travel**, and **Both defaults** buttons
change defaults; existing explicit overrides retain their values.

Set **Json File**, then **Export JSON** to save the authored mission. Import
validates the strict versioned schema and semantic rules before applying marker
changes. Unknown execution fields are errors. See `JSON_STANDARD.md` for units,
inheritance, timing, quality limits and metric definitions.

## Runtime and output

The panel launches a hidden managed worker with the configured Python executable
(default `.venv/Scripts/python.exe`). The existing workspace environment contains
the required `airsim`, `msgpack`, `msgpackrpc`, `numpy`, `Pillow`, and `jsonschema`
dependencies. The plugin bundles its schema under `Scripts`.

Each run has a unique folder containing the authored input, `mission.json`,
`resolved_mission.json`, native `context.json` and `clock.json`, `status.json`,
events, telemetry, preflight evidence, recovery results and `summary.json`.

```text
<run>/pairs/000001/
  rgb.png
  ir.png
  record.json
```

The complete pair directory is committed atomically. `pairs.jsonl` is a
convenience index; committed pair directories remain authoritative if indexing
fails. A pair contains one RGB image and the project's custom ThermalIR image
(type 12). IR PNG values are display-mapped signal, not calibrated Kelvin.

Captures briefly freeze the simulated scene state and retain each response's
actual timestamp/pose. This does not claim a shared render-frame ID. The output
records acquisition policy and measured camera-pose separation. Scene heating
is not reset between nodes. Processing can slow wall-clock playback.

Normal marker visuals are hidden from drone images. The example deliberately
shows markers/ground guides in a separate fixed observer, while every drone
capture excludes them. `Scripts/RouteCaptureDemo` contains the isolated test
harness and observer recording/encoding tools; those are not the add-on's
product control protocol. Observer frame metadata retains its actual transform
and simulation timestamps so a fixed-camera recording can be audited.

## Validation evidence

Final measured results are summarized in [RESULTS.md](RESULTS.md).

Live acceptance results and final artifact locations are recorded in
`Saved/RouteCaptureReview`. A completed build or offline test alone does not
establish a successful real flight or the requested capture throughput; inspect
each mission summary and the final integration report.
