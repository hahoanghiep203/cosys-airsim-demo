"""Route Capture 1.0 runtime. Importing this module never connects to AirSim.

CLI: route_capture.py --mission mission.json --run-dir run --context context.json
Use --validate-only without an editor, or --preflight for read-only live checks.
Each pairs/<sequence>/ directory is an atomic complete pair, including record.json.
The JSONL index is a convenience; committed directories are authoritative.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import queue
import shutil
import statistics
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = Path(__file__).with_name("mission.schema.json")


class MissionError(RuntimeError):
    pass


class MissionStopped(MissionError):
    pass


class MissionLimit(MissionError):
    pass


class BadPair(MissionError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MissionError("Duplicate JSON property: " + key)
        result[key] = value
    return result


def read_json(path):
    def reject(value):
        raise MissionError("Nonfinite JSON number: " + value)
    with Path(path).open(encoding="utf-8-sig") as stream:
        value = json.load(stream, object_pairs_hook=_unique_object, parse_constant=reject)
    _finite(value)
    return value


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise MissionError("Nonfinite number")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    if isinstance(value, (list, tuple)):
        for item in value:
            _finite(item)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers that omit FILE_SHARE_DELETE can briefly hold the
        # destination open. Keep the previous complete JSON visible while
        # retrying only sharing/access-denied errors, with a hard wall bound.
        deadline, backoff = time.monotonic()+.75, .01
        while True:
            try:
                os.replace(temporary, path)
                break
            except OSError as error:
                if getattr(error, "winerror", None) not in (5, 32, 33):
                    raise
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(backoff, remaining))
                backoff = min(.05, backoff*2)
    finally:
        temporary.unlink(missing_ok=True)


def vec(value):
    if isinstance(value, dict):
        return tuple(float(value[k]) for k in ("x", "y", "z"))
    return (float(value.x_val), float(value.y_val), float(value.z_val))


def xyz(value):
    return dict(zip(("x", "y", "z"), value))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(sum(x * x for x in a))


def quat(value):
    if isinstance(value, dict):
        q = tuple(float(value[k]) for k in ("x", "y", "z", "w"))
    elif isinstance(value, (list, tuple)):
        q = tuple(value)
    else:
        q = (value.x_val, value.y_val, value.z_val, value.w_val)
    size = norm(q)
    if not all(math.isfinite(x) for x in q) or size < 1e-12:
        raise BadPair("Invalid camera/vehicle quaternion")
    return tuple(x / size for x in q)


def qdict(q):
    return dict(zip(("x", "y", "z", "w"), q))


def qmul(a, b):
    x, y, z, w = a
    X, Y, Z, W = b
    return quat((w * X + x * W + y * Z - z * Y,
                 w * Y - x * Z + y * W + z * X,
                 w * Z + x * Y - y * X + z * W,
                 w * W - x * X - y * Y - z * Z))


def qinverse(q):
    return (-q[0], -q[1], -q[2], q[3])


def qrotate(q, value):
    # Quaternion-vector rotation without normalizing the vector as a quaternion.
    x, y, z, w = q
    vx, vy, vz = value
    tx, ty, tz = 2*(y*vz-z*vy), 2*(z*vx-x*vz), 2*(x*vy-y*vx)
    return (vx+w*tx+y*tz-z*ty, vy+w*ty+z*tx-x*tz, vz+w*tz+x*ty-y*tx)


def euler_quat(rotation):
    # Unreal FRotator converted by NedTransform::toNed: (-UE.X,-UE.Y,UE.Z,UE.W).
    p, y, r = (math.radians(rotation[k]) / 2 for k in ("pitch", "yaw", "roll"))
    return quat((math.sin(r)*math.cos(p)*math.cos(y)-math.cos(r)*math.sin(p)*math.sin(y),
                 math.cos(r)*math.sin(p)*math.cos(y)+math.sin(r)*math.cos(p)*math.sin(y),
                 math.cos(r)*math.cos(p)*math.sin(y)-math.sin(r)*math.sin(p)*math.cos(y),
                 math.cos(r)*math.cos(p)*math.cos(y)+math.sin(r)*math.sin(p)*math.sin(y)))


def qangle(a, b):
    return math.degrees(2 * math.acos(min(1., abs(sum(x * y for x, y in zip(quat(a), quat(b)))))))


def slerp(a, b, fraction):
    a, b = quat(a), quat(b)
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b, dot = tuple(-x for x in b), -dot
    t = max(0., min(1., fraction))
    if dot > .9995:
        return quat(tuple(x + t * (y - x) for x, y in zip(a, b)))
    angle = math.acos(min(1., dot))
    return quat(tuple((math.sin((1-t)*angle)*x + math.sin(t*angle)*y)/math.sin(angle)
                      for x, y in zip(a, b)))


def route_error(position, start, end):
    delta = sub(end, start)
    if norm(delta) < 1e-12:
        return norm(sub(position, end)), 1.
    t = max(0., min(1., sum(x*y for x, y in zip(sub(position, start), delta)) /
                       sum(x*x for x in delta)))
    nearest = tuple(x + t*y for x, y in zip(start, delta))
    return norm(sub(position, nearest)), t


def load_mission(source, schema_path=SCHEMA):
    """Strict schema + semantic validation; return (authored, resolved, warnings)."""
    from jsonschema import Draft202012Validator
    authored = copy.deepcopy(source) if isinstance(source, dict) else read_json(source)
    _finite(authored)
    errors = sorted(Draft202012Validator(read_json(schema_path)).iter_errors(authored),
                    key=lambda e: str(list(e.absolute_path)))
    if errors:
        raise MissionError("Schema: " + "; ".join(
            "/".join(str(x) for x in e.absolute_path) + ": " + e.message for e in errors[:8]))
    resolved = copy.deepcopy(authored)
    for group, default in (("nodes", "node"), ("segments", "segment")):
        identifiers = [item["id"] for item in resolved[group]]
        if len(identifiers) != len(set(identifiers)):
            raise MissionError("Duplicate " + default + " ID")
        for item in resolved[group]:
            # capture is deliberately replaced whole, never recursively merged.
            item["settings"] = {**copy.deepcopy(resolved["defaults"][default]), **item.get("settings", {})}
    nodes, segments = resolved["nodes"], resolved["segments"]
    if len(segments) != len(nodes) - 1:
        raise MissionError("Expected exactly N-1 ordered segments")
    for index, segment in enumerate(segments):
        a, b = nodes[index:index + 2]
        if (segment["from"], segment["to"]) != (a["id"], b["id"]):
            raise MissionError("Segment endpoints/order mismatch: " + segment["id"])
        if norm(sub(vec(a["position_cm"]), vec(b["position_cm"]))) < 1e-9:
            raise MissionError("Adjacent nodes must have distinct positions")
    mandatory = 0
    for node in nodes:
        settings = node["settings"]
        capture = settings["capture"]
        if settings["behavior"] == "fly_through" and (
                capture["mode"] != "off" or settings["settle_time_ms"] or settings["extra_hold_ms"]):
            raise MissionError("fly_through requires capture off and zero settle/hold: " + node["id"])
        mandatory += capture.get("count", 1) if capture["mode"] != "off" else 0
    if nodes[-1]["settings"]["behavior"] != "stop":
        raise MissionError("Final node must stop")
    window = resolved["thermal"]["display_window_k"]
    if window["min"] >= window["max"]:
        raise MissionError("Thermal display_window_k.min must be less than max")
    if mandatory > resolved["limits"]["max_pairs"]:
        raise MissionError("max_pairs cannot accommodate mandatory node samples")
    warnings = []
    estimate = mandatory
    for index, segment in enumerate(segments):
        capture, settings = segment["settings"]["capture"], segment["settings"]
        distance = norm(sub(vec(nodes[index+1]["position_cm"]), vec(nodes[index]["position_cm"]))) / 100
        if capture["mode"] == "time_interval":
            estimate += max(0, math.ceil(distance / settings["speed_mps"] * 1000 / capture["interval_ms"]) - 1)
        if capture["mode"] == "distance_interval":
            estimate += max(0, math.ceil(distance / capture["interval_m"]) - 1)
    if estimate > resolved["limits"]["max_pairs"]:
        warnings.append("Estimated nominal pairs exceed max_pairs; runtime may finish limit_reached")
    warnings.append("JSON validation cannot establish loaded-scene safety, camera compatibility or throughput")
    return authored, resolved, warnings


def resolve_context(mission, source):
    context = copy.deepcopy(source) if isinstance(source, dict) else read_json(source)
    _finite(context)
    if context.get("schema_version") != "1.0.0":
        raise MissionError("Unsupported/missing context schema_version")
    if context.get("vehicle_name") != mission["connection"]["vehicle_name"]:
        raise MissionError("Coordinate context belongs to a different vehicle")
    scale = context.get("world_to_meters", 0)
    if not isinstance(scale, (float, int)) or scale <= 0:
        raise MissionError("Missing/invalid world_to_meters")
    try:
        origin = vec(context["vehicle_origin_ue_cm"])
    except (KeyError, TypeError, ValueError) as error:
        raise MissionError("Stored vehicle spawn origin is required") from error
    result = copy.deepcopy(mission)
    for node in result["nodes"]:
        delta = sub(vec(node["position_cm"]), origin)
        node["position_ned_m"] = xyz((delta[0]/scale, delta[1]/scale, -delta[2]/scale))
    if "resolved_nodes" in context:
        native = context["resolved_nodes"]
        if len(native) != len(result["nodes"]):
            raise MissionError("Native validated route node count differs from mission")
        for node, saved in zip(result["nodes"], native):
            if (node["id"] != saved.get("id") or "position_ned_m" not in saved or
                    norm(sub(vec(node["position_ned_m"]), vec(saved["position_ned_m"]))) > 1e-5):
                raise MissionError("Native clearance context belongs to a different route")
    result["coordinate_context"] = context
    return result, context


class IntervalSchedule:
    """Absolute travel deadlines; one latest eligible request, no catch-up queue."""
    def __init__(self, capture):
        self.mode = capture["mode"]
        self.period = (capture.get("interval_ms", 0) / 1000 if self.mode == "time_interval"
                       else capture.get("interval_m", 0))
        self.next_index = 1

    def due(self, active_seconds, travelled_m, completed=False):
        if completed or self.mode == "off":
            return None, []
        value = active_seconds if self.mode == "time_interval" else travelled_m
        latest = math.floor((value + 1e-10) / self.period)
        if latest < self.next_index:
            return None, []
        missed = [index*self.period for index in range(self.next_index, latest)]
        self.next_index = latest + 1
        return latest*self.period, missed


def read_clock_snapshot(path, max_age_s=None, label="Native simulation clock"):
    """Read a real native document, tolerating at most 100 ms of file contention.

    Python's Windows CRT may expose a sharing violation as plain EACCES with
    no winerror, so PermissionError is retried too. Persistent errors still
    fail; failed reads never return cached data or refresh any heartbeat.
    """
    path = Path(path)
    deadline = time.monotonic()+.1
    while True:
        try:
            stat = path.stat()
            value = read_json(path)
            break
        except OSError as error:
            retryable = isinstance(error, (FileNotFoundError, PermissionError)) or getattr(error, "winerror", None) in (5, 32, 33)
            remaining = deadline-time.monotonic()
            if not retryable or remaining <= 0:
                raise MissionError("Cannot read native simulation clock: " + str(error)) from error
            time.sleep(min(.01, remaining))
        except ValueError as error:
            raise MissionError("Cannot read native simulation clock: " + str(error)) from error
    if not isinstance(value, dict):
        raise MissionError(label + " snapshot must be a JSON object")
    if max_age_s is not None and time.time()-stat.st_mtime > max_age_s:
        raise MissionError(label + " heartbeat is stale")
    return stat.st_mtime_ns, value


class NativeClock:
    """Native world time (never image timestamps), with a wall-time stale watchdog."""
    def __init__(self, context, stale_s=3., monotonic=time.monotonic):
        name = context.get("sim_clock_path", context.get("sim_clock_file"))
        if not name:
            raise MissionError("Native unpaused simulation clock file is required")
        self.path = Path(name)
        self.context = context
        self.stale_s, self.monotonic = stale_s, monotonic
        self.last_stamp, self.last_change, self.previous = None, monotonic(), None

    def read(self):
        stamp, value = read_clock_snapshot(self.path)
        now = self.monotonic()
        if stamp != self.last_stamp:
            self.last_stamp, self.last_change = stamp, now
        if now - self.last_change > self.stale_s:
            raise MissionError("Native clock heartbeat stalled")
        if value.get("world_origin_valid") is False:
            raise MissionError("World origin rebased during mission")
        origin = value.get("world_origin_ue_cm")
        expected = self.context.get("world_origin_ue_cm", self.context.get("world_origin"))
        if origin is not None and expected is not None and vec(origin) != vec(expected):
            raise MissionError("World origin rebased during mission")
        seconds = value.get("simulation_time_s", value.get("unpaused_simulation_seconds"))
        if not isinstance(seconds, (float, int)) or not math.isfinite(seconds):
            raise MissionError("Missing native simulation_time_s")
        if self.previous is not None and seconds < self.previous - 1e-6:
            raise MissionError("Native simulation clock moved backwards")
        self.previous = seconds
        return float(seconds), bool(value.get("paused", False))


class PairWriter:
    """A single disk worker with capacity reserved *before* image acquisition."""
    def __init__(self, run_dir, capacity):
        self.root = Path(run_dir)
        (self.root / "pairs").mkdir()
        self.capacity = threading.BoundedSemaphore(capacity)
        self.work = queue.Queue(maxsize=capacity)
        self.results = queue.Queue()
        self.pending = 0
        self.high_water = 0
        self.thread = threading.Thread(target=self._worker, daemon=True, name="route-pair-writer")
        self.thread.start()

    def reserve(self):
        if not self.capacity.acquire(blocking=False):
            return False
        self.pending += 1
        self.high_water = max(self.high_water, self.pending)
        return True

    def release(self):
        self.pending -= 1
        self.capacity.release()

    def submit(self, sequence, images, record):
        self.work.put_nowait((sequence, images, record))

    def _worker(self):
        while True:
            item = self.work.get()
            if item is None:
                return
            sequence, images, record = item
            temporary = self.root / "pairs" / (".pending-" + uuid.uuid4().hex)
            try:
                temporary.mkdir()
                started = time.monotonic()
                for label, payload in images.items():
                    with (temporary / (label + ".png")).open("wb") as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                record["write_latency_wall_s"] = time.monotonic() - started
                record["commit_latency_wall_s"] = time.monotonic() - record.pop("_capture_started_wall")
                record["committed_utc"] = datetime.now(timezone.utc).isoformat()
                atomic_json(temporary / "record.json", record)
                destination = self.root / "pairs" / f"{sequence:06d}"
                if destination.exists():
                    raise MissionError("Pair sequence already committed")
                os.replace(temporary, destination)
                # A convenience index can fail *after* the authoritative transaction.
                # Preserve the committed pair and let the mission count it before aborting.
                try:
                    with (self.root / "pairs.jsonl").open("ab") as stream:
                        stream.write(canonical(record) + b"\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                except Exception as error:
                    record["_index_error"] = str(error)
                self.results.put((True, record))
            except Exception as error:
                self.results.put((False, str(error)))
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
                self.work.task_done()


def _large_legacy_frames():
    import msgpack
    import msgpackrpc.transport.tcp as rpc_tcp
    if getattr(rpc_tcp.BaseSocket, "_route_capture_patched", False):
        return
    original = rpc_tcp.BaseSocket.__init__
    def initialize(self, stream, encodings):
        original(self, stream, encodings)
        self._unpacker = msgpack.Unpacker(encoding=encodings[1], max_buffer_size=256*1024*1024,
            max_bin_len=128*1024*1024, max_str_len=128*1024*1024, max_array_len=4*1024*1024)
    rpc_tcp.BaseSocket.__init__ = initialize
    rpc_tcp.BaseSocket._route_capture_patched = True


def airsim_client(connection, capture=False):
    import airsim
    _large_legacy_frames()
    timeout = connection["rpc_timeout_s"]
    return airsim.MultirotorClient(ip=connection["host"], port=connection["port"], timeout_value=timeout)


def image_quality(payload, label):
    from PIL import Image, ImageFilter, ImageStat
    with Image.open(io.BytesIO(payload)) as image:
        gray = image.convert("L")
        histogram = gray.histogram()
        total = sum(histogram)
        mean = ImageStat.Stat(gray).mean[0]
        def percentile(fraction):
            running = 0
            for index, count in enumerate(histogram):
                running += count
                if running >= total*fraction:
                    return index
        if label == "rgb":
            return {"luminance_mean_0_255": mean, "dark_fraction_le_5": sum(histogram[:6])/total,
                    "clipped_fraction_ge_250": sum(histogram[250:])/total,
                    "blur_proxy": {"method": "mean FIND_EDGES luminance (border included)",
                                   "value": ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]}}
        return {"signal": "display PNG luminance, not calibrated Kelvin", "min": percentile(0.00000001),
                "max": percentile(1), "p05": percentile(.05), "p50": percentile(.5), "p95": percentile(.95),
                "lower_display_clipping_fraction": histogram[0]/total,
                "upper_display_clipping_fraction": histogram[255]/total}


def validate_pair(responses, mission):
    from PIL import Image
    if len(responses) != 2:
        raise BadPair("Expected exactly two image responses")
    images, metadata = {}, {}
    for label, expected, response in zip(("rgb", "ir"), (0, 12), responses):
        if response.message or response.width <= 0 or response.height <= 0:
            raise BadPair(label + ": " + str(response.message or "empty image"))
        if response.image_type != expected:
            raise BadPair(label + ": unexpected image type")
        if (response.width, response.height) != (mission["camera"]["width_px"], mission["camera"]["height_px"]):
            raise BadPair(label + ": image dimensions mismatch active mission profile")
        payload = bytes(response.image_data_uint8)
        try:
            with Image.open(io.BytesIO(payload)) as image:
                if image.format != "PNG" or image.size != (response.width, response.height):
                    raise ValueError("wrong PNG dimensions/format")
                image.verify()
        except Exception as error:
            raise BadPair(label + ": invalid PNG: " + str(error)) from error
        position, orientation = vec(response.camera_position), quat(response.camera_orientation)
        if not all(math.isfinite(x) for x in position):
            raise BadPair("Nonfinite camera position")
        images[label] = payload
        metadata[label] = {"image_type": expected, "source_timestamp_ns": str(response.time_stamp),
            "camera_pose": {"position_ned_m": xyz(position), "orientation_xyzw": qdict(orientation)},
            "width_px": response.width, "height_px": response.height, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}
        if mission["metrics"]["record_image_quality"]:
            metadata[label]["quality"] = image_quality(payload, label)
    delta = norm(sub(vec(responses[0].camera_position), vec(responses[1].camera_position)))
    angle = qangle(quat(responses[0].camera_orientation), quat(responses[1].camera_orientation))
    quality = {"position_delta_m": delta, "angle_delta_deg": angle,
               "timestamp_delta_ns": str(abs(int(responses[0].time_stamp)-int(responses[1].time_stamp))),
               "pose_frame": "vehicle_spawn_local_NED_world_axes",
               "shared_render_frame_proven": False, "snapshot_frame_id": None}
    acquisition = mission["acquisition"]
    if delta > acquisition["max_pair_position_delta_m"] or angle > acquisition["max_pair_angle_delta_deg"]:
        raise BadPair("RGB/IR camera pose separation exceeds tolerance: " + json.dumps(quality))
    return images, metadata, quality


class CaptureWorker:
    """Only this daemon owns the image RPC client; at most one request in flight."""
    def __init__(self, mission):
        self.mission = mission
        self.requests, self.results = queue.Queue(maxsize=1), queue.Queue(maxsize=1)
        self.thread = threading.Thread(target=self._worker, daemon=True, name="route-image-rpc")
        self.thread.start()

    def _worker(self):
        import airsim
        connection = dict(self.mission["connection"])
        connection["rpc_timeout_s"] = min(connection["rpc_timeout_s"],
            self.mission["acquisition"]["capture_timeout_ms"] / 1000)
        try:
            client = airsim_client(connection, capture=True)
        except Exception as error:
            self.results.put((False, error))
            return
        while True:
            request = self.requests.get()
            if request is None:
                return
            previous_pause = None
            result = None
            try:
                previous_pause = bool(client.simIsPause())
                clock_path = self.mission["coordinate_context"].get("sim_clock_path",
                             self.mission["coordinate_context"].get("sim_clock_file"))
                baseline_stamp = baseline_clock = None
                if clock_path:
                    baseline_stamp, baseline_clock = read_clock_snapshot(clock_path, max_age_s=3.)
                client.simPause(True)
                if not client.simIsPause():
                    raise MissionError("Simulator did not acknowledge acquisition freeze")
                clock_before = None
                if clock_path:
                    # A paused=true document can belong to the preceding pair.
                    # Require a publication newer than the pre-command snapshot.
                    pause_deadline = time.monotonic()+min(1., connection["rpc_timeout_s"])
                    while True:
                        before_stamp, clock_before = read_clock_snapshot(clock_path, max_age_s=3.)
                        if before_stamp > baseline_stamp and clock_before.get("paused"):
                            break
                        if time.monotonic() >= pause_deadline:
                            raise MissionError("Native clock did not acknowledge acquisition freeze")
                        time.sleep(.02)
                    baseline_s = baseline_clock.get("simulation_time_s", baseline_clock.get("unpaused_simulation_seconds"))
                    frozen_s = clock_before.get("simulation_time_s", clock_before.get("unpaused_simulation_seconds"))
                    if baseline_s is None or frozen_s is None or frozen_s < baseline_s:
                        raise MissionError("Native simulation clock moved backwards during acquisition freeze")
                if request.get("verify_freeze"):
                    if not clock_before:
                        raise MissionError("Native clock is required to verify acquisition freeze")
                    # Preflight additionally proves world time stays fixed while paused.
                    time.sleep(.08)
                    after_stamp, clock_after = read_clock_snapshot(clock_path, max_age_s=3.)
                    before_s = clock_before.get("simulation_time_s", clock_before.get("unpaused_simulation_seconds"))
                    after_s = clock_after.get("simulation_time_s", clock_after.get("unpaused_simulation_seconds"))
                    if not clock_after.get("paused") or after_stamp < before_stamp:
                        raise MissionError("Native simulation clock did not remain paused during acquisition freeze")
                    if before_s is None or after_s != before_s:
                        raise MissionError("Native simulation clock advanced during acquisition freeze")
                frozen_state = client.getMultirotorState(vehicle_name=connection["vehicle_name"])
                requests = [airsim.ImageRequest(connection["camera_name"], kind, False, True) for kind in (0, 12)]
                # Cosys legacy endpoints: exactly 2 arguments, no external flag.
                raw = client.client.call("simGetImages", requests, connection["vehicle_name"])
                responses = [airsim.ImageResponse.from_msgpack(value) for value in raw]
                frozen_sim_s = (clock_before.get("simulation_time_s", clock_before.get("unpaused_simulation_seconds"))
                                if clock_before else None)
                result = (True, (responses, frozen_state, frozen_sim_s))
            except Exception as error:
                result = (False, error)
            finally:
                if previous_pause is not None:
                    try:
                        client.simPause(previous_pause)
                        if bool(client.simIsPause()) != previous_pause:
                            raise MissionError("Previous pause state was not restored")
                    except Exception as error:
                        result = (False, MissionError("Failed to restore acquisition pause state: " + str(error)))
            self.results.put(result)


def quantiles(values):
    if not values:
        return {"count": 0, "method": "nearest rank", "p50": None, "p95": None, "max": None}
    values = sorted(values)
    return {"count": len(values), "method": "nearest rank", "p50": values[max(0, math.ceil(.5*len(values))-1)],
            "p95": values[max(0, math.ceil(.95*len(values))-1)], "max": values[-1]}


class MissionRunner:
    """Public API for editor/demo launchers. run() flies; preflight() never arms."""
    def __init__(self, mission, run_dir, context, client=None, clock=None):
        self.authored, mission, self.warnings = load_mission(mission)
        self.mission, self.context = resolve_context(mission, context)
        self.run_dir = Path(run_dir).resolve()
        self.client = client
        self.clock = clock
        self.writer = self.capture_worker = None
        self.vehicle = mission["connection"]["vehicle_name"]
        self.started_wall = time.monotonic()
        self.created_utc = datetime.now(timezone.utc).isoformat()
        self.sim_start = self.previous_sim = None
        self.sim_s = self.active_s = 0.
        self.paused = self.acquiring = False
        self.native_paused = False
        self._paused_wall_total_s = 0.
        self._pause_started_wall = None
        self.status_state = "initializing"
        self.command_id = None
        self.last_status_wall = self.last_telemetry_sim = -math.inf
        self.state = self.telemetry = None
        self.last_aim_q = self.mount_q = None
        self.mount_position = None
        self.last_aim_active = 0.
        self.target_node = self.segment_id = None
        self.target_speed = self.command_speed = 0.
        self.total_nodes = len(mission["nodes"])
        self.nodes_completed = self.committed = self.issued = self.total_bytes = 0
        self.bad_pairs = self.missed_consecutive = 0
        self.stats = {"attempted": 0, "rejected": 0, "skipped": 0, "eligible_travel_deadlines": 0,
                      "valid_travel_pairs": 0, "collisions": 0}
        self.pair_records, self.segment_records, self.node_records = [], [], []
        self.recovery = None
        self.api_owned = False
        self.original_pause = None
        self.collision_baseline = None
        self._collision_baseline_identity = None
        self._landing_active = False
        self._landing_authorization = None
        self._landing_contact_deadline = None
        self._landing_contact_record = None
        self._landing_deadline = None
        self._latest_collision = None
        self._motor_stable_since = self._motor_stable_sim = None
        self._motor_started = False
        self._motor_deadline = self._motor_next_command_sim = None
        self._motor_original_client = None
        self.motor_settle_report = None
        self._motor_rotor_results = queue.Queue(maxsize=2)
        self.touchdown = None
        self.last_capture_start = None
        self._prepared = False

    def prepare(self):
        if self._prepared:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if any((self.run_dir / name).exists() for name in ("mission.json", "pairs", "summary.json")):
            raise MissionError("Run directory already contains a mission; choose a new run directory")
        atomic_json(self.run_dir / "mission.json", self.authored)
        atomic_json(self.run_dir / "resolved_mission.json", self.mission)
        self.configuration_hash = hashlib.sha256(canonical(self.mission)).hexdigest()
        atomic_json(self.run_dir / "configuration.json", {"sha256": self.configuration_hash,
                    "created_utc": self.created_utc, "clock_config": self.context.get("clock_config"),
                    "warnings": self.warnings})
        self._prepared = True
        self.event("run_created", configuration_sha256=self.configuration_hash)
        self.status(force=True)

    def event(self, kind, **fields):
        value = {"event": kind, "utc": datetime.now(timezone.utc).isoformat(),
                 "wall_elapsed_s": time.monotonic()-self.started_wall, "simulation_elapsed_s": self.sim_s,
                 "active_elapsed_s": self.active_s, **fields}
        with (self.run_dir / "events.jsonl").open("ab") as stream:
            stream.write(canonical(value) + b"\n")

    def status(self, force=False, reason=None):
        now = time.monotonic()
        if force or now-self.last_status_wall >= .25:
            atomic_json(self.run_dir / "status.json", {"schema_version": "1.0.0",
                "state": self.status_state, "reason": reason, "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
                "heartbeat_wall_elapsed_s": now-self.started_wall, "simulation_elapsed_s": self.sim_s,
                "active_elapsed_s": self.active_s, "node_id": self.target_node, "segment_id": self.segment_id,
                "nodes_completed": self.nodes_completed, "nodes_total": self.total_nodes,
                "pairs": self.committed, "images": self.committed*2, "bytes": self.total_bytes,
                "actual_pairs_per_sim_s": self.committed/self.sim_s if self.sim_s > 0 else None,
                "target_speed_mps": self.target_speed, "actual_speed_mps": (self.telemetry or {}).get("speed_mps"),
                "pending_writes": self.writer.pending if self.writer else 0,
                "last_control_id": self.command_id, **self.stats})
            self.last_status_wall = now

    def _clock(self):
        seconds, paused = self.clock.read()
        self.native_paused = paused
        if self.sim_start is None:
            self.sim_start = self.previous_sim = seconds
        delta = seconds-self.previous_sim
        self.previous_sim = seconds
        self.sim_s = seconds-self.sim_start
        # The native clock itself is flat during the actual acquisition freeze.
        # Pre/post-pause RPC handshake steps are real simulation time and remain
        # eligible for interval deadlines even while an acquisition is in flight.
        if not self.paused:
            self.active_s += max(0., delta)
        return paused

    def _paused_wall_at(self, now=None):
        now = time.monotonic() if now is None else now
        return self._paused_wall_total_s + (max(0., now-self._pause_started_wall)
            if self._pause_started_wall is not None else 0.)

    def _phase_wall_metrics(self, started_wall, paused_wall_at_start, now=None):
        now = time.monotonic() if now is None else now
        raw = max(0., now-started_wall)
        pause = max(0., self._paused_wall_at(now)-paused_wall_at_start)
        return {"wall_duration_s": max(0., raw-pause), "wall_duration_including_operator_pauses_s": raw,
                "operator_pause_wall_s": pause}

    def _collect(self):
        if not self.writer:
            return
        while True:
            try:
                ok, value = self.writer.results.get_nowait()
            except queue.Empty:
                return
            self.writer.release()
            if not ok:
                raise MissionError("Pair write failed: " + value)
            self.committed += 1
            index_error = value.pop("_index_error", None)
            self.total_bytes += sum(image["bytes"] for image in value["images"].values())
            self.pair_records.append(value)
            if value["trigger"]["kind"] == "travel":
                self.stats["valid_travel_pairs"] += 1
            self.event("pair_committed", pair_id=value["pair_id"], trigger=value["trigger"], pairs=self.committed)
            if index_error:
                raise MissionError("Pair committed but JSONL index write failed: " + index_error)

    def _command(self):
        path = self.run_dir / "control.json"
        if not path.exists():
            return
        try:
            control = read_json(path)
        except (ValueError, OSError, MissionError):
            return  # A launcher must replace atomically; a transient partial file is not a command.
        identifier, command = control.get("id"), control.get("command")
        if identifier is None or identifier == self.command_id:
            return
        self.command_id = identifier
        self.event("control", control_id=identifier, command=command)
        if command == "pause" and not self.paused:
            pause_started = time.monotonic()
            self.client.cancelLastTask(vehicle_name=self.vehicle)
            self.client.hoverAsync(vehicle_name=self.vehicle)
            self._pause_started_wall = pause_started
            self.paused, self.status_state = True, "paused"
        elif command == "resume" and self.paused:
            self._paused_wall_total_s = self._paused_wall_at()
            self._pause_started_wall = None
            self.paused, self.status_state = False, "running"
        elif command == "stop":
            raise MissionStopped("Stop requested")
        elif command == "land":
            raise MissionStopped("Land requested")
        elif command not in ("pause", "resume"):
            self.event("control_rejected", command=command, reason="Unknown command")
        self.status(force=True)

    def _sample(self, force=False):
        self.state = self.client.getMultirotorState(vehicle_name=self.vehicle)
        kinematics = self.state.kinematics_estimated
        position, velocity, orientation = vec(kinematics.position), vec(kinematics.linear_velocity), quat(kinematics.orientation)
        angular = vec(kinematics.angular_velocity)
        _finite(position + velocity + orientation + angular)
        self.telemetry = {"simulation_elapsed_s": self.sim_s, "active_elapsed_s": self.active_s,
            "wall_elapsed_s": time.monotonic()-self.started_wall,
            "source_timestamp_ns": str(self.state.timestamp), "position_ned_m": xyz(position),
            "orientation_xyzw": qdict(orientation), "velocity_ned_mps": xyz(velocity),
            "speed_mps": norm(velocity), "target_speed_mps": self.target_speed,
            "landed_state": int(self.state.landed_state),
            "angular_velocity_rad_s": xyz(angular),
            "node_id": self.target_node, "segment_id": self.segment_id}
        collision = self.client.simGetCollisionInfo(vehicle_name=self.vehicle)
        collision_record = {"has_collided": bool(collision.has_collided),
            "object_name": collision.object_name, "object_id": collision.object_id,
            "source_timestamp_ns": str(collision.time_stamp),
            "impact_point_ned_m": xyz(vec(collision.impact_point)),
            "normal_ned": xyz(vec(collision.normal)),
            "position_ned_m": xyz(vec(collision.position)),
            "penetration_depth_m": float(collision.penetration_depth)}
        identity = (str(collision.time_stamp), collision.object_name, collision.object_id,
                    vec(collision.impact_point), vec(collision.position), float(collision.penetration_depth))
        baseline_contact = False
        if collision.has_collided:
            # AirSim latches the last collision, including ordinary spawn/floor
            # contact. Only stationary landed preflight may establish that
            # baseline. Once API control is acquired it is immutable, and every
            # different event (even on the same floor actor) remains fatal.
            grounded_preflight = (not self.api_owned and self.state.landed_state == 0 and
                norm(velocity) <= self.mission["defaults"]["node"]["max_settled_speed_mps"])
            same_ground = (self.collision_baseline is None or
                (collision.object_name, collision.object_id) ==
                (self.collision_baseline["object_name"], self.collision_baseline["object_id"]))
            if grounded_preflight and same_ground:
                if identity != self._collision_baseline_identity:
                    self.collision_baseline = copy.deepcopy(collision_record)
                    self._collision_baseline_identity = identity
                    self.event("grounded_collision_baseline", collision=collision_record)
                baseline_contact = True
            else:
                baseline_contact = identity == self._collision_baseline_identity
        expected_touchdown = (collision.has_collided and not baseline_contact and
                              self._expected_touchdown(collision_record))
        confirmed_touchdown = expected_touchdown and self.state.landed_state == 0
        collision_record["classification"] = ("verified_landing_touchdown" if confirmed_touchdown else
                                               "authorized_ground_contact_pending_landed" if expected_touchdown else
                                               "historical_grounded_baseline" if baseline_contact else
                                               "new_collision" if collision.has_collided else "none")
        if confirmed_touchdown and self.touchdown is None:
            self.touchdown = copy.deepcopy(collision_record)
            self.event("landing_touchdown", collision=self.touchdown)
        elif expected_touchdown and not confirmed_touchdown and self._landing_contact_record is None:
            self._landing_contact_record = copy.deepcopy(collision_record)
            self.event("landing_ground_contact_pending", collision=self._landing_contact_record,
                       landing_watchdog_wall_s=self._landing_timeout_s,
                       landed_confirmation_remaining_wall_s=max(0., self._landing_contact_deadline-time.monotonic()))
        self.telemetry["collision"] = collision_record
        self._latest_collision = copy.deepcopy(collision_record)
        period = self.mission["metrics"]["telemetry_interval_ms"] / 1000
        if force or collision.has_collided or self.sim_s-self.last_telemetry_sim >= period:
            with (self.run_dir / "telemetry.jsonl").open("ab") as stream:
                stream.write(canonical(self.telemetry) + b"\n")
            self.last_telemetry_sim = self.sim_s
        if collision.has_collided and not baseline_contact and not expected_touchdown:
            self.stats["collisions"] += 1
            raise MissionError("Collision reported by simulator: " + str(collision.object_name))
        return position

    def tick(self, force_sample=False, allow_commands=True):
        self._clock()
        self._collect()
        if time.monotonic()-self.started_wall > self.mission["limits"]["max_duration_wall_s"]:
            raise MissionLimit("Maximum wall duration reached")
        if shutil.disk_usage(self.run_dir).free / 1_000_000 < self.mission["limits"]["min_free_disk_mb"]:
            raise MissionLimit("Minimum free disk limit reached")
        if allow_commands:
            self._command()
        if self.acquiring:
            self.status()
            return vec(self.state.kinematics_estimated.position) if self.state else None
        position = self._sample(force_sample)
        self.status()
        return position

    def _pause_wait(self, deadline=None, label="Operation"):
        was_paused = self.paused
        while self.paused:
            self.tick()
            if deadline is not None:
                self._operation_deadline(deadline, label)
            time.sleep(.03)
        return was_paused

    def _aim(self, desired):
        import airsim
        body = quat(self.state.kinematics_estimated.orientation)
        elapsed = max(0., self.active_s-self.last_aim_active)
        self.last_aim_active = self.active_s
        if self.last_aim_q is None:
            self.last_aim_q = qmul(body, self.mount_q)
        angle = qangle(self.last_aim_q, desired)
        maximum = self.mission["camera"]["aim"]["max_rate_deg_s"]*elapsed
        self.last_aim_q = slerp(self.last_aim_q, desired, min(1., maximum/angle) if angle > 1e-8 else 1.)
        relative = qmul(qinverse(body), self.last_aim_q)
        camera_pose = airsim.Pose(airsim.Vector3r(*self.mount_position), airsim.Quaternionr(*relative))
        # Exactly three arguments: camera, relative pose, selected vehicle.
        self.client.client.call("simSetCameraPose", self.mission["connection"]["camera_name"], camera_pose, self.vehicle)

    def _desired_aim(self, node, previous=None, fraction=1.):
        aim = self.mission["camera"]["aim"]
        if aim["mode"] == "fixed_body_rotation":
            return qmul(quat(self.state.kinematics_estimated.orientation), euler_quat(aim["rotation_deg"]))
        target = euler_quat(node["camera_rotation_deg"])
        return slerp(euler_quat(previous["camera_rotation_deg"]), target, fraction) if previous else target

    def _request_pair(self):
        if self.capture_worker is None:
            self.capture_worker = CaptureWorker(self.mission)
        started = time.monotonic()
        self.acquiring = True
        self.capture_worker.requests.put_nowait({"verify_freeze": not hasattr(self, "_freeze_verified")})
        try:
            deadline = started + self.mission["acquisition"]["capture_timeout_ms"] / 1000
            while True:
                try:
                    ok, value = self.capture_worker.results.get(timeout=.03)
                    break
                except queue.Empty:
                    self.tick(allow_commands=False)
                    if time.monotonic() >= deadline:
                        raise MissionError("Capture watchdog expired; independent supervisor must recover a blocked RPC")
            if not ok:
                raise MissionError("Capture RPC failed: " + str(value)) from value
            if time.monotonic() > deadline:
                raise MissionError("Capture watchdog expired")
            self._freeze_verified = True
            responses, frozen_state, frozen_sim_s = value
            self.frozen_simulation_absolute_s = frozen_sim_s
            kinematics = frozen_state.kinematics_estimated
            self.frozen_telemetry = {"simulation_elapsed_s": frozen_sim_s-self.sim_start if frozen_sim_s is not None else None,
                "active_elapsed_s": self.active_s,
                "source_timestamp_ns": str(frozen_state.timestamp), "position_ned_m": xyz(vec(kinematics.position)),
                "orientation_xyzw": qdict(quat(kinematics.orientation)),
                "velocity_ned_mps": xyz(vec(kinematics.linear_velocity)),
                "speed_mps": norm(vec(kinematics.linear_velocity)), "target_speed_mps": self.target_speed,
                "node_id": self.target_node, "segment_id": self.segment_id,
                "measurement": "getMultirotorState while acquisition freeze acknowledged"}
            return responses, time.monotonic()-started
        finally:
            # Collect actual native clock steps through both RPC handshakes;
            # the native clock already excludes the frozen portion itself.
            try:
                self._clock()
            finally:
                self.acquiring = False

    def _missed(self, deadlines, reason):
        if not deadlines:
            return
        self.stats["skipped"] += len(deadlines)
        self.missed_consecutive += len(deadlines)
        self.event("travel_deadlines_skipped", segment_id=self.segment_id, deadlines=deadlines, reason=reason)
        acquisition = self.mission["acquisition"]
        if (acquisition["on_interval_overload"] == "stop_mission" or
                self.missed_consecutive >= acquisition["abort_after_consecutive_missed_triggers"]):
            raise MissionError("Consecutive missed travel trigger limit reached: " + reason)

    def capture(self, trigger, mandatory=False, deadline=None):
        self.tick(force_sample=True)
        self._pause_wait(deadline, "Capture operation")
        if deadline is not None:
            self._operation_deadline(deadline, "Capture operation")
        if self.committed + self.writer.pending >= self.mission["limits"]["max_pairs"]:
            self.flush(deadline)
            raise MissionLimit("Maximum committed pair limit reached before mandatory route work finished")
        if not self.writer.reserve():
            if mandatory:
                while not self.writer.reserve():
                    self.tick()
                    self._pause_wait(deadline, "Node write capacity")
                    if deadline is not None:
                        self._operation_deadline(deadline, "Node write capacity")
                    time.sleep(.02)
            else:
                self._missed([trigger["scheduled"]], "write_capacity")
                return False
        if not mandatory:
            self.missed_consecutive = 0
        submitted = False
        started_wall, started_sim, started_active = time.monotonic(), self.sim_s, self.active_s
        self.stats["attempted"] += 1
        try:
            responses, latency = self._request_pair()
            images, metadata, quality = validate_pair(responses, self.mission)
            self.bad_pairs = 0
            self.issued += 1
            sequence = self.issued
            for label in metadata:
                metadata[label]["path"] = f"pairs/{sequence:06d}/{label}.png"
            spacing = None if self.last_capture_start is None else started_sim-self.last_capture_start
            self.last_capture_start = started_sim
            record = {"schema_version": "1.0.0", "pair_id": f"{sequence:06d}", "trigger": trigger,
                "simulation_elapsed_s": started_sim, "active_elapsed_s": started_active,
                "request_start_simulation_elapsed_s": started_sim,
                "acquisition_frozen_simulation_elapsed_s": (self.frozen_simulation_absolute_s-self.sim_start
                    if getattr(self, "frozen_simulation_absolute_s", None) is not None else None),
                "thermal_elapsed_simulation_s": getattr(self, "frozen_simulation_absolute_s", None),
                "thermal_elapsed_reference": "native unpaused world time; pre-existing thermal state is preserved",
                "wall_elapsed_s": started_wall-self.started_wall, "images": metadata,
                "telemetry": copy.deepcopy(self.frozen_telemetry), "quality": quality,
                "acquisition_policy": "freeze_simulation", "backend": "legacy_simGetImages_2_args",
                "acquisition_latency_wall_s": latency, "encoding_latency_wall_s": None,
                "encoding_note": "Simulator PNG encoding is included in acquisition RPC; separate latency unavailable",
                "actual_pair_spacing_sim_s": spacing,
                "schedule_lateness": (trigger.get("actual", 0)-trigger.get("scheduled", 0)),
                "_capture_started_wall": started_wall}
            self.writer.submit(sequence, images, record)
            submitted = True
            if mandatory:
                self.flush(deadline)
            return started_active
        except BadPair as error:
            self.bad_pairs += 1
            self.stats["rejected"] += 1
            self.event("pair_rejected", trigger=trigger, reason=str(error), consecutive_bad_pairs=self.bad_pairs)
            if self.bad_pairs >= self.mission["acquisition"]["abort_after_consecutive_bad_pairs"]:
                raise MissionError("Consecutive bad pair limit reached") from error
            return False
        finally:
            if not submitted:
                self.writer.release()

    def flush(self, deadline=None):
        while self.writer and self.writer.pending:
            self.tick()
            if deadline is not None:
                self._operation_deadline(deadline, "Pair commit")
            time.sleep(.01)

    def _check_context(self):
        context, mission = self.context, self.mission
        if context.get("map_asset") != mission["map_asset"]:
            raise MissionError("Loaded map does not match mission map_asset")
        if context.get("sim_mode") != "Multirotor":
            raise MissionError("Selected simulation must be Multirotor")
        profile = context.get("active_profile", {})
        for key in ("width_px", "height_px", "horizontal_fov_deg", "projection"):
            if profile.get("camera", {}).get(key) != mission["camera"][key]:
                raise MissionError("Active camera profile mismatch: " + key)
        if profile.get("thermal", {}).get("display_window_k") != mission["thermal"]["display_window_k"]:
            raise MissionError("Active thermal display window mismatch")
        safety = context.get("path_validation", {})
        if safety.get("clear") is not True or safety.get("clearance_m", 0) < mission["limits"]["obstacle_clearance_m"]:
            raise MissionError("Native clearance sweeps must validate takeoff, entry and route before arming")
        if context.get("world_origin_valid") is False:
            raise MissionError("World origin rebasing is unsupported")

    def preflight(self):
        import airsim
        self.prepare()
        self.status_state = "preflight"
        self.status(force=True)
        self._check_context()
        self.clock = self.clock or NativeClock(self.context)
        self.client = self.client or airsim_client(self.mission["connection"])
        if not self.client.ping():
            raise MissionError("AirSim RPC did not respond")
        self.original_pause = bool(self.client.simIsPause())
        if self.original_pause:
            raise MissionError("Simulation is paused; resume it before preflight")
        self._clock()
        self._sample(force=True)
        # WorldSimApi cameraInfo and image responses use vehicle-spawn local NED.
        # Convert its actual world pose to a body-relative mount before changing aim.
        raw = self.client.client.call("simGetCameraInfo", self.mission["connection"]["camera_name"], self.vehicle)
        info = airsim.CameraInfo.from_msgpack(raw)
        if abs(info.fov-self.mission["camera"]["horizontal_fov_deg"]) > .05:
            raise MissionError("Live camera FOV mismatch")
        body = quat(self.state.kinematics_estimated.orientation)
        self.mount_position = qrotate(qinverse(body), sub(vec(info.pose.position),
                                    vec(self.state.kinematics_estimated.position)))
        self.mount_q = qmul(qinverse(body), quat(info.pose.orientation))
        responses, latency = self._request_pair()
        validate_pair(responses, self.mission)
        # Frozen telemetry and response pose share the stable scene. Derive the
        # mount here rather than combining two unpaused sequential RPC samples.
        frozen_body = quat(self.frozen_telemetry["orientation_xyzw"])
        self.mount_position = qrotate(qinverse(frozen_body), sub(vec(responses[0].camera_position),
                                    vec(self.frozen_telemetry["position_ned_m"])))
        self.mount_q = qmul(qinverse(frozen_body), quat(responses[0].camera_orientation))
        before = self.previous_sim
        wall = time.monotonic()
        time.sleep(.2)
        self._clock()
        rate = (self.previous_sim-before)/(time.monotonic()-wall)
        if rate <= 0:
            raise MissionError("Native clock does not advance while simulation is unpaused")
        for index, node in enumerate(self.mission["nodes"]):
            settings, capture = node["settings"], node["settings"]["capture"]
            seconds = (settings["settle_time_ms"]+settings["extra_hold_ms"]+capture.get("delay_ms", 0) +
                       (capture.get("count", 1)-1)*capture.get("interval_ms", 0))/1000
            watchdog = (self.mission["segments"][index-1]["settings"]["timeout_s"] if index
                        else self.mission["flight"]["entry_leg"]["timeout_s"])
            if seconds/rate + latency*(capture.get("count", 1) if capture["mode"] != "off" else 0) >= watchdog:
                raise MissionError("Measured simulation rate/capture latency make node watchdog infeasible: " + node["id"])
        result = {"passed": True, "measured_simulation_rate": rate,
            "probe_acquisition_latency_wall_s": latency, "camera_mount_position_ned_m": xyz(self.mount_position),
            "camera_mount_orientation_xyzw": qdict(self.mount_q), "context": self.context,
            "pair_frame_sync_proven": False}
        atomic_json(self.run_dir / "preflight.json", result)
        self.event("preflight_passed", measured_simulation_rate=rate)
        return result

    def _operation_deadline(self, deadline, label):
        if time.monotonic() > deadline:
            raise MissionError(label + " wall watchdog expired")

    def _wait_active(self, seconds, deadline, node=None):
        target = self.active_s + seconds
        while self.active_s < target:
            self.tick()
            self._operation_deadline(deadline, "Node/operation")
            self._pause_wait(deadline, "Node/operation")
            if node:
                self._hold_position(node)
                self._aim(self._desired_aim(node))
            time.sleep(.02)

    def _travel(self, target, settings, previous=None, segment=None):
        self.target_node, self.segment_id = target["id"], segment["id"] if segment else None
        self.target_speed = settings["speed_mps"]
        self.missed_consecutive = 0
        destination = vec(target["position_ned_m"])
        start = vec(previous["position_ned_m"]) if previous else vec(self.state.kinematics_estimated.position)
        last_position = vec(self.state.kinematics_estimated.position)
        initial_active, initial_sim, initial_wall = self.active_s, self.sim_s, time.monotonic()
        initial_paused_wall = self._paused_wall_at(initial_wall)
        last_active, over_error_s = self.active_s, 0.
        distance, speeds, errors = 0., [], []
        speed_sum = error_square_sum = maximum_speed = maximum_error = 0.
        initial_stats = dict(self.stats)
        capture_settings = settings.get("capture", {"mode": "off"})
        schedule = IntervalSchedule(capture_settings)
        stopping = target["settings"]["behavior"] == "stop"
        deadline = time.monotonic()+settings["timeout_s"]
        self.event("segment_started" if segment else "entry_started", node_id=target["id"], segment_id=self.segment_id)
        self.current_segment_metrics = None
        while True:
            position = self.tick()
            self._operation_deadline(deadline, "Segment/entry")
            resumed = self._pause_wait(deadline, "Segment/entry")
            if resumed:
                position = vec(self.state.kinematics_estimated.position)
                last_position, last_active = position, self.active_s
                self.command_speed = 0.
            elapsed = max(0., self.active_s-last_active)
            last_active = self.active_s
            step = norm(sub(position, last_position))
            last_position = position
            distance += step
            remaining = norm(sub(destination, position))
            error, fraction = route_error(position, start, destination)
            speeds.append(self.telemetry["speed_mps"])
            errors.append(error)
            speed_sum += speeds[-1]
            error_square_sum += error*error
            maximum_speed, maximum_error = max(maximum_speed, speeds[-1]), max(maximum_error, error)
            if segment:
                self.current_segment_metrics = {"id": segment["id"], "settings": settings, "completed": False,
                    "active_duration_sim_s": self.active_s-initial_active,
                    "simulation_duration_including_freezes_s": self.sim_s-initial_sim,
                    **self._phase_wall_metrics(initial_wall, initial_paused_wall), "travelled_m": distance,
                    "actual_speed_mps": {"mean": speed_sum/len(speeds), "max": maximum_speed},
                    "_speed_samples": speeds,
                    "cross_track_error_m": {"max": maximum_error, "rms": math.sqrt(error_square_sum/len(errors))},
                    "skipped": self.stats["skipped"]-initial_stats["skipped"],
                    "rejected": self.stats["rejected"]-initial_stats["rejected"],
                    "eligible_travel_deadlines": self.stats["eligible_travel_deadlines"]-initial_stats["eligible_travel_deadlines"]}
            over_error_s = over_error_s+elapsed if error > self.mission["limits"]["max_cross_track_error_m"] else 0.
            if error > self.mission["limits"]["max_cross_track_error_m"] and over_error_s*1000 >= self.mission["limits"]["cross_track_grace_ms"]:
                raise MissionError("Cross-track error exceeded limit/grace")
            arrived = remaining <= target["settings"]["arrival_radius_m"]
            self._aim(self._desired_aim(target, previous, fraction))
            if arrived:
                break  # Endpoint deadlines are excluded before asking the scheduler.
            scheduled, skipped = schedule.due(self.active_s-initial_active, distance)
            self.stats["eligible_travel_deadlines"] += len(skipped)+(scheduled is not None)
            self._missed(skipped, "telemetry_or_capture_lateness")
            if scheduled is not None:
                actual = self.active_s-initial_active if schedule.mode == "time_interval" else distance
                self.capture({"kind": "travel", "segment_id": self.segment_id, "mode": schedule.mode,
                              "scheduled": scheduled, "actual": actual,
                              "units": "s" if schedule.mode == "time_interval" else "m",
                              "requested_period": schedule.period}, deadline=deadline)
            acceleration, deceleration = settings.get("acceleration_mps2", 1.), settings.get("deceleration_mps2", 1.)
            requested = min(settings["speed_mps"], self.command_speed+acceleration*elapsed)
            if stopping:
                requested = min(requested, math.sqrt(2*deceleration*max(0., remaining)))
            self.command_speed = max(.05, requested)
            velocity = tuple(value/remaining*self.command_speed for value in sub(destination, position))
            self.client.moveByVelocityAsync(*velocity, .3, vehicle_name=self.vehicle)
            time.sleep(.025)
        if stopping:
            self.client.cancelLastTask(vehicle_name=self.vehicle)
            self.client.hoverAsync(vehicle_name=self.vehicle)
            self.command_speed = 0.
        self._sample(force=True)
        if segment:
            active_duration = self.active_s-initial_active
            record = {"id": segment["id"], "settings": settings, "completed": True, "active_duration_sim_s": active_duration,
                "simulation_duration_including_freezes_s": self.sim_s-initial_sim,
                **self._phase_wall_metrics(initial_wall, initial_paused_wall), "travelled_m": distance,
                "actual_speed_mps": {"mean": statistics.mean(speeds), **quantiles(speeds)},
                "cross_track_error_m": {"max": max(errors), "rms": math.sqrt(statistics.mean(x*x for x in errors))},
                "periodic_pairs": None,
                "skipped": self.stats["skipped"]-initial_stats["skipped"],
                "rejected": self.stats["rejected"]-initial_stats["rejected"],
                "eligible_travel_deadlines": self.stats["eligible_travel_deadlines"]-initial_stats["eligible_travel_deadlines"]}
            self.segment_records.append(record)
            self.current_segment_metrics = None
        self.event("node_arrived", node_id=target["id"], position_error_m=remaining)

    def _hold_position(self, node):
        """Reacquire the authored stop after braking drift using flight control."""
        settings = node["settings"]
        delta = sub(vec(node["position_ned_m"]), vec(self.state.kinematics_estimated.position))
        velocity = vec(self.state.kinematics_estimated.linear_velocity)
        if norm(delta) <= settings["arrival_radius_m"]*.25 and norm(velocity) <= settings["max_settled_speed_mps"]*.5:
            if not getattr(self, "_node_hovering", False):
                self.client.cancelLastTask(vehicle_name=self.vehicle)
                self.client.hoverAsync(vehicle_name=self.vehicle)
                self._node_hovering = True
            return
        self._node_hovering = False
        desired = tuple(.8*x-.5*v for x, v in zip(delta, velocity))
        speed = norm(desired)
        maximum = min(.75, self.mission["flight"]["entry_leg"]["speed_mps"])
        if speed > maximum:
            desired = tuple(x*maximum/speed for x in desired)
        self.client.moveByVelocityAsync(*desired, .3, vehicle_name=self.vehicle)

    def _settle_node(self, node, deadline, already_settled=False):
        settings = node["settings"]
        settled_since = None
        required = 0. if already_settled else settings["settle_time_ms"]/1000
        while True:
            position = self.tick()
            self._operation_deadline(deadline, "Node")
            if self._pause_wait(deadline, "Node"):
                settled_since = None
                required = settings["settle_time_ms"]/1000
                position = vec(self.state.kinematics_estimated.position)
            self._hold_position(node)
            desired = self._desired_aim(node)
            self._aim(desired)
            position_error = norm(sub(position, vec(node["position_ned_m"])))
            # Verify actual camera response pose, rather than treating a commanded aim as attained.
            import airsim
            raw = self.client.client.call("simGetCameraInfo", self.mission["connection"]["camera_name"], self.vehicle)
            camera = airsim.CameraInfo.from_msgpack(raw)
            actual_world = quat(camera.pose.orientation)
            aim_error = qangle(actual_world, desired)
            acceptable = (position_error <= settings["arrival_radius_m"] and
                          self.telemetry["speed_mps"] <= settings["max_settled_speed_mps"] and
                          aim_error <= settings["aim_tolerance_deg"])
            if acceptable:
                settled_since = self.active_s if settled_since is None else settled_since
                if self.active_s-settled_since >= required:
                    return position_error, aim_error
            else:
                settled_since = None
                required = settings["settle_time_ms"]/1000
            time.sleep(.025)

    def _node(self, node, timeout):
        settings, capture = node["settings"], node["settings"]["capture"]
        if settings["behavior"] == "fly_through":
            self.nodes_completed += 1
            self.event("node_passed", node_id=node["id"])
            return
        self.segment_id, self.target_speed = None, 0.
        self._node_hovering = False
        deadline = time.monotonic()+timeout
        start, retries = self.active_s, 0
        self.event("node_settling", node_id=node["id"])
        position_error, aim_error = self._settle_node(node, deadline)
        settling = self.active_s-start
        self._sample(force=True)
        self.event("node_settled", node_id=node["id"], position_error_m=position_error, aim_error_deg=aim_error)
        expected = capture.get("count", 1) if capture["mode"] != "off" else 0
        self._wait_active(capture.get("delay_ms", 0)/1000, deadline, node)
        successful_starts = []
        for index in range(expected):
            if successful_starts:
                remaining = successful_starts[-1]+capture["interval_ms"]/1000-self.active_s
                self._wait_active(max(0., remaining), deadline, node)
            while True:
                self._operation_deadline(deadline, "Node")
                self._pause_wait(deadline, "Node capture")
                self._settle_node(node, deadline, already_settled=True)
                successful = self.capture({"kind": "node", "node_id": node["id"], "sample_index": index,
                    "mode": capture["mode"], "scheduled": self.active_s, "actual": self.active_s,
                    "units": "active_sim_s", "requested_spacing_ms": capture.get("interval_ms")}, mandatory=True, deadline=deadline)
                if successful is not False:
                    successful_starts.append(successful)
                    self._operation_deadline(deadline, "Node")
                    break
                retries += 1
                self._wait_active(.02, deadline, node)
        self._wait_active(settings["extra_hold_ms"]/1000, deadline, node)
        self._operation_deadline(deadline, "Node")
        self.nodes_completed += 1
        self.node_records.append({"id": node["id"], "position_error_m": position_error, "aim_error_deg": aim_error,
            "settling_duration_sim_s": settling, "total_duration_active_sim_s": self.active_s-start,
            "mandatory_expected": expected, "mandatory_committed": len(successful_starts), "retries": retries,
            "successful_starts_active_sim_s": successful_starts,
            "actual_burst_spacing_sim_s": [b-a for a, b in zip(successful_starts, successful_starts[1:])],
            "requested_burst_spacing_ms": capture.get("interval_ms")})
        self.event("node_completed", node_id=node["id"], nodes_completed=self.nodes_completed)

    def _read_landing_validation(self):
        # Bridge may refresh a separate dynamic clearance document for an explicit land command.
        source = self.context.get("landing_validation_path")
        clock_source = self.context.get("sim_clock_path", self.context.get("sim_clock_file"))
        if source:
            _, landing = read_clock_snapshot(source, max_age_s=3., label="Landing clearance clock")
        elif clock_source:
            _, snapshot = read_clock_snapshot(clock_source, max_age_s=3., label="Landing clearance clock")
            landing = snapshot.get("landing_validation", {})
        else:
            landing = self.context.get("landing_validation", {})
        if not landing and self.nodes_completed == self.total_nodes:
            landing = self.context.get("path_validation", {}).get("landing", {})
        return landing

    def _ground_ned(self, landing):
        if "ground_position_ned_m" in landing:
            return vec(landing["ground_position_ned_m"])
        delta = sub(vec(landing["ground_position_ue_cm"]), vec(self.context["vehicle_origin_ue_cm"]))
        scale = self.context["world_to_meters"]
        return (delta[0]/scale, delta[1]/scale, -delta[2]/scale)

    def _landing_clear(self):
        landing = self._read_landing_validation()
        position = vec(self.state.kinematics_estimated.position)
        if (landing.get("clear") is not True or
                landing.get("clearance_m", 0) < self.mission["limits"]["obstacle_clearance_m"] or
                "position_ned_m" not in landing or
                norm(sub(position, vec(landing["position_ned_m"]))) > landing.get("tolerance_m", .5)):
            raise MissionError("Landing requires a current native clearance-validated local descent")
        if not landing.get("ground_actor_name", landing.get("ground_object_name")):
            raise MissionError("Landing requires the native validated ground actor identity")
        try:
            ground = self._ground_ned(landing)
            _finite(ground)
        except (KeyError, TypeError, ValueError) as error:
            raise MissionError("Landing requires the native validated ground position") from error
        self._landing_authorization = {"validation": copy.deepcopy(landing), "ground_ned_m": ground,
                                       "checked_wall": time.monotonic()}

    def _near_landing_ground(self, require_landed=True):
        if not self._landing_authorization:
            return False
        landing = self._landing_authorization["validation"]
        ground = self._landing_authorization["ground_ned_m"]
        position = vec(self.state.kinematics_estimated.position)
        horizontal = norm(sub(position[:2], ground[:2]))
        height = ground[2]-position[2]
        return (horizontal <= landing.get("tolerance_m", .5) and
                -.15 <= height <= landing["clearance_m"]+.25 and
                (not require_landed or self.state.landed_state == 0) and
                norm(vec(self.state.kinematics_estimated.linear_velocity)) <=
                max(.3, self.mission["defaults"]["node"]["max_settled_speed_mps"]))

    def _expected_touchdown(self, collision):
        if not self._landing_active or not self._near_landing_ground(require_landed=False):
            return False
        authorization = self._landing_authorization
        landing, ground = authorization["validation"], authorization["ground_ned_m"]
        try:
            # The descent was authorized while clear. At contact, a sphere
            # sweep may overlap the floor, so clear=false alone is not a new
            # authorization. Require fresh native geometry to agree with the
            # previously validated landing surface instead.
            latest = self._read_landing_validation()
            if norm(sub(self._ground_ned(latest), ground)) > .2:
                return False
        except (MissionError, OSError, ValueError, KeyError, TypeError):
            return False
        expected_object = landing.get("ground_actor_name", landing.get("ground_object_name"))
        latest_object = latest.get("ground_actor_name", latest.get("ground_object_name"))
        if not expected_object or latest_object != expected_object or collision["object_name"] != expected_object:
            return False
        normal = vec(collision["normal_ned"])
        if norm(normal) < .9 or normal[2]/norm(normal) > -.7:
            return False
        impact_offset = sub(vec(collision["impact_point_ned_m"]), ground)
        # Native clearance includes the actual pawn bounding-sphere radius.
        # A landing foot can contact anywhere in that footprint; its vertical
        # surface agreement remains independently constrained.
        valid_contact = (norm(impact_offset[:2]) <= landing["clearance_m"] and
                         abs(impact_offset[2]) <= .15 and collision["penetration_depth_m"] <= .15)
        if not valid_contact:
            return False
        now = time.monotonic()
        if self.state.landed_state != 0 and self._landing_contact_deadline is None:
            if self._landing_deadline is None:
                raise MissionError("Ground contact has no configured landing operation watchdog")
            # SimpleFlight's detector checks actual motor output and velocity;
            # OffboardApi.hpp defines no two-second contact/settling contract.
            # Keep monitoring within the original configured operation bound.
            self._landing_contact_deadline = self._landing_deadline
        if self._landing_contact_deadline is not None and now >= self._landing_contact_deadline:
            raise MissionError("Authorized ground contact was not confirmed Landed before the configured landing watchdog")
        return True

    @staticmethod
    def _contact_identity(collision):
        return (collision["source_timestamp_ns"], collision["object_name"], collision["object_id"],
                vec(collision["impact_point_ned_m"]), vec(collision["position_ned_m"]), collision["penetration_depth_m"])

    def _motor_contact_safe(self):
        contact, latest = self._landing_contact_record, self._latest_collision
        if not contact or not latest:
            return False, "No authorized physical ground contact", None
        if self.native_paused:
            return False, "Simulation is paused", None
        if self._contact_identity(contact) != self._contact_identity(latest):
            return False, "New impact since authorized ground contact", None
        if not self._expected_touchdown(contact):
            return False, "Authorized ground geometry no longer matches", None
        kinematics = self.state.kinematics_estimated
        linear, angular = vec(kinematics.linear_velocity), vec(kinematics.angular_velocity)
        if not all(math.isfinite(value) and abs(value) < .08 for value in linear+angular):
            return False, "Linear/angular motion exceeds SimpleFlight landed detector tolerance", None
        if norm(sub(vec(kinematics.position), vec(contact["position_ned_m"]))) > .1:
            return False, "Body moved away from physical ground contact", None
        return True, None, {"collision": copy.deepcopy(contact), "position_ned_m": xyz(vec(kinematics.position)),
                           "linear_velocity_mps": xyz(linear), "angular_velocity_rad_s": xyz(angular),
                           "actual_landed_state": int(self.state.landed_state)}

    def _request_motor_rotors(self, label):
        """Optional diagnostics never block the bounded landing control loop."""
        def probe():
            result = {"label": label, "available": False,
                      "note": "Rotor speed/thrust are physical diagnostics, not normalized PWM"}
            try:
                connection = dict(self.mission["connection"], rpc_timeout_s=.2)
                response = airsim_client(connection).getRotorStates(vehicle_name=self.vehicle)
                result.update(available=True, source_timestamp_ns=str(response.timestamp),
                    rotors=[{key: float(value) for key, value in rotor.items()} for rotor in response.rotors],
                    units={"speed": "rad/s", "thrust": "N", "torque_scaler": "backend torque coefficient"})
            except Exception as error:
                result["reason"] = str(error)
            self._motor_rotor_results.put_nowait(result)
        threading.Thread(target=probe, daemon=True, name="route-landing-rotors").start()

    def _poll_motor_rotors(self):
        while self.motor_settle_report is not None:
            try:
                result = self._motor_rotor_results.get_nowait()
            except queue.Empty:
                break
            self.motor_settle_report["rotor_diagnostics"].append(result)
            self.event("landing_rotor_diagnostics", **result)

    def _send_settle_pwm(self):
        self._operation_deadline(self._motor_deadline, "SimpleFlight motor settle")
        command = {"pwm_each_motor": .05, "duration_sim_s": .2, "simulation_elapsed_s": self.sim_s,
                   "wall_elapsed_s": time.monotonic()-self.started_wall}
        # The future is never joined: telemetry/geometry/deadlines remain live.
        self.client.moveByMotorPWMsAsync(.05, .05, .05, .05, .2, vehicle_name=self.vehicle)
        self.motor_settle_report["commands"].append(command)
        self.event("landing_motor_pwm_command", **command)
        self._motor_next_command_sim = self.sim_s+.1

    def _step_motor_settle(self, landing_deadline):
        if self.context.get("vehicle_type") != "simpleflight":
            return
        self._poll_motor_rotors()
        safe, reason, evidence = self._motor_contact_safe()
        now = time.monotonic()
        if self._motor_started:
            self._operation_deadline(self._motor_deadline, "SimpleFlight motor settle")
            if not safe:
                raise MissionError("SimpleFlight motor settle lost safe contact: " + reason)
            if self.state.landed_state == 0:
                if self.motor_settle_report["state"] != "confirmed_landed":
                    self.motor_settle_report.update(state="confirmed_landed", returned_landed_state=0,
                        confirmation=evidence, actual_wall_duration_s=now-self.motor_settle_report["started_wall"])
                    self.event("landing_motor_settle_confirmed", firmware="simpleflight", evidence=evidence)
                return
            if self.sim_s >= self._motor_next_command_sim:
                self._send_settle_pwm()
            return
        if self.state.landed_state == 0:
            return
        if not safe:
            self._motor_stable_since = self._motor_stable_sim = None
            return
        if self._motor_stable_since is None:
            self._motor_stable_since, self._motor_stable_sim = now, self.sim_s
            return
        if now-self._motor_stable_since < .25 or self.sim_s-self._motor_stable_sim < .25:
            return
        if landing_deadline-now < .25:
            return
        self.motor_settle_report = {"firmware": "simpleflight", "state": "in_progress", "started_wall": now,
            "dwell_wall_s": now-self._motor_stable_since, "dwell_sim_s": self.sim_s-self._motor_stable_sim,
            "contact_evidence": evidence, "commands": [], "rotor_diagnostics": [],
            "rotor_diagnostics_note": "Optional independent RPC probes; results may be unavailable at completion",
            "returned_landed_state": None, "watchdog_target_wall_s": min(2., landing_deadline-now),
            "requested_rpc_timeout_s": .2,
            "rpc_timeout_note": "Requested 0.2 s; msgpackrpc checks once per second, so this is not a hard 200 ms bound",
            "watchdog_note": "Cooperative target; blocking RPC and cleanup can overrun it. The native 45 s heartbeat threshold triggers recovery attempts and does not guarantee hover",
            "native_heartbeat_threshold_wall_s": 45.,
            "duration_measurement_note": "Success ends at returned Landed confirmation; failure includes cancel and hover cleanup requests"}
        self._motor_deadline = min(landing_deadline, now+2.)
        self._motor_original_client = self.client
        # Keep transport waits short during this safety-sensitive phase. The
        # native independent supervisor remains the final blocked-process bound.
        self.client = airsim_client(dict(self.mission["connection"], rpc_timeout_s=.2))
        self._motor_started = True
        self.event("landing_motor_settle_started", firmware="simpleflight", evidence=evidence,
                   dwell_wall_s=now-self._motor_stable_since, dwell_sim_s=self.sim_s-self._motor_stable_sim,
                   watchdog_target_wall_s=self.motor_settle_report["watchdog_target_wall_s"],
                   requested_rpc_timeout_s=.2, watchdog_note=self.motor_settle_report["watchdog_note"])
        self._request_motor_rotors("before_pwm")
        self.client.cancelLastTask(vehicle_name=self.vehicle)
        self.event("landing_motor_descent_cancelled")
        self._send_settle_pwm()
        self._request_motor_rotors("after_pwm")

    def _abort_motor_settle(self, reason):
        errors = []
        for label, operation in (("cancel", lambda:self.client.cancelLastTask(vehicle_name=self.vehicle)),
                                 ("hover", lambda:self.client.hoverAsync(vehicle_name=self.vehicle))):
            try:
                operation()
            except Exception as error:
                errors.append(label+": "+str(error))
        self.motor_settle_report.update(state="failed", reason=reason,
            cancelled_and_hover_requested=not errors, recovery_errors=errors)
        self._poll_motor_rotors()
        self.motor_settle_report["actual_wall_duration_s"] = time.monotonic()-self.motor_settle_report["started_wall"]
        self.event("landing_motor_settle_aborted", reason=reason, recovery_errors=errors,
                   actual_wall_duration_s=self.motor_settle_report["actual_wall_duration_s"],
                   note="PWM goal is explicitly replaced; duration expiry alone is insufficient")

    def _land(self):
        self._landing_clear()
        self.event("landing_started", native_vehicle_type=self.context.get("vehicle_type"),
                   simpleflight_motor_settle_eligible=self.context.get("vehicle_type") == "simpleflight")
        self.status_state = "landing"
        self.status(force=True)
        self._landing_timeout_s = min(60., self.mission["flight"]["takeoff"]["timeout_s"])
        deadline = self._landing_deadline = time.monotonic()+self._landing_timeout_s
        self._landing_active = True
        self._landing_contact_deadline = None
        self._landing_contact_record = None
        self._motor_stable_since = self._motor_stable_sim = None
        self._motor_started = False
        try:
            self.client.cancelLastTask(vehicle_name=self.vehicle)
            self.client.landAsync(timeout_sec=self._landing_timeout_s, vehicle_name=self.vehicle)
            while True:
                self.tick(allow_commands=False)
                if self._landing_contact_deadline is not None:
                    self._operation_deadline(self._landing_contact_deadline, "Ground contact Landed confirmation")
                else:
                    self._operation_deadline(deadline, "Landing")
                self._step_motor_settle(deadline)
                if self.state.landed_state == 0:
                    if not self._near_landing_ground():
                        raise MissionError("Landed state is not near the validated ground at low velocity")
                    if self._landing_contact_record is not None and self.touchdown is None:
                        if not self._expected_touchdown(self._landing_contact_record):
                            raise MissionError("Landed confirmation no longer matches the authorized ground contact")
                        self.touchdown = copy.deepcopy(self._landing_contact_record)
                        self.touchdown["classification"] = "verified_landing_touchdown"
                        self.event("landing_touchdown", collision=self.touchdown)
                    break
                time.sleep(.03)
            self._sample(force=True)
            if self._motor_started:
                self._step_motor_settle(deadline)
            if not self._near_landing_ground():
                raise MissionError("Landing state changed before disarming")
            if self.client.armDisarm(False, vehicle_name=self.vehicle) is False:
                raise MissionError("Backend refused disarm after verified Landed")
            self.client.enableApiControl(False, vehicle_name=self.vehicle)
            self.api_owned = False
        except BaseException as error:
            if self._motor_started:
                self._abort_motor_settle(str(error))
            raise
        finally:
            self._landing_active = False
            if self._motor_original_client is not None:
                self.client, self._motor_original_client = self._motor_original_client, None
        if self._prepared:
            self.event("landed")

    def initialize_recovery(self):
        """Initialize an independent CLI supervisor without overwriting run artifacts."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.clock = self.clock or NativeClock(self.context)
        baseline = None
        summary = self.run_dir / "summary.json"
        if summary.exists():
            baseline = read_json(summary).get("grounded_collision_baseline")
        if not baseline:
            events = self.run_dir / "events.jsonl"
            if events.exists():
                with events.open(encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get("event") == "grounded_collision_baseline":
                            baseline = event.get("collision")
        if baseline:
            self._collision_baseline_identity = (str(baseline["source_timestamp_ns"]), baseline["object_name"],
                baseline["object_id"], vec(baseline["impact_point_ned_m"]), vec(baseline["position_ned_m"]),
                float(baseline["penetration_depth_m"]))
            self.collision_baseline = copy.deepcopy(baseline)
        self.client = self.client or airsim_client(self.mission["connection"])
        self.api_owned = bool(self.client.isApiControlEnabled(vehicle_name=self.vehicle))
        self.original_pause = False
        self.state = self.client.getMultirotorState(vehicle_name=self.vehicle)

    def recover(self, land=False):
        acknowledgement = {"cancel": False, "unfreeze": False, "hover": False, "landed": False, "errors": []}
        if self.client is None:
            return acknowledgement
        operations = [("unfreeze", lambda: self.client.simPause(bool(self.original_pause)))]
        if self.api_owned:
            operations.insert(0, ("cancel", lambda: self.client.cancelLastTask(vehicle_name=self.vehicle)))
        for name, operation in operations:
            try:
                operation()
                acknowledgement[name] = True
            except Exception as error:
                acknowledgement["errors"].append(name + ": " + str(error))
        if self.api_owned:
            try:
                self.client.hoverAsync(vehicle_name=self.vehicle)
                deadline = time.monotonic()+min(5., self.mission["connection"]["rpc_timeout_s"])
                while time.monotonic() < deadline:
                    state = self.client.getMultirotorState(vehicle_name=self.vehicle)
                    self.state = state
                    if norm(vec(state.kinematics_estimated.linear_velocity)) <= self.mission["defaults"]["node"]["max_settled_speed_mps"]:
                        acknowledgement["hover"] = True
                        break
                    time.sleep(.05)
                if land:
                    if not acknowledgement["hover"]:
                        raise MissionError("Recovery hover was not acknowledged; landing refused")
                    self.clock = self.clock or NativeClock(self.context)
                    self._clock()
                    self._sample(force=True)
                    self._land()
                    acknowledgement["landed"] = True
                    acknowledgement["verified_touchdown"] = self.touchdown
            except Exception as error:
                acknowledgement["errors"].append("recovery: " + str(error))
                if land:
                    # A failed landing monitor must not leave the asynchronous
                    # descent running without supervision.
                    try:
                        self.client.cancelLastTask(vehicle_name=self.vehicle)
                        self.client.hoverAsync(vehicle_name=self.vehicle)
                        acknowledgement["landing_cancelled_then_hover_requested"] = True
                    except Exception as recovery_error:
                        acknowledgement["errors"].append("landing abort: " + str(recovery_error))
        self.recovery = acknowledgement
        if self.motor_settle_report is not None:
            self._poll_motor_rotors()
            acknowledgement["simpleflight_motor_settle"] = self.motor_settle_report
        return acknowledgement

    def _summary(self, state, reason):
        wall = time.monotonic()-self.started_wall
        current = getattr(self, "current_segment_metrics", None)
        if current:
            current["actual_speed_mps"].update(quantiles(current.pop("_speed_samples")))
            self.segment_records.append(current)
            self.current_segment_metrics = None
        for segment in self.segment_records:
            pairs = [record for record in self.pair_records if record["trigger"].get("segment_id") == segment["id"]]
            segment["periodic_pairs"] = len(pairs)
            segment["achieved_active_pair_rate_hz"] = len(pairs)/segment["active_duration_sim_s"] if segment["active_duration_sim_s"] else None
            segment["achieved_wall_pair_rate_hz"] = len(pairs)/segment["wall_duration_s"] if segment["wall_duration_s"] else None
        return {"schema_version": "1.0.0", "state": state, "reason": reason,
            "created_utc": self.created_utc, "configuration_sha256": self.configuration_hash,
            "nodes_completed": self.nodes_completed, "nodes_total": self.total_nodes,
            "route_complete": self.nodes_completed == self.total_nodes,
            "pairs": self.committed, "images": 2*self.committed, "bytes": self.total_bytes,
            "wall_duration_s": wall, "simulation_duration_s": self.sim_s, "active_duration_sim_s": self.active_s,
            "whole_run_pair_rate_sim_hz": self.committed/self.sim_s if self.sim_s else None,
            "whole_run_pair_rate_wall_hz": self.committed/wall if wall else None,
            "deadline_success_ratio": self.stats["valid_travel_pairs"]/self.stats["eligible_travel_deadlines"] if self.stats["eligible_travel_deadlines"] else None,
            **self.stats, "queue_high_water": self.writer.high_water if self.writer else 0,
            "acquisition_latency_wall_s": quantiles([r["acquisition_latency_wall_s"] for r in self.pair_records]),
            "commit_latency_wall_s": quantiles([r["commit_latency_wall_s"] for r in self.pair_records]),
            "write_latency_wall_s": quantiles([r["write_latency_wall_s"] for r in self.pair_records]),
            "pair_position_delta_m": quantiles([r["quality"]["position_delta_m"] for r in self.pair_records]),
            "pair_angle_delta_deg": quantiles([r["quality"]["angle_delta_deg"] for r in self.pair_records]),
            "max_cross_track_error_m": max((s["cross_track_error_m"]["max"] for s in self.segment_records), default=None),
            "segments": self.segment_records, "nodes": self.node_records, "recovery": self.recovery,
            "grounded_collision_baseline": self.collision_baseline,
            "verified_landing_touchdown": self.touchdown,
            "simpleflight_motor_settle": self.motor_settle_report,
            "thermal": {"warmup_requested_ms": self.mission["thermal"]["warmup_ms"],
                        "warmup_actual_sim_s": getattr(self, "warmup_actual", None),
                        "context": self.context.get("active_profile", {}).get("thermal")},
            "missing_measurements": {"thermal_receiver_diagnostics": "Not exposed by legacy image RPC; consult native context references",
                "shared_render_frame_id": "Sequential native capture does not prove a shared render frame"}}

    def run(self):
        state, reason = "failed", None
        try:
            self.preflight()
            self.writer = PairWriter(self.run_dir, self.mission["acquisition"]["max_pending_writes"])
            self.status_state = "running"
            self.client.enableApiControl(True, vehicle_name=self.vehicle)
            self.api_owned = True
            if not self.client.armDisarm(True, vehicle_name=self.vehicle):
                raise MissionError("Simulator refused arming")
            self.event("armed")
            takeoff = self.mission["flight"]["takeoff"]
            if self.state.landed_state == 0:
                takeoff_start = vec(self.state.kinematics_estimated.position)
                self.client.takeoffAsync(timeout_sec=takeoff["timeout_s"], vehicle_name=self.vehicle)
                deadline = time.monotonic()+takeoff["timeout_s"]
                while self.state.landed_state == 0:
                    self.tick()
                    self._operation_deadline(deadline, "Takeoff")
                    self._pause_wait(deadline, "Takeoff")
                    time.sleep(.025)
                climb = copy.deepcopy(self.mission["nodes"][0])
                climb["id"] = "takeoff"
                climb["settings"]["behavior"] = "stop"
                climb["position_ned_m"] = xyz((takeoff_start[0], takeoff_start[1], takeoff_start[2]-takeoff["height_above_takeoff_m"]))
                self._travel(climb, {"speed_mps": self.mission["flight"]["entry_leg"]["speed_mps"],
                                   "timeout_s": max(.01, deadline-time.monotonic())})
            warm_start = self.active_s
            self._wait_active(self.mission["thermal"]["warmup_ms"]/1000,
                              time.monotonic()+self.mission["limits"]["max_duration_wall_s"])
            self.warmup_actual = self.active_s-warm_start
            nodes = self.mission["nodes"]
            entry = self.mission["flight"]["entry_leg"]
            self._travel(nodes[0], entry)
            self._node(nodes[0], entry["timeout_s"])
            for index, segment in enumerate(self.mission["segments"]):
                self._travel(nodes[index+1], segment["settings"], previous=nodes[index], segment=segment)
                self._node(nodes[index+1], segment["settings"]["timeout_s"])
            self.flush()
            if self.mission["flight"]["on_complete"] == "land_here":
                self._land()
            else:
                self.recover()
                if not self.recovery["hover"]:
                    raise MissionError("Completion hover was not acknowledged")
            state = "completed"
        except MissionStopped as error:
            state, reason = "stopped", str(error)
            self.recover(land=str(error) == "Land requested")
        except MissionLimit as error:
            state, reason = "limit_reached", str(error)
            self.recover()
        except (Exception, KeyboardInterrupt) as error:
            state, reason = "failed", str(error) or "Keyboard interrupt"
            if self.api_owned or self.capture_worker is not None:
                self.recover()
        finally:
            if self._prepared:
                try:
                    if self.writer:
                        deadline = time.monotonic()+5
                        while self.writer.pending and time.monotonic() < deadline:
                            self._collect()
                            time.sleep(.02)
                        if self.writer.pending:
                            state, reason = "failed", "Writer did not drain within final watchdog"
                        else:
                            self.writer.work.put_nowait(None)
                    if self.capture_worker:
                        try:
                            self.capture_worker.requests.put_nowait(None)
                        except queue.Full:
                            pass
                    self.event("run_finished", state=state, reason=reason)
                    summary = self._summary(state, reason)
                    atomic_json(self.run_dir / "summary.json", summary)
                    self.status_state = state
                    self.status(force=True, reason=reason)
                except Exception as error:
                    state, reason = "failed", "Final output error: " + str(error)
                    try:
                        self.status_state = state
                        self.status(force=True, reason=reason)
                    except Exception:
                        pass
        return {"state": state, "reason": reason, "run_dir": str(self.run_dir), "pairs": self.committed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", required=True)
    parser.add_argument("--run-dir")
    parser.add_argument("--context")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--recover", choices=("hover", "land"))
    args = parser.parse_args(argv)
    try:
        authored, resolved, warnings = load_mission(args.mission)
        if args.validate_only:
            if args.context:
                resolved, _ = resolve_context(resolved, args.context)
            report = {"valid": True, "mission_id": authored["mission_id"], "warnings": warnings,
                      "configuration_sha256": hashlib.sha256(canonical(resolved)).hexdigest()}
            if args.run_dir:
                directory = Path(args.run_dir)
                directory.mkdir(parents=True, exist_ok=True)
                atomic_json(directory / "validation.json", report)
            print(json.dumps(report))
            return 0
        if not args.context or not args.run_dir:
            parser.error("--context and --run-dir are required for live modes")
        runner = MissionRunner(args.mission, args.run_dir, args.context)
        if args.recover:
            runner.initialize_recovery()
            result = runner.recover(land=args.recover == "land")
            atomic_json(Path(args.run_dir) / "recovery.json", result)
            print(json.dumps(result))
            return 0 if (result["landed"] if args.recover == "land" else result["hover"]) else 1
        if args.preflight:
            try:
                result = runner.preflight()
                runner.status_state = "preflight_passed"
                runner.status(force=True)
            except Exception as error:
                if runner.capture_worker is not None:
                    atomic_json(runner.run_dir / "recovery.json", runner.recover())
                if runner._prepared:
                    runner.status_state = "preflight_failed"
                    runner.status(force=True, reason=str(error))
                    atomic_json(runner.run_dir / "preflight.json", {"passed": False, "reason": str(error)})
                raise
            print(json.dumps(result))
            return 0
        result = runner.run()
        print(json.dumps(result))
        return 0 if result["state"] == "completed" else 1
    except (MissionError, OSError, ValueError, ImportError) as error:
        print(json.dumps({"state": "failed", "reason": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
