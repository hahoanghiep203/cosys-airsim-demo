"""Encode three synchronized views of one genuine mixed Route Capture mission.

CLI: --result mixed_showcase_<tag>_result.json --drone-folder FOLDER --output FRESH_FOLDER
Uses native simulation timestamps only. No image interpolation, IR enhancement,
wall-clock retiming, or synthetic camera frames are introduced.
"""
import argparse
from bisect import bisect_right
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
BG = (12, 19, 29)
PANEL = (21, 31, 44)
INK = (239, 245, 251)
MUTED = (153, 171, 192)
TEAL = (81, 220, 213)
AMBER = (255, 191, 101)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic_json(path, value):
    path = Path(path)
    candidate = path.with_suffix(path.suffix + ".partial")
    with candidate.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(candidate, path)


def absolute(path):
    path = Path(path)
    return path.resolve() if path.is_absolute() else (ROOT/path).resolve()


def inside(folder, name):
    path = (folder/Path(name)).resolve()
    if not path.is_relative_to(folder):
        raise RuntimeError("Evidence path escapes its source folder: " + str(path))
    if not path.is_file():
        raise RuntimeError("Missing actual source image: " + str(path))
    return path


def manifest_in(folder, names):
    for name in names:
        if (folder/name).is_file():
            return folder/name
    raise RuntimeError("Frame metadata not found in " + str(folder))


def quat(rotation):
    pitch, yaw, roll = [math.radians(float(x))/2 for x in rotation]
    sp, cp, sy, cy, sr, cr = math.sin(pitch), math.cos(pitch), math.sin(yaw), math.cos(yaw), math.sin(roll), math.cos(roll)
    return np.asarray([sr*cp*cy-cr*sp*sy, cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy, cr*cp*cy+sr*sp*sy])


def angle(a, b):
    return math.degrees(2*math.acos(min(1., abs(float(np.dot(quat(a), quat(b)))))))


def read_frames(folder, names, size):
    path = manifest_in(folder, names)
    data = load(path)
    frames = data.get("frames", [])
    if len(frames) < 2:
        raise RuntimeError("At least two actual frames are required: " + str(path))
    previous = -math.inf
    for frame in frames:
        stamp = frame["sim_time_s"]
        if not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp <= previous:
            raise RuntimeError("Frame simulation timestamps must be finite and strictly increasing")
        previous = stamp
        frame["_path"] = inside(folder, frame["file"])
        with Image.open(frame["_path"]) as image:
            if image.size != size:
                raise RuntimeError(f"Expected {size} source frame, got {image.size}: {frame['_path']}")
    if data.get("errors"):
        raise RuntimeError("Recorder reported errors: " + json.dumps(data["errors"]))
    return data, frames, path


def check_observer(data, frames):
    positions = np.asarray([f["position_cm"] for f in frames], dtype=float)
    rotations = np.asarray([f["rotation_deg"] for f in frames], dtype=float)
    if not np.isfinite(positions).all() or not np.isfinite(rotations).all():
        raise RuntimeError("Nonfinite fixed observer transform")
    position = float(np.linalg.norm(positions-positions[0], axis=1).max())
    rotation = float(np.abs((rotations-rotations[0]+180) % 360-180).max())
    if position > 1e-6 or rotation > 1e-6:
        raise RuntimeError("Observer moved; refuse fixed-camera evidence")
    return {"passed": True, "position_max_delta_cm": position, "rotation_max_delta_deg": rotation,
            "position_tolerance_cm": 1e-6, "rotation_tolerance_deg": 1e-6,
            "transform_position_cm": positions[0].tolist(), "transform_rotation_deg": rotations[0].tolist(),
            "width": 960, "height": 540, "fov_deg": data.get("fov_deg")}


