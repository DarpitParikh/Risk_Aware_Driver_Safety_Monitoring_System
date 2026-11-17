from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
import time
from unittest.mock import patch

from fleet.device import DeviceSession, Outbox
from fleet.demo import DemoFleet
from fleet.network import ApiClient, ApiError
from fleet.risk import Measurements, RiskResult
from fleet.server import FleetServer
from fleet.storage import Store, utc_now
from fleet.ui_common import vehicle_status


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = Store(self.path / "test.sqlite3")
        self.store.seed()
        self.server = FleetServer(("127.0.0.1", 0), self.store, "owner-test", "device-test")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.owner = ApiClient(self.url, "owner-test")
        self.device = ApiClient(self.url, "device-test")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def sample(self, level="LOW", score=0):
        return {"id": str(uuid.uuid4()), "vehicle_id": 1, "trip_id": 1, "captured_at": utc_now(),
                "readings": Measurements(speed=40).to_dict(), "risk": RiskResult(score, level, "Test event").to_dict()}

    def test_authentication_and_owner_only_operations(self):
        with self.assertRaises(ApiError) as error:
            ApiClient(self.url, "wrong").request("/snapshot")
        self.assertEqual(error.exception.status, 401)
        with self.assertRaises(ApiError) as error:
            self.device.request("/entity", {"kind": "vehicles", "values": {}})
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(len(self.owner.request("/snapshot")["vehicles"]), 3)

    def test_duplicate_submission_is_idempotent_and_only_transitions_logged(self):
        sample = self.sample()
        self.device.request("/telemetry", sample)
        self.device.request("/telemetry", sample)
        self.device.request("/telemetry", self.sample())
        self.device.request("/telemetry", self.sample("HIGH", 75))
        self.assertEqual(len(self.owner.request("/logs")), 2)
        self.assertEqual(len(self.owner.request("/logs?level=HIGH&vehicle_id=1&driver_id=1")), 1)
        snapshot = self.owner.request("/snapshot")
        self.assertEqual(snapshot["vehicles"][0]["sample"]["level"], "HIGH")

    def test_phone_frame_sensor_sample_and_vehicle_isolation(self):
        from fleet.android_driver import AndroidSensors, PhoneDriver
        from fleet.model_detector import prediction_to_readings
        from io import BytesIO
        import base64
        import queue
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow required for phone camera")
        buffer = BytesIO()
        Image.new("RGB", (32, 32)).save(buffer, "JPEG")
        frame = base64.b64encode(buffer.getvalue()).decode()
        phone = PhoneDriver.__new__(PhoneDriver)
        phone.session = DeviceSession(1, self.device, self.path / "phone.db")
        phone.session.refresh_assignment()
        phone.sensors = AndroidSensors(1)
        phone.sensors.gps.accept({"timestamp": time.time(), "speed_mps": 10, "accuracy_m": 3})
        phone.sensors.motion = time.monotonic(), {"gyroscope": [1, 2, 3], "accelerometer": [0, 1, 9]}
        phone.messages = queue.Queue()
        phone.stop = threading.Event()
        phone.last_frame = None
        phone.last_alarm = 0
        with patch.object(phone.sensors, "capture", return_value=frame), patch.object(
                self.server, "classify", return_value=prediction_to_readings("turning", .95)):
            phone.assess()
        phone.session.synchronize()
        snapshot = self.owner.request("/snapshot")["vehicles"]
        self.assertEqual(snapshot[0]["sample"]["readings"]["speed"], 36)
        self.assertEqual(snapshot[0]["sample"]["readings"]["gyroscope"], [1, 2, 3])
        self.assertEqual(snapshot[0]["sample"]["readings"]["behavior"], "turning")
        self.assertIsNone(snapshot[1]["sample"])
        self.assertEqual(self.owner.request("/frame/1", raw=True), buffer.getvalue())

    def test_busy_driver_assignment_does_not_end_existing_trip(self):
        with self.assertRaises(ApiError):
            self.owner.request("/assign", {"vehicle_id": 1, "driver_id": 2, "route_id": 1})
        self.assertEqual(self.store.assignment(1)["id"], 1)

    def test_reassignment_preserves_historical_names_and_trip(self):
        self.device.request("/telemetry", self.sample("HIGH", 75))
        self.owner.request("/entity", {"kind": "drivers", "values": {"id": 1, "name": "Renamed driver", "license": "NEW-DL", "phone": ""}})
        result = self.owner.request("/assign", {"vehicle_id": 1, "driver_id": 1, "route_id": 2})
        self.assertNotEqual(result["trip_id"], 1)
        self.assertEqual(self.store.assignment(1)["driver_name"], "Renamed driver")
        self.assertEqual(self.owner.request("/logs")[0]["driver_name"], "Aarav Shah")
        old_trip = next(t for t in self.store.snapshot()["trips"] if t["id"] == 1)
        self.assertIsNotNone(old_trip["ended_at"])

    def test_late_valid_sample_preserved_but_post_trip_sample_rejected(self):
        queued = self.sample("HIGH", 75)
        self.owner.request("/end-trip", {"trip_id": 1})
        self.device.request("/telemetry", queued)
        invalid = self.sample()
        invalid["captured_at"] = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(timespec="milliseconds")
        with self.assertRaises(ApiError):
            self.device.request("/telemetry", invalid)

    def test_persistent_outbox_replays_after_connection_returns(self):
        session = DeviceSession(1, self.device, self.path / "outbox.sqlite3")
        session.refresh_assignment()
        session.evaluate(Measurements(speed=40, eyes_closed=True), 1)
        risk = session.evaluate(Measurements(speed=40, eyes_closed=True), 1)
        self.assertEqual(risk.level, "HIGH")
        reopened = Outbox(self.path / "outbox.sqlite3")
        self.assertEqual(reopened.count(), 2)
        reopened.flush(self.device)
        self.assertEqual(reopened.count(), 0)
        self.assertEqual(self.store.snapshot()["vehicles"][0]["sample"]["level"], "HIGH")

    def test_network_failure_does_not_interrupt_local_risk(self):
        session = DeviceSession(1, self.device, self.path / "outbox.sqlite3")
        session.refresh_assignment()
        with patch.object(self.device, "request", side_effect=ApiError("Offline")):
            self.assertEqual(session.synchronize(), "Offline")
            session.evaluate(Measurements(speed=40, eyes_closed=True), 1)
            self.assertEqual(session.evaluate(Measurements(speed=40, eyes_closed=True), 1).level, "HIGH")
            self.assertEqual(session.outbox.count(), 2)
        self.assertEqual(session.synchronize(), "Connected")
        self.assertEqual(session.outbox.count(), 0)

    def test_multiple_demo_devices_reach_server_independently(self):
        demo = DemoFleet(self.url, "device-test", self.path)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                vehicles = self.store.snapshot()["vehicles"]
                if all(v["sample"] for v in vehicles if v["id"] in (2, 3)):
                    break
                time.sleep(0.1)
            for vehicle in vehicles[1:]:
                self.assertIsNotNone(vehicle["sample"])
                self.assertEqual(vehicle["sample"]["trip_id"], vehicle["trip"]["id"])
                self.assertEqual(vehicle["sample"]["readings"]["source"], "simulation")
        finally:
            demo.close()

    def test_permanent_rejection_retained_without_blocking_queue(self):
        outbox = Outbox(self.path / "outbox.sqlite3")
        bad = self.sample()
        bad["trip_id"] = 999
        outbox.put(bad)
        outbox.put(self.sample())
        outbox.flush(self.device)
        self.assertEqual(outbox.count(), 0)
        with outbox.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rejected").fetchone()[0], 1)

    def test_stale_data_cannot_show_online_even_if_just_replayed(self):
        stale = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
        vehicle = {"trip": {"id": 1}, "sample": {"captured_at": stale, "received_at": utc_now(), "level": "LOW"}}
        self.assertEqual(vehicle_status(vehicle), "OFFLINE")

    def test_invalid_telemetry_does_not_crash_server(self):
        malformed = self.sample()
        malformed["readings"]["speed"] = -10
        with self.assertRaises(ApiError) as error:
            self.device.request("/telemetry", malformed)
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(self.owner.request("/health")["status"], "ok")

    def test_model_provenance_and_prediction_survive_server_storage(self):
        from fleet.model_detector import prediction_to_readings
        sample = self.sample("HIGH", 80)
        sample["readings"] = prediction_to_readings("texting_phone", 0.95, 24).to_dict()
        self.device.request("/telemetry", sample)
        readings = self.owner.request("/snapshot")["vehicles"][0]["sample"]["readings"]
        self.assertEqual(readings["source"], "trained_model")
        self.assertEqual(readings["motion_source"], "simulation")
        self.assertEqual(readings["behavior"], "texting_phone")
        self.assertEqual(readings["confidence"], 0.95)
        self.assertIsNone(readings["face_visible"])

    def test_real_camera_frame_transport_and_trip_boundary(self):
        import base64
        jpeg = b"\xff\xd8test-frame\xff\xd9"
        self.device.request("/camera", {"vehicle_id": 1, "trip_id": 1, "jpeg": base64.b64encode(jpeg).decode()})
        self.assertEqual(self.owner.request("/frame/1", raw=True), jpeg)
        self.owner.request("/assign", {"vehicle_id": 1, "driver_id": 1, "route_id": 2})
        with self.assertRaises(ApiError) as error:
            self.owner.request("/frame/1", raw=True)
        self.assertEqual(error.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
