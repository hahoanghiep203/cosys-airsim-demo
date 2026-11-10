"""Offline contract/runtime tests. No Unreal editor or AirSim server is used."""
import copy
import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import route_capture as rc

ROOT = Path(__file__).resolve().parents[4]


def example():
    return rc.read_json(ROOT / "Docs/RouteCapture/mission.example.json")


def context(mission):
    return {"schema_version": "1.0.0", "vehicle_name": mission["connection"]["vehicle_name"],
            "world_to_meters": 100., "vehicle_origin_ue_cm": {"x": 100, "y": 200, "z": 300},
            "map_asset": mission["map_asset"], "sim_mode": "Multirotor",
            "active_profile": {"camera": {key: mission["camera"][key] for key in
                                ("width_px", "height_px", "horizontal_fov_deg", "projection")},
                               "thermal": {"display_window_k": mission["thermal"]["display_window_k"]}},
            "path_validation": {"clear": True, "clearance_m": 1.}}


class ContractTests(unittest.TestCase):
    def test_examples_and_all_demo_modes(self):
        for path in [ROOT/"Docs/RouteCapture/mission.example.json", *[ROOT/"Config/RouteCapture"/name for name in
                     ("at_nodes.json", "during_travel.json", "combined.json")]]:
            with self.subTest(path=path.name):
                authored, resolved, _ = rc.load_mission(path)
                self.assertEqual(len(resolved["segments"]), len(resolved["nodes"])-1)
                self.assertNotEqual(id(authored), id(resolved))

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp)/"mission.json"
            for value in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}'):
                path.write_text(value)
                with self.subTest(value=value), self.assertRaises(rc.MissionError):
                    rc.read_json(path)

    def test_schema_is_strict_and_versions_exact(self):
        for change in ({"schema_version": "1.1.0"}, {"unrecognised_option": True}, {"name": None}):
            value = example()
            value.update(change)
            with self.subTest(change=change), self.assertRaises(rc.MissionError):
                rc.load_mission(value)

    def test_capture_replaced_whole_and_authored_not_mutated(self):
        value = example()
        value["segments"][0]["settings"]["capture"] = {"mode": "distance_interval", "interval_m": .5}
        before = copy.deepcopy(value)
        authored, resolved, _ = rc.load_mission(value)
        effective = resolved["segments"][0]["settings"]
        self.assertEqual(effective["capture"], {"mode": "distance_interval", "interval_m": .5})
        self.assertEqual(effective["acceleration_mps2"], value["defaults"]["segment"]["acceleration_mps2"])
        self.assertEqual(value, before)
        self.assertEqual(authored, before)

    def test_semantics_after_inheritance(self):
        mutations = [
            lambda m: m["nodes"][1].update(id="A"),
            lambda m: m["segments"][0].update(to="C"),
            lambda m: m["segments"].pop(),
            lambda m: m["nodes"][1].update(position_cm=m["nodes"][0]["position_cm"]),
            lambda m: m["thermal"]["display_window_k"].update(min=500),
            lambda m: m["limits"].update(max_pairs=2),
            lambda m: m["defaults"]["node"].update(behavior="fly_through"),
            lambda m: m["nodes"][-1].update(settings={"behavior":"fly_through", "settle_time_ms":0,
                                                    "extra_hold_ms":0, "capture":{"mode":"off"}}),
        ]
        for index, mutation in enumerate(mutations):
            mission = example()
            mutation(mission)
            with self.subTest(case=index), self.assertRaises(rc.MissionError):
                rc.load_mission(mission)

    def test_spawn_frame_conversion_never_uses_current_position(self):
        mission = rc.load_mission(example())[1]
        resolved, saved = rc.resolve_context(mission, context(mission))
        self.assertEqual(resolved["nodes"][0]["position_ned_m"], {"x":-1.,"y":-2.,"z":0.})
        bad = dict(saved, vehicle_name="other")
        with self.assertRaises(rc.MissionError):
            rc.resolve_context(mission, bad)

    def test_profile_and_clearance_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission = example()
            runner = rc.MissionRunner(mission, temp, context(mission))
            runner._check_context()
            runner.context["active_profile"]["thermal"]["display_window_k"]["max"] = 900
            with self.assertRaises(rc.MissionError):
                runner._check_context()
            runner.context = context(mission)
            runner.context["path_validation"]["clear"] = False
            with self.assertRaises(rc.MissionError):
                runner._check_context()