def check_drone(data, frames, mission):
    caps = {"position_cm": .01, "angle_deg": .01, "fov_deg": .001}
    tolerances = data.get("mirror_tolerances", {})
    if any(not 0 < tolerances.get(key, 0) <= cap for key, cap in caps.items()):
        raise RuntimeError("Missing or overly loose drone mirror tolerances")
    if not data.get("sensor_actor_path") or not data.get("sensor_component_path"):
        raise RuntimeError("Drone recorder must identify the actual sensor actor/component")
    maximum = dict.fromkeys(caps, 0.)
    for frame in frames:
        for key in ("position_cm", "sensor_position_cm", "rotation_deg", "sensor_rotation_deg"):
            if not np.isfinite(np.asarray(frame[key], dtype=float)).all():
                raise RuntimeError("Nonfinite drone mirror pose")
        errors = {"position_cm": float(np.linalg.norm(np.asarray(frame["position_cm"])-np.asarray(frame["sensor_position_cm"]))),
                  "angle_deg": angle(frame["rotation_deg"], frame["sensor_rotation_deg"]),
                  "fov_deg": abs(frame["fov_deg"]-frame["sensor_fov_deg"])}
        for key, value in errors.items():
            if not math.isfinite(value) or value > tolerances[key]:
                raise RuntimeError("Drone mirror mismatch: " + key + " " + str(value))
            maximum[key] = max(maximum[key], value)
        for field, key in (("position_delta_cm", "position_cm"), ("angle_delta_deg", "angle_deg"), ("fov_delta_deg", "fov_deg")):
            value = frame.get(field)
            if not isinstance(value, (float, int)) or not math.isfinite(value) or value > tolerances[key]:
                raise RuntimeError("Recorder mirror check failed/missing: " + field)
        if frame.get("all_markers_hidden") is not True:
            raise RuntimeError("Drone view contains route/debug markers")
        if abs(frame["sensor_fov_deg"]-mission["camera"]["horizontal_fov_deg"]) > tolerances["fov_deg"]:
            raise RuntimeError("Actual sensor FOV differs from the mission")
    return {"passed": True, "maximum_errors": maximum, "tolerances": tolerances, "all_markers_hidden": True,
            "sensor_actor_path": data["sensor_actor_path"], "sensor_component_path": data["sensor_component_path"],
            "camera_selection_note": data.get("camera_selection_note"), "source_note": data.get("source_note"),
            "width": 640, "height": 480,
            "limitation": "Independent live renderer mirrors pose/FOV; identical pixels or a shared RPC render frame are not asserted"}



def drone_color_conversion(data):
    source = str(data.get("sensor_capture_source", ""))
    target = str(data.get("target_format", ""))
    declared = data.get("exported_png_color_space") == "linear_rgb"
    known_export = "SCS_FINAL_TONE_CURVE_HDR" in source and "RTF_RGBA8" in target
    return {"applied": declared or known_export,
            "scope": "02_live_drone_view.mp4 source pixels only; before video annotations",
            "input_color_space": "linear_rgb" if declared or known_export else "unchanged / not declared linear",
            "output_color_space": "sRGB" if declared or known_export else "unchanged",
            "basis": "explicit exported_png_color_space" if declared else (
                "verified FinalToneCurveHDR SceneCapture export into RTF_RGBA8" if known_export else "no matching linear export metadata"),
            "sensor_capture_source": data.get("sensor_capture_source"), "target_format": data.get("target_format"),
            "transfer": "IEC sRGB: x <= 0.0031308 ? 12.92*x : 1.055*x**(1/2.4)-0.055; clamp [0,1], round to uint8",
            "limitations": "Original export is already quantized to 8-bit linear RGB; standard display conversion cannot restore lost dark-tone precision or clipped HDR values. No exposure, guessed gamma, or contrast adjustment. Observer and saved RGB/ThermalIR panels are unchanged."}


def linear_rgb_to_srgb(source):
    linear = np.asarray(source.convert("RGB"), dtype=np.float64)/255.
    display = np.where(linear <= .0031308, 12.92*linear, 1.055*linear**(1/2.4)-.055)
    return Image.fromarray(np.rint(np.clip(display, 0., 1.)*255).astype(np.uint8))


