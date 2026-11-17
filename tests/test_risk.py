import unittest
from fleet.risk import Measurements, RiskEngine


class RiskTests(unittest.TestCase):
    def test_blink_is_not_drowsiness(self):
        engine = RiskEngine()
        self.assertEqual(engine.update(Measurements(speed=40, eyes_closed=True), 0.3).level, "LOW")
        self.assertEqual(engine.update(Measurements(speed=40), 1).level, "LOW")

    def test_sustained_eye_closure_and_recovery(self):
        engine = RiskEngine()
        engine.update(Measurements(speed=40, eyes_closed=True), 1)
        self.assertEqual(engine.update(Measurements(speed=40, eyes_closed=True), 1).level, "HIGH")
        for _ in range(2):
            self.assertEqual(engine.update(Measurements(speed=40), 1).level, "HIGH")
        self.assertEqual(engine.update(Measurements(speed=40), 1).level, "LOW")

    def test_unavailable_face_is_unknown_and_resets_duration(self):
        engine = RiskEngine()
        engine.update(Measurements(speed=40, eyes_closed=True), 1.5)
        self.assertEqual(engine.update(Measurements(speed=40, face_visible=False), 1).level, "UNKNOWN")
        self.assertEqual(engine.update(Measurements(speed=40, eyes_closed=True), 0.5).level, "LOW")

    def test_stopped_vehicle_suppresses_alert_and_duration(self):
        engine = RiskEngine()
        for _ in range(10):
            self.assertEqual(engine.update(Measurements(eyes_closed=True), 1).level, "LOW")
        self.assertEqual(engine.update(Measurements(speed=40, eyes_closed=True), 1).level, "LOW")

    def test_combined_risk_and_long_phone_use(self):
        engine = RiskEngine()
        for _ in range(3):
            result = engine.update(Measurements(speed=40, phone_use=True, looking_away=True))
        self.assertEqual(result.level, "HIGH")
        self.assertLessEqual(result.score, 100)
        engine = RiskEngine()
        for _ in range(5):
            result = engine.update(Measurements(speed=40, phone_use=True))
        self.assertEqual(result.level, "HIGH")

    def test_repeated_yawns_and_expiration(self):
        engine = RiskEngine()
        for _ in range(3):
            result = engine.update(Measurements(speed=40, yawning=True))
            engine.update(Measurements(speed=40))
        self.assertEqual(result.level, "CAUTION")
        for _ in range(65):
            result = engine.update(Measurements(speed=40))
        self.assertEqual(result.level, "LOW")

    def test_validation_rejects_invalid_sensor_values(self):
        for values in ({"speed": float("nan")}, {"speed": 300}, {"face_visible": "false"}, {"acceleration": float("inf")}, {"speed": True}):
            with self.assertRaises(ValueError):
                Measurements.from_dict(values)


if __name__ == "__main__":
    unittest.main()
