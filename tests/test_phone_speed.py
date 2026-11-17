import time
import unittest
import importlib.util
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from fleet.phone_speed import PhoneSpeed, PhoneSpeedServer
from fleet.risk import Measurements, RiskEngine


class PhoneSpeedTests(unittest.TestCase):
    def setUp(self):
        self.gps = PhoneSpeed()
        self.now = time.time()

    def send(self, speed=10, accuracy=5, stamp=None):
        self.gps.accept({"timestamp": self.now if stamp is None else stamp,
                         "speed_mps": speed, "accuracy_m": accuracy}, now=self.now)

    def test_conversion_and_wire_roundtrip(self):
        self.send()
        result = self.gps.apply(Measurements(), now=self.now)
        self.assertEqual(result.speed, 36)
        self.assertEqual(Measurements.from_dict(result.to_dict()).motion_source, "phone_gps")

    def test_missing_stale_and_uncertain_are_unknown(self):
        for speed, accuracy, age in ((None, 5, 0), (10, 80, 0), (10, 5, 6)):
            self.gps = PhoneSpeed()
            self.send(speed, accuracy)
            readings = self.gps.apply(Measurements(), now=self.now+age)
            self.assertEqual(RiskEngine().update(readings).level, "UNKNOWN")
        self.assertEqual(RiskEngine().update(PhoneSpeed().apply(Measurements())).level, "UNKNOWN")

    def test_bad_and_replayed_fixes(self):
        for value in (-1, float("nan"), float("inf"), True, "10", 100):
            with self.assertRaises(ValueError):
                self.send(value)
        self.send()
        with self.assertRaises(ValueError):
            self.send()
        with self.assertRaises(ValueError):
            self.send(stamp=self.now-10)

    def test_zero_is_valid_and_acceleration_not_invented(self):
        self.send(0)
        result = self.gps.apply(Measurements(acceleration=-8), now=self.now)
        self.assertTrue(result.assessment_available)
        self.assertEqual(result.acceleration, 0)
        self.assertEqual(RiskEngine().update(result).level, "LOW")

    def test_behavior_uncertainty_preserved(self):
        self.send()
        result = self.gps.apply(Measurements(assessment_available=False, assessment_note="Camera missing"), now=self.now)
        self.assertFalse(result.assessment_available)
        self.assertEqual(result.assessment_note, "Camera missing")

    def test_low_speed_allowance_and_fast_attention(self):
        for speed, expected in ((2, "LOW"), (15, "HIGH")):
            self.gps = PhoneSpeed()
            self.send(speed)
            engine = RiskEngine()
            for _ in range(8):
                result = engine.update(self.gps.apply(Measurements(looking_away=True), now=self.now))
            self.assertEqual(result.level, expected)

    @unittest.skipUnless(importlib.util.find_spec("cryptography"), "Optional certificate package not installed")
    def test_trusted_https_pairing_and_speed_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            certs = Path(folder) / "certs"
            tool = Path(__file__).resolve().parents[1] / "tools" / "create_gps_certificate.py"
            subprocess.run([sys.executable, str(tool), "127.0.0.1", "--output", str(certs)], check=True, capture_output=True)
            context = ssl.create_default_context(cafile=str(certs / "phone-ca.crt"))
            server = PhoneSpeedServer(("127.0.0.1", 0), certs / "server.crt", certs / "server.key")
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"https://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/", context=context, timeout=3) as response:
                    self.assertIn(b"watchPosition", response.read())
                body = json.dumps({"timestamp": time.time(), "speed_mps": 10, "accuracy_m": 5}).encode()
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(base+"/speed", data=body), context=context, timeout=3)
                self.assertEqual(caught.exception.code, 401)
                request = Request(base+"/speed", data=body, headers={"Authorization": "Bearer " + server.token})
                with urlopen(request, context=context, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                self.assertEqual(server.speed.apply(Measurements()).speed, 36)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)