def read_pairs(run, summary):
    pairs, bases = [], []
    for directory in sorted((run/"pairs").iterdir()):
        if not directory.is_dir() or not directory.name.isdecimal():
            continue
        path = directory/"record.json"
        record = load(path)
        stamp = record.get("thermal_elapsed_simulation_s")
        relative = record.get("acquisition_frozen_simulation_elapsed_s")
        if not isinstance(stamp, (float, int)) or not math.isfinite(stamp) or not isinstance(relative, (float, int)):
            raise RuntimeError("A pair lacks actual absolute and run-relative acquisition simulation times")
        record["_absolute_sim_s"] = float(stamp)
        record["_record_path"] = str(path)
        bases.append(stamp-relative)
        for label, kind in (("rgb", 0), ("ir", 12)):
            info = record["images"][label]
            image_path = inside(run, info["path"])
            if info["image_type"] != kind or hashlib.sha256(image_path.read_bytes()).hexdigest() != info["sha256"]:
                raise RuntimeError("Saved pair image type/hash failed: " + str(image_path))
            with Image.open(image_path) as image:
                if image.size != (info["width_px"], info["height_px"]):
                    raise RuntimeError("Saved pair image dimensions differ from its record")
                image.verify()
            record["images"][label]["_path"] = str(image_path)
        pairs.append(record)
    if len(pairs) != summary["pairs"] or not pairs:
        raise RuntimeError("Committed pair count does not match the mission summary")
    if set(p["trigger"]["kind"] for p in pairs) != {"node", "travel"}:
        raise RuntimeError("Mixed showcase requires both actual stopped-node and in-flight captures")
    pairs.sort(key=lambda record: (record["_absolute_sim_s"], record["pair_id"]))
    if max(bases)-min(bases) > 1e-5:
        raise RuntimeError("Pair records disagree about the native run simulation clock origin")
    return pairs, sum(bases)/len(bases)