class SchedulingTests(unittest.TestCase):
    def test_native_steps_during_acquisition_count_but_actual_freeze_and_user_pause_do_not(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission = example()
            values = iter([(10.,False),(10.05,True),(10.05,True),(10.15,False),(10.20,False)])
            runner = rc.MissionRunner(mission, temp, context(mission), clock=SimpleNamespace(read=lambda:next(values)))
            runner._clock()
            runner.acquiring = True
            runner._clock()
            self.assertAlmostEqual(runner.active_s, .05)
            runner._clock()
            self.assertAlmostEqual(runner.active_s, .05)  # Actual paused native time stayed flat.
            runner.paused = True
            runner._clock()
            self.assertAlmostEqual(runner.active_s, .05)  # Operator hover is excluded despite native advancement.
            runner.paused = False
            runner._clock()
            self.assertAlmostEqual(runner.active_s, .10)

    def test_segment_wall_rate_excludes_operator_pause_including_open_pause(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission = example()
            runner = rc.MissionRunner(mission, temp, context(mission), client=Mock())
            runner.prepare()
            now = [10.]
            with patch.object(rc.time, "monotonic", side_effect=lambda:now[0]):
                initial_pause = runner._paused_wall_at()
                now[0] = 12.
                rc.atomic_json(Path(temp)/"control.json", {"id":1,"command":"pause"})
                runner._command()
                now[0] = 17.
                during = runner._phase_wall_metrics(10., initial_pause)
                self.assertEqual(during, {"wall_duration_s":2.,"wall_duration_including_operator_pauses_s":7.,
                                         "operator_pause_wall_s":5.})
                rc.atomic_json(Path(temp)/"control.json", {"id":2,"command":"resume"})
                runner._command()
                now[0] = 20.
                ended = runner._phase_wall_metrics(10., initial_pause)
                self.assertEqual(ended, {"wall_duration_s":5.,"wall_duration_including_operator_pauses_s":10.,
                                        "operator_pause_wall_s":5.})

    def test_absolute_time_deadlines_skip_without_restarting(self):
        schedule = rc.IntervalSchedule({"mode":"time_interval", "interval_ms":100})
        self.assertEqual(schedule.due(.099, 0), (None, []))
        deadline, missed = schedule.due(.101, 0)
        self.assertAlmostEqual(deadline, .1)
        self.assertEqual(missed, [])
        deadline, missed = schedule.due(.401, 0)
        self.assertAlmostEqual(deadline, .4)
        self.assertEqual(len(missed), 2)
        self.assertAlmostEqual(missed[0], .2)
        self.assertAlmostEqual(missed[1], .3)
        self.assertEqual(schedule.due(.401, 0), (None, []))
        # Endpoints are excluded even when exactly on a deadline.
        self.assertEqual(schedule.due(.5, 0, completed=True), (None, []))

    def test_distance_latest_only_and_segment_reset(self):
        schedule = rc.IntervalSchedule({"mode":"distance_interval", "interval_m":.5})
        self.assertEqual(schedule.due(999, .49), (None, []))
        self.assertEqual(schedule.due(999, 1.6), (1.5, [.5, 1.]))
        self.assertEqual(rc.IntervalSchedule({"mode":"distance_interval", "interval_m":.5}).due(0, .5), (.5, []))

    def test_quaternion_sign_and_cross_track_geometry(self):
        q = rc.euler_quat({"pitch":-45,"yaw":90,"roll":0})
        self.assertAlmostEqual(rc.qangle(q, tuple(-x for x in q)), 0)
        halfway = rc.slerp((0,0,0,1), rc.euler_quat({"pitch":0,"yaw":90,"roll":0}), .5)
        self.assertAlmostEqual(rc.qangle((0,0,0,1), halfway), 45)
        self.assertEqual(rc.route_error((5,3,0), (0,0,0), (10,0,0)), (3., .5))
        self.assertEqual(rc.route_error((0,0,0), (0,0,0), (0,0,0)), (0., 1.))
        rotated = rc.qrotate(rc.euler_quat({"pitch":0,"yaw":90,"roll":0}), (2,0,0))
        self.assertAlmostEqual(rotated[0], 0)
        self.assertAlmostEqual(rotated[1], 2)

    def test_clock_pause_rebase_and_backwards_detection(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp)/"clock.json"
            origin = {"x":0,"y":0,"z":0}
            rc.atomic_json(path, {"simulation_time_s":4.,"paused":True,"world_origin_ue_cm":origin})
            clock = rc.NativeClock({"sim_clock_path":str(path), "world_origin_ue_cm":origin})
            self.assertEqual(clock.read(), (4., True))
            rc.atomic_json(path, {"simulation_time_s":3.,"paused":False,"world_origin_ue_cm":origin})
            with self.assertRaises(rc.MissionError):
                clock.read()
            rc.atomic_json(path, {"simulation_time_s":5.,"paused":False,"world_origin_ue_cm":{"x":1,"y":0,"z":0}})
            with self.assertRaises(rc.MissionError):
                clock.read()

    def test_clock_heartbeat_stall_detected_in_wall_time(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp)/"clock.json"
            rc.atomic_json(path, {"simulation_time_s":4.,"paused":True})
            now = [0.]
            clock = rc.NativeClock({"sim_clock_path":str(path)}, monotonic=lambda:now[0])
            clock.read()
            now[0] = 3.1
            with self.assertRaises(rc.MissionError):
                clock.read()

    def test_clock_transient_missing_or_shared_file_retries_real_data_only(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp)/"clock.json"
            rc.atomic_json(path, {"simulation_time_s":4.,"paused":False})
            clock = rc.NativeClock({"sim_clock_path":str(path)})
            self.assertEqual(clock.read(), (4.,False))
            original_read = rc.read_json
            attempts = []
            def transient_read(source):
                attempts.append(1)
                if len(attempts) == 1:
                    self.assertEqual(clock.previous, 4.)
                    raise FileNotFoundError("native publication gap")
                if len(attempts) == 2:
                    self.assertEqual(clock.previous, 4.)
                    error = PermissionError("clock shared briefly")
                    error.winerror = 32
                    raise error
                return original_read(source)
            rc.atomic_json(path, {"simulation_time_s":5.,"paused":False})
            with patch.object(rc, "read_json", side_effect=transient_read), patch.object(rc.time, "sleep"):
                self.assertEqual(clock.read(), (5.,False))
            self.assertEqual(len(attempts), 3)

    def test_clock_missing_file_retry_is_bounded_and_preserves_heartbeat(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp)/"clock.json"
            rc.atomic_json(path, {"simulation_time_s":4.,"paused":False})
            heartbeat_time = [0.]
            clock = rc.NativeClock({"sim_clock_path":str(path)}, monotonic=lambda:heartbeat_time[0])
            clock.read()
            previous_stamp, previous_heartbeat = clock.last_stamp, clock.last_change
            with patch.object(rc, "read_json", side_effect=FileNotFoundError("missing")) as read, \
                 patch.object(rc.time, "monotonic", side_effect=[0.,.03,.07,.11]), \
                 patch.object(rc.time, "sleep"):
                with self.assertRaisesRegex(rc.MissionError, "Cannot read native simulation clock"):
                    clock.read()
            self.assertEqual(read.call_count, 3)
            self.assertEqual(clock.previous, 4.)
            self.assertEqual(clock.last_stamp, previous_stamp)
            self.assertEqual(clock.last_change, previous_heartbeat)
            heartbeat_time[0] = 3.1
            # Its document reappearing unchanged cannot conceal a stalled writer.
            with self.assertRaisesRegex(rc.MissionError, "heartbeat stalled"):
                clock.read()


class StorageAndControlTests(unittest.TestCase):
    def test_atomic_json_retries_transient_windows_reader_without_partial_publish(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp)/"status.json"
            rc.atomic_json(path, {"state":"old"})
            original_replace = rc.os.replace
            attempts = []
            def replacement(source, target):
                attempts.append(1)
                if len(attempts) <= 2:
                    self.assertEqual(rc.read_json(path), {"state":"old"})
                    error = PermissionError("transient reader")
                    error.winerror = (5, 32)[len(attempts)-1]
                    raise error
                return original_replace(source, target)
            with patch.object(rc.os, "replace", side_effect=replacement), patch.object(rc.time, "sleep"):
                rc.atomic_json(path, {"state":"new"})
            self.assertEqual(len(attempts), 3)
            self.assertEqual(rc.read_json(path), {"state":"new"})
            self.assertFalse(list(Path(temp).glob("*.tmp")))

    def test_atomic_json_persistent_windows_error_expires_and_keeps_previous_document(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp)/"status.json"
            rc.atomic_json(path, {"state":"old"})
            error = PermissionError("persistent access denied")
            error.winerror = 33
            with patch.object(rc.os, "replace", side_effect=error) as replace, \
                 patch.object(rc.time, "monotonic", side_effect=[0.,.25,.5,.8]), \
                 patch.object(rc.time, "sleep"):
                with self.assertRaisesRegex(PermissionError, "persistent access denied"):
                    rc.atomic_json(path, {"state":"new"})
            self.assertEqual(replace.call_count, 3)
            self.assertEqual(rc.read_json(path), {"state":"old"})
            self.assertFalse(list(Path(temp).glob("*.tmp")))

    def test_atomic_json_unrelated_io_failure_does_not_retry(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            with patch.object(rc.os, "replace", side_effect=OSError("disk failure")) as replace, \
                 patch.object(rc.time, "sleep") as sleep:
                with self.assertRaisesRegex(OSError, "disk failure"):
                    rc.atomic_json(Path(temp)/"status.json", {"state":"new"})
            replace.assert_called_once()
            sleep.assert_not_called()

    def test_grounded_collision_baseline_allowed_but_fresh_inflight_event_fails(self):
        import airsim
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission = example()
            client = Mock()
            state = airsim.MultirotorState()
            state.landed_state = 0
            state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,0)
            collision = airsim.CollisionInfo()
            collision.has_collided, collision.object_name, collision.object_id = True, "Floor", 12
            collision.time_stamp = 1234567890123456789
            client.getMultirotorState.return_value = state
            client.simGetCollisionInfo.return_value = collision
            runner = rc.MissionRunner(mission, temp, context(mission), client=client)
            runner.prepare()
            runner._sample(force=True)
            self.assertEqual(runner.stats["collisions"], 0)
            self.assertEqual(runner.collision_baseline["source_timestamp_ns"], "1234567890123456789")
            self.assertEqual(runner.telemetry["collision"]["classification"], "historical_grounded_baseline")
            runner.api_owned = True
            state.landed_state = 1
            runner._sample()  # The same latched floor event is historical even after lift-off.
            self.assertEqual(runner.stats["collisions"], 0)
            collision.time_stamp += 1  # A fresh impact on that same actor is still fatal.
            with self.assertRaisesRegex(rc.MissionError, "Collision reported"):
                runner._sample()
            self.assertEqual(runner.stats["collisions"], 1)
            self.assertEqual(runner.telemetry["collision"]["classification"], "new_collision")
            rows = [json.loads(line) for line in (Path(temp)/"telemetry.jsonl").read_text().splitlines()]
            self.assertEqual(rows[-1]["collision"]["source_timestamp_ns"], "1234567890123456790")

    def test_initial_airborne_collision_is_not_accepted_as_ground_baseline(self):
        import airsim
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission, client = example(), Mock()
            state, collision = airsim.MultirotorState(), airsim.CollisionInfo()
            state.landed_state, collision.has_collided = 1, True
            collision.object_name, collision.time_stamp = "Wall", 123
            client.getMultirotorState.return_value = state
            client.simGetCollisionInfo.return_value = collision
            runner = rc.MissionRunner(mission, temp, context(mission), client=client)
            runner.prepare()
            with self.assertRaisesRegex(rc.MissionError, "Collision reported"):
                runner._sample()
            self.assertIsNone(runner.collision_baseline)

    def test_atomic_paired_commit_and_capacity_reserved_before_capture(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            writer = rc.PairWriter(temp, 1)
            self.assertTrue(writer.reserve())
            self.assertFalse(writer.reserve())
            record = {"pair_id":"000001", "_capture_started_wall":time.monotonic()}
            writer.submit(1, {"rgb":b"rgb", "ir":b"ir"}, record)
            ok, result = writer.results.get(timeout=3)
            self.assertTrue(ok, result)
            directory = Path(temp)/"pairs/000001"
            self.assertEqual((directory/"rgb.png").read_bytes(), b"rgb")
            self.assertEqual((directory/"ir.png").read_bytes(), b"ir")
            self.assertEqual(rc.read_json(directory/"record.json")["pair_id"], "000001")
            self.assertFalse(list((Path(temp)/"pairs").glob(".pending-*")))
            # A completed write remains reserved until the mission observes its result.
            self.assertFalse(writer.reserve())
            writer.release()
            self.assertTrue(writer.reserve())
            writer.release()
            writer.work.put(None)

    def test_failed_second_image_never_exposes_partial_pair(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            writer = rc.PairWriter(temp, 1)
            writer.reserve()
            original_open = Path.open
            def open_or_fail(path, *args, **kwargs):
                if path.name == "ir.png":
                    raise OSError("disk full")
                return original_open(path, *args, **kwargs)
            with patch.object(Path, "open", open_or_fail):
                writer.submit(1, {"rgb":b"rgb", "ir":b"ir"}, {"_capture_started_wall":time.monotonic()})
                ok, result = writer.results.get(timeout=3)
            self.assertFalse(ok)
            self.assertIn("disk full", result)
            self.assertFalse((Path(temp)/"pairs/000001").exists())
            writer.thread.join(.05)  # let cleanup complete
            self.assertFalse(list((Path(temp)/"pairs").glob(".pending-*")))
            writer.release()
            writer.work.put(None)

    def test_index_failure_counts_authoritative_committed_pair_before_abort(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission = example()
            runner = rc.MissionRunner(mission, temp, context(mission))
            runner.prepare()
            runner.writer = rc.PairWriter(temp, 1)
            runner.writer.reserve()
            record = {"pair_id":"000001", "_capture_started_wall":time.monotonic(),
                      "images":{"rgb":{"bytes":3},"ir":{"bytes":2}}, "trigger":{"kind":"node"}}
            original_open = Path.open
            def open_or_fail(path, *args, **kwargs):
                if path.name == "pairs.jsonl":
                    raise OSError("index locked")
                return original_open(path, *args, **kwargs)
            with patch.object(Path, "open", open_or_fail):
                runner.writer.submit(1, {"rgb":b"rgb", "ir":b"ir"}, record)
                runner.writer.work.join()
            with self.assertRaisesRegex(rc.MissionError, "committed but JSONL"):
                runner._collect()
            self.assertEqual(runner.committed, 1)
            self.assertEqual(runner.total_bytes, 5)
            self.assertTrue((Path(temp)/"pairs/000001/record.json").exists())
            self.assertEqual(runner.writer.pending, 0)
            runner.writer.work.put(None)

    def test_operation_wall_watchdog_expires_while_paused(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission = example()
            runner = rc.MissionRunner(mission, temp, context(mission))
            runner.paused = True
            runner.tick = Mock()
            with self.assertRaisesRegex(rc.MissionError, "wall watchdog"):
                runner._pause_wait(time.monotonic()-.01, "Segment")

    def test_stop_reacquires_position_after_braking_drift(self):
        import airsim
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission = example()
            client = Mock()
            runner = rc.MissionRunner(mission, temp, context(mission), client=client)
            node = runner.mission["nodes"][0]
            state = airsim.MultirotorState()
            target = rc.vec(node["position_ned_m"])
            state.kinematics_estimated.position = airsim.Vector3r(target[0]+.5,target[1],target[2])
            state.kinematics_estimated.linear_velocity = airsim.Vector3r(.3,0,0)
            runner.state = state
            runner._hold_position(node)
            self.assertLess(client.moveByVelocityAsync.call_args.args[0], 0)
            self.assertFalse(runner._node_hovering)

    def test_pause_resume_stop_idempotent_and_active_time_excludes_pause(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission = example()
            runner = rc.MissionRunner(mission, temp, context(mission), client=Mock())
            runner.prepare()
            values = iter([(10.,False), (11.,False), (12.,False), (15.,False), (16.,False)])
            runner.clock = SimpleNamespace(read=lambda:next(values))
            runner._clock()
            runner._clock()
            self.assertEqual(runner.active_s, 1)
            rc.atomic_json(Path(temp)/"control.json", {"id":1,"command":"pause"})
            runner._command()
            runner._command()
            runner.client.cancelLastTask.assert_called_once()
            self.assertTrue(runner.paused)
            runner._clock()
            runner._clock()
            self.assertEqual(runner.active_s, 1)
            rc.atomic_json(Path(temp)/"control.json", {"id":2,"command":"resume"})
            runner._command()
            runner._clock()
            self.assertEqual(runner.active_s, 2)
            rc.atomic_json(Path(temp)/"control.json", {"id":3,"command":"stop"})
            with self.assertRaises(rc.MissionStopped):
                runner._command()

    def test_recovery_cancels_restores_pause_and_verifies_hover(self):
        import airsim
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission = example()
            client = Mock()
            state = airsim.MultirotorState()
            state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,0)
            client.getMultirotorState.return_value = state
            runner = rc.MissionRunner(mission, temp, context(mission), client=client)
            runner.api_owned, runner.original_pause = True, False
            result = runner.recover()
            self.assertTrue(result["cancel"])
            self.assertTrue(result["hover"])
            client.simPause.assert_called_once_with(False)
            client.enableApiControl.assert_not_called()

    def test_rejected_capture_releases_capacity_and_aborts_bad_threshold(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission = example()
            mission["acquisition"]["abort_after_consecutive_bad_pairs"] = 1
            runner = rc.MissionRunner(mission, temp, context(mission))
            runner.prepare()
            runner.writer = rc.PairWriter(temp, 1)
            runner.tick = Mock()
            runner._request_pair = Mock(return_value=([], .01))
            with self.assertRaises(rc.MissionError):
                runner.capture({"kind":"node","scheduled":0,"actual":0}, mandatory=True)
            self.assertEqual(runner.committed, 0)
            self.assertEqual(runner.stats["rejected"], 1)
            self.assertEqual(runner.writer.pending, 0)
            self.assertTrue(runner.writer.reserve())
            runner.writer.release()
            runner.writer.work.put(None)

    def test_request_failure_restores_previous_pause_and_legacy_argument_counts(self):
        import airsim
        mission = rc.load_mission(example())[1]
        mission["coordinate_context"] = context(mission)
        client = Mock()
        client.simIsPause.side_effect = [True, True, True]
        client.client.call.side_effect = OSError("RPC unavailable")
        with patch.object(rc, "airsim_client", return_value=client):
            worker = rc.CaptureWorker(mission)
            worker.requests.put({"verify_freeze":False})
            ok, error = worker.results.get(timeout=3)
            self.assertFalse(ok)
            self.assertIn("RPC unavailable", str(error))
            self.assertEqual(client.simPause.call_args_list[0].args, (True,))
            self.assertEqual(client.simPause.call_args_list[-1].args, (True,))
            call = client.client.call.call_args
            self.assertEqual(call.args[0], "simGetImages")
            self.assertEqual(len(call.args), 3)  # endpoint name + two legacy args
            self.assertEqual([request.image_type for request in call.args[1]], [0,12])
            worker.requests.put(None)


class ClockSnapshotIntegrationTests(unittest.TestCase):
    def worker_result(self, directory, read_side_effect=None, stale=False, bounded_failure=False):
        import airsim
        path = directory/"clock.json"
        snapshot = {"simulation_time_s":4.,"paused":True}
        rc.atomic_json(path, snapshot)
        mission = rc.load_mission(example())[1]
        mission["coordinate_context"] = dict(context(mission), sim_clock_path=str(path))
        client = Mock()
        paused_state = [False]
        client.simIsPause.side_effect = lambda:paused_state[0]
        def publish_pause(paused):
            paused_state[0] = paused
            if paused:
                stamp = path.stat().st_mtime_ns
                rc.atomic_json(path, snapshot)
                rc.os.utime(path, ns=(stamp+1_000_000, stamp+1_000_000))
        client.simPause.side_effect = publish_pause
        client.getMultirotorState.return_value = airsim.MultirotorState()
        client.client.call.return_value = [response.to_msgpack() for response in ImageTests().responses(mission)]
        original_read = rc.read_json
        now = [0.]
        def monotonic():
            now[0] += .025
            return now[0]
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.object(rc, "airsim_client", return_value=client))
            stack.enter_context(patch.object(rc.time, "sleep"))
            read = stack.enter_context(patch.object(rc, "read_json", side_effect=read_side_effect or original_read))
            if stale:
                stack.enter_context(patch.object(rc.time, "time", return_value=path.stat().st_mtime+3.1))
            if bounded_failure:
                stack.enter_context(patch.object(rc.time, "monotonic", side_effect=monotonic))
            worker = rc.CaptureWorker(mission)
            try:
                worker.requests.put({"verify_freeze":True})
                result = worker.results.get(timeout=3)
            finally:
                worker.requests.put(None)
                worker.thread.join(timeout=1)
            calls = read.call_count
        if len(client.simPause.call_args_list) > 1:
            self.assertEqual(client.simPause.call_args_list[0].args, (True,))
        self.assertEqual(client.simPause.call_args_list[-1].args, (False,))
        return result, client, calls

    def test_capture_pause_and_freeze_reads_retry_missing_plain_permission_and_sharing(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            sharing = PermissionError("shared clock")
            sharing.winerror = 33
            snapshot = {"simulation_time_s":4.,"paused":True}
            result, client, calls = self.worker_result(Path(temp),
                [FileNotFoundError("publication gap"),PermissionError(13,"CRT access denied"),
                 snapshot,sharing,snapshot,snapshot])
            ok, value = result
            self.assertTrue(ok, value)
            self.assertEqual(value[2], 4.)
            self.assertEqual(calls, 6)
            client.client.call.assert_called_once()

    def test_capture_persistent_snapshot_denial_is_bounded_and_unfreezes(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            reads = [0]
            def failure_after_baseline(path):
                reads[0] += 1
                if reads[0] == 1:
                    return {"simulation_time_s":4.,"paused":False}
                raise PermissionError(13,"persistent clock denial")
            (ok, error), client, calls = self.worker_result(Path(temp), failure_after_baseline, bounded_failure=True)
            self.assertFalse(ok)
            self.assertIn("persistent clock denial", str(error))
            self.assertGreater(calls, 1)
            self.assertLessEqual(calls, 6)
            client.client.call.assert_not_called()

    def test_freeze_verification_still_rejects_advanced_time_after_transient_read_error(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            (ok, error), client, _ = self.worker_result(Path(temp),
                [{"simulation_time_s":4.,"paused":False}, {"simulation_time_s":4.,"paused":True}, PermissionError("transient"),
                 {"simulation_time_s":4.01,"paused":True}])
            self.assertFalse(ok)
            self.assertIn("advanced during acquisition freeze", str(error))
            client.client.call.assert_not_called()

    def test_stale_capture_clock_fails_and_restores_previous_pause(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            (ok, error), client, _ = self.worker_result(Path(temp), stale=True)
            self.assertFalse(ok)
            self.assertIn("heartbeat is stale", str(error))
            client.client.call.assert_not_called()

    def test_landing_snapshot_retries_permission_and_preserves_freshness_check(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            directory, mission = Path(temp), example()
            path = directory/"clock.json"
            snapshot = {"simulation_time_s":4.,"paused":False,"landing_validation":{"clear":True}}
            rc.atomic_json(path, snapshot)
            profile = dict(context(mission), sim_clock_path=str(path))
            runner = rc.MissionRunner(mission, temp, profile)
            with patch.object(rc, "read_json", side_effect=[PermissionError(13,"CRT access denied"), snapshot]), \
                 patch.object(rc.time, "sleep"):
                self.assertEqual(runner._read_landing_validation(), {"clear":True})
            with patch.object(rc.time, "time", return_value=path.stat().st_mtime+3.1):
                with self.assertRaisesRegex(rc.MissionError, "heartbeat is stale"):
                    runner._read_landing_validation()

    def test_malformed_clock_is_not_retried(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp)/"clock.json"
            path.write_text("{invalid")
            with patch.object(rc.time, "sleep") as sleep:
                with self.assertRaisesRegex(rc.MissionError, "Cannot read native simulation clock"):
                    rc.read_clock_snapshot(path)
            sleep.assert_not_called()

    def test_rapid_successive_captures_wait_for_new_publication_not_old_paused_snapshot(self):
        import airsim
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp)/"clock.json"
            rc.atomic_json(path, {"simulation_time_s":10.,"paused":True})
            mission = rc.load_mission(example())[1]
            mission["coordinate_context"] = dict(context(mission), sim_clock_path=str(path))
            client = Mock()
            paused, simulation_time, waits = [False], [10.], []
            client.simIsPause.side_effect = lambda:paused[0]
            client.simPause.side_effect = lambda value:paused.__setitem__(0, value)
            client.getMultirotorState.return_value = airsim.MultirotorState()
            client.client.call.return_value = []
            def publish_after_wait(seconds):
                if seconds == .02 and paused[0]:
                    waits.append(simulation_time[0])
                    simulation_time[0] += 1
                    stamp = path.stat().st_mtime_ns
                    rc.atomic_json(path, {"simulation_time_s":simulation_time[0],"paused":True})
                    rc.os.utime(path, ns=(stamp+1_000_000, stamp+1_000_000))
            with patch.object(rc, "airsim_client", return_value=client), \
                 patch.object(rc.time, "sleep", side_effect=publish_after_wait):
                worker = rc.CaptureWorker(mission)
                try:
                    frozen_times = []
                    for _ in range(2):
                        worker.requests.put({"verify_freeze":False})
                        ok, value = worker.results.get(timeout=3)
                        self.assertTrue(ok, value)
                        frozen_times.append(value[2])
                    self.assertEqual(frozen_times, [11.,12.])
                    self.assertEqual(waits, [10.,11.])
                    self.assertEqual(client.client.call.call_count, 2)
                    self.assertFalse(paused[0])
                finally:
                    worker.requests.put(None)
                    worker.thread.join(timeout=1)

    def test_new_publication_with_backwards_simulation_time_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            (ok, error), client, _ = self.worker_result(Path(temp),
                [{"simulation_time_s":5.,"paused":False}, {"simulation_time_s":4.,"paused":True}])
            self.assertFalse(ok)
            self.assertIn("moved backwards", str(error))
            client.client.call.assert_not_called()


class ImageTests(unittest.TestCase):
    def responses(self, mission):
        import airsim
        from PIL import Image
        stream = io.BytesIO()
        Image.new("RGB", (mission["camera"]["width_px"], mission["camera"]["height_px"]), (80,100,120)).save(stream, format="PNG")
        responses = []
        for kind, timestamp in ((0,1234567890123456789), (12,1234567890123456799)):
            value = airsim.ImageResponse()
            value.width, value.height = mission["camera"]["width_px"], mission["camera"]["height_px"]
            value.image_data_uint8, value.image_type, value.time_stamp = stream.getvalue(), kind, timestamp
            responses.append(value)
        return responses

    def test_per_image_original_timestamps_pose_and_alignment(self):
        mission = rc.load_mission(example())[1]
        images, metadata, quality = rc.validate_pair(self.responses(mission), mission)
        self.assertEqual(metadata["rgb"]["source_timestamp_ns"], "1234567890123456789")
        self.assertEqual(metadata["ir"]["source_timestamp_ns"], "1234567890123456799")
        self.assertEqual(quality["timestamp_delta_ns"], "10")
        self.assertFalse(quality["shared_render_frame_proven"])
        self.assertIn("not calibrated", metadata["ir"]["quality"]["signal"])
        self.assertEqual(set(images), {"rgb","ir"})

    def test_mismatched_pose_and_invalid_payload_rejected(self):
        import airsim
        mission = rc.load_mission(example())[1]
        responses = self.responses(mission)
        responses[1].camera_position = airsim.Vector3r(1,0,0)
        with self.assertRaises(rc.BadPair):
            rc.validate_pair(responses, mission)
        responses = self.responses(mission)
        responses[1].image_data_uint8 = b"not PNG"
        with self.assertRaises(rc.BadPair):
            rc.validate_pair(responses, mission)


class FakeAutopilotTests(unittest.TestCase):
    def test_controller_route_burst_and_periodic_pairs_complete_without_teleport(self):
        import airsim
        mission = example()
        mission["nodes"] = mission["nodes"][:2]
        mission["segments"] = mission["segments"][:1]
        mission["nodes"][0]["position_cm"] = {"x":0,"y":0,"z":100}
        mission["nodes"][1]["position_cm"] = {"x":100,"y":0,"z":100}
        for node in mission["nodes"]:
            node["camera_rotation_deg"] = {"pitch":0,"yaw":0,"roll":0}
        mission["nodes"][1]["settings"] = {"capture":{"mode":"burst","delay_ms":20,"count":2,"interval_ms":100}}
        mission["defaults"]["node"]["settle_time_ms"] = 50
        mission["defaults"]["node"]["arrival_radius_m"] = .1
        mission["defaults"]["segment"]["capture"] = {"mode":"time_interval","interval_ms":200}
        mission["segments"][0]["settings"] = {"capture":{"mode":"time_interval","interval_ms":200}}
        mission["thermal"]["warmup_ms"] = 0
        mission["camera"]["width_px"] = mission["camera"]["height_px"] = 16
        mission["metrics"]["record_image_quality"] = False
        mission["limits"]["max_pairs"] = 1000
        mission["limits"]["min_free_disk_mb"] = 0
        profile = context(mission)
        profile["vehicle_origin_ue_cm"] = {"x":0,"y":0,"z":0}
        class Client:
            def __init__(self):
                self.state = airsim.MultirotorState()
                self.state.landed_state = 1
                self.state.kinematics_estimated.position = airsim.Vector3r(0,0,-1)
                self.state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,0)
                self.orientation = airsim.Quaternionr()
                self.client = self
                self.motion_commands = 0
            def advance(self):
                p, v = self.state.kinematics_estimated.position, self.state.kinematics_estimated.linear_velocity
                self.state.kinematics_estimated.position = airsim.Vector3r(p.x_val+.05*v.x_val,p.y_val+.05*v.y_val,p.z_val+.05*v.z_val)
                self.state.timestamp += 50000000
            def getMultirotorState(self, **kwargs):
                return self.state
            def simGetCollisionInfo(self, **kwargs):
                return airsim.CollisionInfo()
            def call(self, endpoint, *args):
                if endpoint == "simSetCameraPose":
                    self.orientation = args[1].orientation
                    return None
                if endpoint == "simGetCameraInfo":
                    return {"pose":{"position":self.state.kinematics_estimated.position.to_msgpack(),
                                    "orientation":self.orientation.to_msgpack()}, "fov":65}
                raise AssertionError(endpoint)
            def enableApiControl(self, *args, **kwargs): pass
            def armDisarm(self, *args, **kwargs): return True
            def cancelLastTask(self, **kwargs): pass
            def simPause(self, *args): pass
            def hoverAsync(self, **kwargs):
                self.state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,0)
            def moveByVelocityAsync(self, x, y, z, duration, **kwargs):
                self.motion_commands += 1
                self.state.kinematics_estimated.linear_velocity = airsim.Vector3r(x,y,z)
        client = Client()
        class Clock:
            seconds = 0.
            def read(self):
                self.seconds += .05
                client.advance()
                return self.seconds, False
        class Runner(rc.MissionRunner):
            def preflight(self):
                self.prepare()
                self._check_context()
                self._clock()
                self._sample()
                self.original_pause = False
                self.mount_position, self.mount_q = (0.,0.,0.), (0.,0.,0.,1.)
            def _request_pair(self):
                responses = ImageTests().responses(self.mission)
                for response in responses:
                    response.camera_position = client.state.kinematics_estimated.position
                    response.camera_orientation = client.orientation
                self.frozen_telemetry = dict(self.telemetry)
                return responses, .001
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            runner = Runner(mission, temp, profile, client=client, clock=Clock())
            original_sleep = time.sleep
            with patch.object(rc.time, "sleep", lambda seconds:original_sleep(.0005)):
                result = runner.run()
            self.assertEqual(result["state"], "completed", result)
            self.assertGreater(client.motion_commands, 0)
            summary = rc.read_json(Path(temp)/"summary.json")
            self.assertEqual(summary["nodes_completed"], 2)
            self.assertGreater(summary["valid_travel_pairs"], 0)
            self.assertEqual(summary["nodes"][1]["mandatory_committed"], 2)
            self.assertEqual(summary["pairs"], len(list((Path(temp)/"pairs").glob("[0-9]*"))))
            self.assertTrue(all(spacing >= .1-1e-8 for spacing in summary["nodes"][1]["actual_burst_spacing_sim_s"]))


class IndependentRecoveryTests(unittest.TestCase):
    def exercise_cli_landing(self, collision_case="floor", baseline_events=False, landing_timeout_s=30., firmware=None):
        import airsim
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            directory = Path(temp)
            mission = example()
            mission["limits"]["min_free_disk_mb"] = 0
            mission["flight"]["takeoff"]["timeout_s"] = landing_timeout_s
            virtual_wall = [0.]
            profile = context(mission)
            profile["vehicle_origin_ue_cm"] = {"x":0,"y":0,"z":0}
            profile["sim_clock_path"] = str(directory/"clock.json")
            if firmware is not None:
                profile["vehicle_type"] = firmware
            baseline = {"has_collided":True, "object_name":"Floor", "object_id":12,
                        "source_timestamp_ns":"100", "impact_point_ned_m":{"x":0,"y":0,"z":0},
                        "position_ned_m":{"x":0,"y":0,"z":-.1}, "normal_ned":{"x":0,"y":0,"z":-1},
                        "penetration_depth_m":0.}
            original_summary = {"state":"failed", "grounded_collision_baseline":baseline, "retained":True}
            if baseline_events:
                (directory/"events.jsonl").write_text(json.dumps({"event":"grounded_collision_baseline", "collision":baseline})+"\n")
            else:
                rc.atomic_json(directory/"summary.json", original_summary)
            rc.atomic_json(directory/"authored_input.json", mission)
            rc.atomic_json(directory/"context.json", profile)
            class Client:
                def __init__(self):
                    self.state = airsim.MultirotorState()
                    self.state.landed_state = 1
                    self.state.kinematics_estimated.position = airsim.Vector3r(0,0,-1)
                    self.state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,0)
                    self.collision = airsim.CollisionInfo()
                    self.collision.has_collided, self.collision.object_name, self.collision.object_id = True,"Floor",12
                    self.collision.time_stamp = 100
                    self.collision.impact_point = airsim.Vector3r(0,0,0)
                    self.collision.position = airsim.Vector3r(0,0,-.1)
                    self.collision.normal = airsim.Vector3r(0,0,-1)
                    self.descending, self.descent_samples, self.clock_s = False,0,0.
                    self.contact_started_wall = None
                    self.land_timeouts = []
                    self.pwm_calls = []
                    self.cancelLastTask, self.simPause = Mock(),Mock()
                    self.armDisarm, self.enableApiControl = Mock(return_value=True),Mock()
                    self.hover_calls = 0
                    self.publish()
                def publish(self):
                    self.clock_s += .1
                    rc.atomic_json(directory/"clock.json", {"simulation_time_s":self.clock_s,"paused":False,
                        "landing_validation":{"clear":self.state.kinematics_estimated.position.z_val < -.5,
                            "position_ned_m":rc.xyz(rc.vec(self.state.kinematics_estimated.position)),
                            "clearance_m":.5,"tolerance_m":.5,"ground_position_ue_cm":{"x":0,"y":0,"z":0},
                            "ground_actor_name":"Floor"}})
                def isApiControlEnabled(self, **kwargs): return True
                def getMultirotorState(self, **kwargs):
                    if self.descending:
                        self.descent_samples += 1
                        if self.descent_samples == 1:
                            self.state.kinematics_estimated.position = airsim.Vector3r(0,0,-.5)
                            self.state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,.5)
                        else:
                            self.state.kinematics_estimated.position = airsim.Vector3r(0,0,-.1)
                            self.state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,0)
                            self.state.landed_state = 0
                            self.collision.time_stamp = 200
                            if collision_case == "wall":
                                self.collision.object_name = "Wall"
                                self.collision.normal = airsim.Vector3r(1,0,0)
                            elif collision_case == "other_actor":
                                self.collision.object_name = "Box"
                            elif collision_case == "higher_surface":
                                self.collision.impact_point = airsim.Vector3r(0,0,-1)
                            elif collision_case == "measured_footprint":
                                self.collision.impact_point = airsim.Vector3r(.33381,.13656,0)
                            elif collision_case == "footprint_edge":
                                self.collision.impact_point = airsim.Vector3r(.499,0,0)
                            elif collision_case == "outside_footprint":
                                self.collision.impact_point = airsim.Vector3r(.501,0,0)
                            elif collision_case == "near_wrong_height":
                                self.collision.impact_point = airsim.Vector3r(0,0,-.16)
                            elif collision_case == "high_speed":
                                self.state.landed_state = 1
                                self.state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,.5)
                            elif collision_case.startswith("motor_"):
                                self.state.landed_state = 1
                                self.state.kinematics_estimated.angular_velocity = airsim.Vector3r(0,0,0)
                                if collision_case.startswith("motor_angular_"):
                                    values = [0.,0.,0.]
                                    values[int(collision_case[-1])] = .081
                                    self.state.kinematics_estimated.angular_velocity = airsim.Vector3r(*values)
                                elif collision_case.startswith("motor_linear_"):
                                    values = [0.,0.,0.]
                                    values[int(collision_case[-1])] = .081
                                    self.state.kinematics_estimated.linear_velocity = airsim.Vector3r(*values)
                                elif collision_case == "motor_dwell_reset" and self.descent_samples == 4:
                                    self.state.kinematics_estimated.angular_velocity = airsim.Vector3r(.09,0,0)
                                if self.pwm_calls:
                                    if collision_case == "motor_new_impact":
                                        self.collision.time_stamp = 201
                                    elif collision_case in ("motor_success", "motor_dwell_reset"):
                                        self.state.landed_state = 0
                            elif collision_case in ("delayed_floor", "delayed_floor_cleared", "pending_then_wall",
                                                    "unconfirmed", "unconfirmed_cleared", "slow_backend"):
                                if collision_case == "slow_backend" and self.contact_started_wall is None:
                                    self.contact_started_wall = virtual_wall[0]
                                if (self.descent_samples == 2 or collision_case.startswith("unconfirmed") or
                                        (collision_case == "slow_backend" and virtual_wall[0]-self.contact_started_wall < 5.)):
                                    self.state.landed_state = 1
                                    self.state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,.203)
                                if collision_case == "delayed_floor":
                                    self.collision.impact_point = airsim.Vector3r(.33381,.13656,0)
                                if self.descent_samples > 2:
                                    if collision_case in ("delayed_floor_cleared", "unconfirmed_cleared"):
                                        self.collision.has_collided = False
                                    elif collision_case == "pending_then_wall":
                                        self.collision.object_name = "Wall"
                                        self.collision.normal = airsim.Vector3r(1,0,0)
                    self.publish()
                    return self.state
                def simGetCollisionInfo(self, **kwargs): return self.collision
                def hoverAsync(self, **kwargs):
                    self.hover_calls += 1
                    self.descending = False
                    self.state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,0)
                def landAsync(self, **kwargs):
                    self.land_timeouts.append(kwargs["timeout_sec"])
                    self.descending = True
                def moveByMotorPWMsAsync(self, *args, **kwargs):
                    self.pwm_calls.append({"args":args,"kwargs":kwargs,"sample":self.descent_samples})
                    future = Mock()
                    future.join.side_effect = AssertionError("Motor future must never be blindly joined")
                    return future
                def getRotorStates(self, **kwargs):
                    return SimpleNamespace(timestamp=123, rotors=[{"speed":10.,"thrust":2.} for _ in range(4)])
            client = Client()
            from contextlib import ExitStack
            with patch.object(rc, "airsim_client", return_value=client), \
                 patch.object(rc.time, "sleep"), patch.object(sys, "stdout", io.StringIO()), ExitStack() as stack:
                if collision_case.startswith(("unconfirmed", "motor_")) or collision_case == "slow_backend":
                    def advancing_wall():
                        virtual_wall[0] += .01 if collision_case.startswith("motor_") else .1
                        return virtual_wall[0]
                    stack.enter_context(patch.object(rc.time, "monotonic", side_effect=advancing_wall))
                exit_code = rc.main(["--mission",str(directory/"authored_input.json"),"--run-dir",str(directory),
                                     "--context",str(directory/"context.json"),"--recover","land"])
            result = rc.read_json(directory/"recovery.json")
            if not baseline_events:
                self.assertEqual(rc.read_json(directory/"summary.json"), original_summary)
            self.assertFalse((directory/"mission.json").exists())
            self.assertTrue(result["cancel"])
            self.assertTrue(result["unfreeze"])
            self.assertTrue(result["hover"])
            self.assertEqual(client.land_timeouts, [min(60., landing_timeout_s)])
            motor_success = collision_case in ("motor_success", "motor_dwell_reset") and firmware == "simpleflight"
            if collision_case in ("floor", "delayed_floor", "delayed_floor_cleared", "measured_footprint", "footprint_edge", "slow_backend") or motor_success:
                self.assertEqual(exit_code, 0, result)
                self.assertTrue(result["landed"])
                self.assertEqual(result["verified_touchdown"]["classification"], "verified_landing_touchdown")
                client.armDisarm.assert_called_once_with(False, vehicle_name="")
                client.enableApiControl.assert_called_once_with(False, vehicle_name="")
                if collision_case == "slow_backend":
                    self.assertGreaterEqual(virtual_wall[0]-client.contact_started_wall, 5.)
                if motor_success:
                    report = result["simpleflight_motor_settle"]
                    self.assertEqual(report["state"], "confirmed_landed")
                    self.assertEqual(report["returned_landed_state"], 0)
                    self.assertGreaterEqual(report["dwell_wall_s"], .25)
                    self.assertGreaterEqual(report["dwell_sim_s"], .25)
                    self.assertLessEqual(report["actual_wall_duration_s"], 2.)
                    self.assertTrue(client.pwm_calls)
                    for command in client.pwm_calls:
                        self.assertEqual(command["args"], (.05,.05,.05,.05,.2))
                    if collision_case == "motor_dwell_reset":
                        self.assertGreaterEqual(client.pwm_calls[0]["sample"], 8)
                if collision_case.startswith("delayed_floor"):
                    rows = [json.loads(line) for line in (directory/"telemetry.jsonl").read_text().splitlines()]
                    pending = [row for row in rows if row["collision"]["classification"] == "authorized_ground_contact_pending_landed"]
                    self.assertTrue(pending)
                    self.assertEqual(pending[0]["landed_state"], 1)
                    self.assertAlmostEqual(pending[0]["speed_mps"], .203)
                    self.assertEqual(rows[-1]["landed_state"], 0)
            else:
                self.assertEqual(exit_code, 1, result)
                self.assertFalse(result["landed"])
                self.assertTrue(result["landing_cancelled_then_hover_requested"])
                self.assertGreaterEqual(client.cancelLastTask.call_count, 3)
                self.assertGreaterEqual(client.hover_calls, 2)
                client.armDisarm.assert_not_called()
                client.enableApiControl.assert_not_called()
                if collision_case.startswith(("unconfirmed", "motor_")):
                    self.assertTrue(any("Landed" in error or "Ground contact" in error or "SimpleFlight motor settle" in error
                                        for error in result["errors"]), result)
                else:
                    self.assertTrue(any("Collision reported" in error for error in result["errors"]), result)
            if collision_case.startswith("motor_"):
                if firmware != "simpleflight" or collision_case.startswith(("motor_angular_", "motor_linear_")):
                    self.assertFalse(client.pwm_calls)
                    self.assertNotIn("simpleflight_motor_settle", result)
                elif collision_case in ("motor_timeout", "motor_new_impact"):
                    self.assertTrue(client.pwm_calls)
                    report = result["simpleflight_motor_settle"]
                    self.assertEqual(report["state"], "failed")
                    self.assertTrue(report["cancelled_and_hover_requested"])
                    self.assertLessEqual(report["watchdog_target_wall_s"], 2.)
                    self.assertGreaterEqual(report["actual_wall_duration_s"], 0.)
                    self.assertEqual(report["requested_rpc_timeout_s"], .2)
                    self.assertIn("not a hard 200 ms bound", report["rpc_timeout_note"])
                    self.assertIn("does not guarantee hover", report["watchdog_note"])
                    self.assertNotIn("maximum_wall_s", report)

    def test_cli_recover_land_initializes_clock_restores_baseline_and_verifies_touchdown(self):
        self.exercise_cli_landing()

    def test_cli_recover_land_can_restore_baseline_from_events(self):
        self.exercise_cli_landing(baseline_events=True)

    def test_landing_obstacle_wall_wrong_actor_wrong_surface_or_fast_contact_aborts(self):
        for case in ("wall","other_actor","higher_surface","high_speed"):
            with self.subTest(case=case):
                self.exercise_cli_landing(case)

    def test_landing_ground_contact_can_precede_landed_state(self):
        self.exercise_cli_landing("delayed_floor")

    def test_landed_confirmation_survives_collision_flag_clearing(self):
        self.exercise_cli_landing("delayed_floor_cleared")

    def test_ground_contact_confirmation_timeout_cancels_descent_and_retains_api(self):
        for case in ("unconfirmed", "unconfirmed_cleared"):
            with self.subTest(case=case):
                self.exercise_cli_landing(case, landing_timeout_s=3.)

    def test_backend_confirmation_after_five_seconds_uses_configured_watchdog(self):
        self.exercise_cli_landing("slow_backend", landing_timeout_s=10.)

    def test_configured_landing_watchdog_is_capped_at_sixty_seconds(self):
        self.exercise_cli_landing("unconfirmed_cleared", landing_timeout_s=120.)

    def test_simpleflight_grounded_motor_settle_requires_actual_landed_before_handoff(self):
        self.exercise_cli_landing("motor_success", landing_timeout_s=6., firmware="simpleflight")

    def test_motor_settle_is_disabled_for_unknown_and_px4_firmware(self):
        for firmware in (None, "px4", "SimpleFlight"):
            with self.subTest(firmware=firmware):
                self.exercise_cli_landing("motor_success", landing_timeout_s=3., firmware=firmware)

    def test_every_linear_and_angular_axis_blocks_motor_settle_above_detector_tolerance(self):
        for kind in ("angular", "linear"):
            for axis in range(3):
                with self.subTest(kind=kind,axis=axis):
                    self.exercise_cli_landing(f"motor_{kind}_{axis}", landing_timeout_s=3., firmware="simpleflight")

    def test_motor_stability_dwell_restarts_after_angular_motion(self):
        self.exercise_cli_landing("motor_dwell_reset", landing_timeout_s=6., firmware="simpleflight")

    def test_motor_failure_duration_includes_cancel_and_hover_cleanup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            mission, client = example(), Mock()
            runner = rc.MissionRunner(mission, temp, context(mission), client=client)
            runner.event = Mock()
            runner.motor_settle_report = {"started_wall":10., "rotor_diagnostics":[]}
            now = [10.]
            def cancel(**kwargs): now[0] += .2
            def hover(**kwargs): now[0] += .3
            client.cancelLastTask.side_effect = cancel
            client.hoverAsync.side_effect = hover
            with patch.object(rc.time, "monotonic", side_effect=lambda:now[0]):
                runner._abort_motor_settle("transport stalled")
            self.assertAlmostEqual(runner.motor_settle_report["actual_wall_duration_s"], .5)
            self.assertTrue(runner.motor_settle_report["cancelled_and_hover_requested"])

    def test_motor_failure_is_bounded_and_explicitly_replaces_pwm_with_hover(self):
        self.exercise_cli_landing("motor_timeout", landing_timeout_s=6., firmware="simpleflight")

    def test_motor_settle_never_extends_original_landing_deadline(self):
        self.exercise_cli_landing("motor_timeout", landing_timeout_s=1.5, firmware="simpleflight")

    def test_new_impact_during_motor_settle_aborts_without_disarming(self):
        self.exercise_cli_landing("motor_new_impact", landing_timeout_s=6., firmware="simpleflight")

    def test_wall_impact_during_pending_ground_contact_is_not_ignored(self):
        self.exercise_cli_landing("pending_then_wall")

    def test_validated_footprint_accepts_measured_offset_and_near_radius_edge(self):
        for case in ("measured_footprint", "footprint_edge"):
            with self.subTest(case=case):
                self.exercise_cli_landing(case)

    def test_outside_footprint_and_surface_height_mismatch_remain_fatal(self):
        for case in ("outside_footprint", "near_wrong_height"):
            with self.subTest(case=case):
                self.exercise_cli_landing(case)

    def test_cli_hover_recovers_despite_historical_collision_and_stale_clock(self):
        import airsim
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            directory, mission = Path(temp), example()
            profile = context(mission)
            profile["sim_clock_path"] = str(directory/"missing_clock.json")
            rc.atomic_json(directory/"mission_input.json", mission)
            rc.atomic_json(directory/"context.json", profile)
            client, state = Mock(), airsim.MultirotorState()
            state.landed_state = 1
            state.kinematics_estimated.linear_velocity = airsim.Vector3r(0,0,0)
            client.isApiControlEnabled.return_value = True
            client.getMultirotorState.return_value = state
            with patch.object(rc, "airsim_client", return_value=client), patch.object(sys, "stdout", io.StringIO()):
                result = rc.main(["--mission",str(directory/"mission_input.json"),"--run-dir",str(directory),
                                  "--context",str(directory/"context.json"),"--recover","hover"])
            self.assertEqual(result, 0)
            client.cancelLastTask.assert_called_once()
            client.simPause.assert_called_once_with(False)
            client.hoverAsync.assert_called_once()
            client.simGetCollisionInfo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