def read_events(run, base):
    events = []
    with (run/"events.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            value = json.loads(line)
            stamp = base+value["simulation_elapsed_s"]
            if not math.isfinite(stamp):
                raise RuntimeError("Event simulation time is not finite")
            events.append((stamp, value))
    return sorted(events, key=lambda event: event[0])


def frame_plan(frames, start, end):
    times = [f["sim_time_s"] for f in frames]
    index = max(0, bisect_right(times, start)-1)
    selected = [(start, frames[index])]
    selected.extend((frame["sim_time_s"], frame) for frame in frames[index+1:] if start < frame["sim_time_s"] < end)
    return [{"display_sim_s": stamp, "source_sim_s": frame["sim_time_s"], "duration_s": (
                selected[i+1][0] if i+1 < len(selected) else end)-stamp, "source": frame}
            for i, (stamp, frame) in enumerate(selected)]


@lru_cache(maxsize=12)
def font(size, bold=False):
    path = Path("C:/Windows/Fonts")/("segoeuib.ttf" if bold else "segoeui.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size=size)


def text(draw, xy, value, size=24, color=INK, bold=False, width=None):
    value = str(value)
    face = font(size, bold)
    if width:
        while value and draw.textlength(value, font=face) > width:
            value = value[:-2].rstrip()+"…" if not value.endswith("…") else value[:-2]+"…"
    draw.text(xy, value, font=face, fill=color)


def fit(canvas, source, box):
    x, y, width, height = box
    image = source.convert("RGB")
    scale = min(width/image.width, height/image.height)
    resized = image.resize((round(image.width*scale), round(image.height*scale)), Image.Resampling.LANCZOS)
    canvas.paste(resized, (x+(width-resized.width)//2, y+(height-resized.height)//2))


def phase_at(events, stamp):
    phase, node, segment = "PREPARING ROUTE", None, None
    for when, event in events:
        if when > stamp:
            break
        kind = event["event"]
        if kind == "segment_started":
            phase, segment, node = "IN-FLIGHT CAPTURE", event.get("segment_id"), None
        elif kind in ("node_arrived", "node_settling", "node_settled"):
            phase, node, segment = "STOP & CAPTURE", event.get("node_id"), None
        elif kind == "node_completed":
            phase, node = "NODE COMPLETE", event.get("node_id")
        elif kind == "node_passed":
            phase, node = "FLY-THROUGH", event.get("node_id")
        elif kind == "entry_started":
            phase, node, segment = "POSITIONING", event.get("node_id"), None
        elif kind == "run_finished":
            phase = "ROUTE COMPLETE" if event.get("state") == "completed" else "RUN "+event.get("state", "FINISHED").upper()
        elif kind == "control":
            if event.get("command") == "pause":
                phase = "PAUSED"
    return phase, node, segment


@lru_cache(maxsize=4)
def pair_image(path):
    with Image.open(path) as image:
        return image.convert("RGB")


def annotate(source, stamp, phase, count, dimensions, subtitle):
    canvas = source.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, dimensions[0], 72), fill=BG)
    text(draw, (18, 6), subtitle, 21, bold=True, width=dimensions[0]-36)
    text(draw, (18, 38), f"SIM {stamp:.2f}s  |  {phase}  |  {count} PAIRS", 17, color=TEAL, width=dimensions[0]-36)
    return canvas


def composite(observer, stamp, phase, node, segment, latest, count, total, start, end):
    canvas = Image.new("RGB", (1920, 1080), BG)
    draw = ImageDraw.Draw(canvas)
    text(draw, (32, 24), "ONE ROUTE. TWO CAPTURE MODES.", 39, bold=True)
    text(draw, (32, 78), "Actual multirotor flight  /  RGB + ThermalIR  /  Native simulation timeline", 23, MUTED)
    accent = AMBER if phase == "STOP & CAPTURE" else TEAL
    draw.rounded_rectangle((32, 124, 1888, 166), radius=10, fill=PANEL)
    text(draw, (48, 127), phase, 24, accent, True)
    text(draw, (665, 128), f"NODE {node or '-'}   SEGMENT {segment or '-'}", 22, width=760)
    text(draw, (1510, 128), f"SIM {stamp:.2f} s", 23, width=355)
    text(draw, (32, 178), "FIXED OBSERVER  /  LIVE FLIGHT", 22, TEAL, True)
    draw.rectangle((32, 208, 1292, 917), fill=PANEL)
    fit(canvas, observer, (32, 208, 1260, 709))
    text(draw, (1322, 178), "LATEST ACTUAL CAPTURE", 22, AMBER, True)
    text(draw, (1334, 213), "RGB", 22, TEAL, True)
    text(draw, (1334, 638), "THERMAL IR", 22, AMBER, True)
    for y in (242, 666):
        draw.rectangle((1334, y, 1878, y+385), fill=PANEL)
    if latest:
        fit(canvas, pair_image(latest["images"]["rgb"]["_path"]), (1334, 242, 544, 385))
        fit(canvas, pair_image(latest["images"]["ir"]["_path"]), (1334, 666, 544, 385))
        kind = latest["trigger"]["kind"]
        source_mode = "STOP & CAPTURE" if kind == "node" else "IN-FLIGHT CAPTURE"
        source_accent = AMBER if kind == "node" else TEAL
        location = latest["trigger"].get("node_id", latest["trigger"].get("segment_id", "-"))
        text(draw, (32, 944), f"{count:03d} / {total:03d} PAIRS ACQUIRED", 31, bold=True)
        text(draw, (32, 991), f"Latest pair {latest['pair_id']}  |  {source_mode}  |  {location}", 24, source_accent, width=870)
        text(draw, (1410, 216), f"PAIR {latest['pair_id']}  |  SIM {latest['_absolute_sim_s']:.2f}s", 16, MUTED, width=468)
        text(draw, (930, 997), f"Still age {stamp-latest['_absolute_sim_s']:.2f}s", 20, MUTED, width=350)
    else:
        text(draw, (32, 946), "CAPTURE PANELS WAIT FOR THE FIRST ACTUAL PAIR", 27, MUTED, True, width=1240)
        text(draw, (1380, 412), "No pair acquired yet", 23, MUTED)
        text(draw, (1380, 840), "No pair acquired yet", 23, MUTED)
    draw.rectangle((32, 1048, 1292, 1056), fill=PANEL)
    draw.rectangle((32, 1048, 32+round(1260*(stamp-start)/(end-start)), 1056), fill=accent)
    text(draw, (32, 1024), "AMBER: STOP & CAPTURE     CYAN: IN-FLIGHT CAPTURE", 17, MUTED)
    return canvas


def encode_vfr(plan, directory, destination, draw_frame):
    directory.mkdir()
    rows, lines = [], ["ffconcat version 1.0"]
    for index, item in enumerate(plan):
        with Image.open(item["source"]["_path"]) as source:
            rendered = draw_frame(source, item)
        target = directory/f"frame_{index:06d}.png"
        rendered.save(target, compress_level=1)
        safe = str(target).replace("\\", "/").replace("'", "'\\''")
        lines.extend(["file '"+safe+"'", "option framerate 1000", f"duration {item['duration_s']:.9f}"])
        rows.append({"source_file": str(item["source"]["_path"]), "source_sim_time_s": item["source_sim_s"],
                     "display_sim_time_s": item["display_sim_s"], "duration_s": item["duration_s"]})
    lines.append(lines[-3])
    lines.append("option framerate 1000")
    concat = directory/"frames.ffconcat"
    concat.write_text("\n".join(lines)+"\n", encoding="utf-8")
    candidate = destination.with_name(destination.stem+".partial.mp4")
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("FFmpeg executable not found")
    # Keep decode and presentation order identical. With reordered B-frames the
    # MP4 muxer can derive a short track duration from the final decode packet,
    # even though the terminal presentation timestamp is present and correct.
    subprocess.run([executable, "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat), "-fps_mode", "vfr", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "19", "-pix_fmt", "yuv420p", "-enc_time_base", "1:1000", "-bf", "0",
                    "-video_track_timescale", "1000000",
                    "-movflags", "+faststart", str(candidate)], check=True)
    with candidate.open("r+b") as stream:
        os.fsync(stream.fileno())
    os.replace(candidate, destination)
    mapping = destination.with_suffix(".frames.json")
    atomic_json(mapping, {"timeline": "native unpaused world simulation seconds", "frames": rows})
    probe = shutil.which("ffprobe")
    if not probe:
        raise RuntimeError("FFprobe executable not found")
    metadata = json.loads(subprocess.check_output([probe, "-v", "error", "-select_streams", "v:0",
        "-show_streams", "-show_format", "-show_packets", "-show_entries",
        "stream=codec_type,width,height,duration:format=duration:packet=pts_time,dts_time,duration_time",
        "-of", "json", str(destination)], text=True))
    stream = next(s for s in metadata["streams"] if s["codec_type"] == "video")
    duration_error = float(metadata["format"]["duration"])-sum(item["duration_s"] for item in plan)
    if abs(duration_error) > .005:
        raise RuntimeError("Encoded duration does not preserve native timeline within 5 ms: "+str(duration_error))
    # Check every displayed source boundary, as total duration alone cannot
    # detect lost/repeated frames or retimed intervals. The extra final packet
    # holds the last actual image for the declared 1 ms terminal boundary.
    packets = metadata["packets"]
    if len(packets) != len(plan)+1:
        raise RuntimeError("Encoded frame count differs from native plan plus terminal boundary")
    actual = [float(packet["pts_time"]) for packet in packets]
    expected = [item["display_sim_s"]-plan[0]["display_sim_s"] for item in plan]
    expected.append(sum(item["duration_s"] for item in plan))
    timestamp_error = max(abs(a-b) for a, b in zip(actual, expected))
    interval_error = max(abs((actual[i+1]-actual[i])-item["duration_s"]) for i, item in enumerate(plan))
    if (any(b <= a for a, b in zip(actual, actual[1:])) or
            any(abs(float(packet["dts_time"])-stamp) > 1e-6 for packet, stamp in zip(packets, actual)) or
            timestamp_error > .001 or interval_error > .001):
        raise RuntimeError("Encoded timestamps/intervals do not preserve native millisecond VFR timing")
    terminal_hold = float(packets[-1]["duration_time"])
    if abs(terminal_hold-.001) > 1e-6:
        raise RuntimeError("Encoded terminal boundary does not have the declared 1 ms hold")
    return {"file": str(destination), "frames_mapping": str(mapping), "bytes": destination.stat().st_size,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "width": stream["width"], "height": stream["height"],
            "encoded_duration_s": float(metadata["format"]["duration"]), "source_frames_used": len(plan),
            "native_duration_error_s": duration_error, "terminal_boundary_hold_s": terminal_hold,
            "native_timestamp_max_error_s": timestamp_error, "native_interval_max_error_s": interval_error,
            "encoded_frames": len(packets), "vfr": True,
            "encoding": "H.264 yuv420p without B-frames; recorded native intervals, millisecond input time base",
            "holds": "Actual source frames held until the next recorded native timestamp; no motion interpolation"}


def encode(result_file, drone_folder, output, trim_warmup=False):
    result_file, drone_folder, output = absolute(result_file), absolute(drone_folder), absolute(output)
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("Choose a fresh output directory; previous evidence is preserved")
    result = load(result_file)
    linked_drone = result.get("drone_view", {}).get("directory")
    if linked_drone and absolute(linked_drone) != drone_folder:
        raise RuntimeError("Drone folder differs from this actual run's recorded result linkage")
    run, observer_folder = absolute(result["run_dir"]), absolute(result["observer"]["directory"])
    summary, mission = load(run/"summary.json"), load(run/"resolved_mission.json")
    if summary["state"] != "completed" or not summary["route_complete"] or summary.get("collisions", 0):
        raise RuntimeError("The showcase requires one completed collision-free mission")
    observer_data, observer, observer_manifest = read_frames(observer_folder, ("frames.json", "observerframes.json"), (960,540))
    drone_data, drone, drone_manifest = read_frames(drone_folder, ("frames.json", "droneviewframes.json"), (640,480))
    checks = {"fixed_observer": check_observer(observer_data, observer), "drone_mirror": check_drone(drone_data, drone, mission)}
    drone_color = drone_color_conversion(drone_data)
    pairs, base = read_pairs(run, summary)
    events = read_events(run, base)
    pair_times = [p["_absolute_sim_s"] for p in pairs]
    start, end = max(observer[0]["sim_time_s"], drone[0]["sim_time_s"]), min(observer[-1]["sim_time_s"], drone[-1]["sim_time_s"])
    if end <= start:
        raise RuntimeError("The two actual native simulation recordings do not overlap")
    original_overlap = [start, end]
    trim = {"enabled": bool(trim_warmup), "original_overlap_sim_s": original_overlap,
            "preroll_sim_s": .75, "selected_event": None, "removed_lead_sim_s": 0.}
    if trim_warmup:
        entry = next(((when, event) for when, event in events
                      if event.get("event") == "entry_started" and event.get("node_id") not in (None, "takeoff")), None)
        if entry is None:
            raise RuntimeError("Cannot trim warmup: actual non-takeoff entry_started event is missing")
        when, event = entry
        start = max(start, when-.75)
        if start >= end:
            raise RuntimeError("Actual route entry is outside the common recorder overlap")
        trim.update(selected_event={"event": "entry_started", "node_id": event["node_id"],
                    "absolute_sim_time_s": when, "run_simulation_elapsed_s": event["simulation_elapsed_s"]},
                    removed_lead_sim_s=start-original_overlap[0],
                    rule="Common native start = max(original overlap start, actual first route entry event minus 0.75 simulation seconds)")
    if pair_times[0] < start or pair_times[-1] >= end:
        raise RuntimeError("Recorder overlap omits actual capture work; preserve broader actual recordings")
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema_version":"1.0.0", "mission_id":mission["mission_id"], "result_file":str(result_file), "run_dir":str(run),
              "camera_checks":checks, "native_timeline":{"start_sim_s":start,"end_sim_s":end,"duration_s":end-start,
              "run_origin_sim_s":base, "observer_range_sim_s":[observer[0]["sim_time_s"],observer[-1]["sim_time_s"]],
              "drone_range_sim_s":[drone[0]["sim_time_s"],drone[-1]["sim_time_s"]],
              "alignment":"Shared native-simulation overlap; crop boundaries hold the latest already-recorded source image",
              "observer_manifest":str(observer_manifest),"drone_manifest":str(drone_manifest)},
              "pairs":{"total":len(pairs),"stop":sum(p["trigger"]["kind"]=="node" for p in pairs),
                       "in_flight":sum(p["trigger"]["kind"]=="travel" for p in pairs)},
              "trim_warmup":trim,
              "drone_display_color_conversion":drone_color,
              "source_linkage":{"observer":"result.observer.directory","drone_view": "result.drone_view.directory" if linked_drone else "explicit CLI folder; independently checked mirror metadata"},
              "sidepanel_display_timing":"Latest actual acquired pair at each actual observer timestamp; updates occur at recorded observer cadence",
              "image_display_resampling":"Aspect-preserving LANCZOS resize only; original saved files remain unchanged",
              "thermal_note":"Original saved ThermalIR PNG display signal. No contrast enhancement or recoloring; resizing only. Not calibrated temperatures.",
              "videos":{}}
    atomic_json(output/"manifest.json", report)
    off_nodes = {node["id"] for node in mission["nodes"] if node["settings"]["capture"]["mode"] == "off"}
    def state(stamp):
        phase, node, segment = phase_at(events, stamp)
        if phase == "STOP & CAPTURE" and node in off_nodes:
            phase = "NODE HOLD / CAPTURE OFF"
        count = bisect_right(pair_times, stamp)
        latest = pairs[count-1] if count else None
        return phase, node, segment, count, latest
    observer_plan, drone_plan = frame_plan(observer,start,end), frame_plan(drone,start,end)
    report["videos"]["fixed_observer"] = encode_vfr(observer_plan,output/"observer_frames",output/"01_fixed_observer.mp4",
        lambda image,item: annotate(image,item["display_sim_s"],state(item["display_sim_s"])[0],
                                   state(item["display_sim_s"])[3],(960,540),"MIXED ROUTE  /  FIXED OBSERVER"))
    atomic_json(output/"manifest.json", report)
    report["videos"]["live_drone_view"] = encode_vfr(drone_plan,output/"drone_frames",output/"02_live_drone_view.mp4",
        lambda image,item: annotate(linear_rgb_to_srgb(image) if drone_color["applied"] else image,
                                   item["display_sim_s"],state(item["display_sim_s"])[0],
                                   state(item["display_sim_s"])[3],(640,480),"LIVE DRONE VIEW  /  INDEPENDENT RENDER"))
    atomic_json(output/"manifest.json", report)
    report["videos"]["capture_showcase"] = encode_vfr(observer_plan,output/"showcase_frames",output/"03_capture_showcase.mp4",
        lambda image,item: composite(image,item["display_sim_s"],*state(item["display_sim_s"])[:3],
                                    state(item["display_sim_s"])[4],state(item["display_sim_s"])[3],len(pairs),start,end))
    report["pair_timeline"] = [{"pair_id":p["pair_id"],"absolute_acquisition_sim_s":p["_absolute_sim_s"],"trigger":p["trigger"],
                              "record":p["_record_path"],"rgb":p["images"]["rgb"]["_path"],"ir":p["images"]["ir"]["_path"]} for p in pairs]
    atomic_json(output/"manifest.json", report)
    print(json.dumps({"output":str(output),"manifest":str(output/"manifest.json"),"videos":report["videos"]},indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--drone-folder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trim-warmup", action="store_true",
                        help="Start 0.75 native simulation seconds before the actual first non-takeoff route entry event")
    args = parser.parse_args()
    encode(args.result,args.drone_folder,args.output,trim_warmup=args.trim_warmup)

