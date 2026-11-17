import unittest

from fleet.attention import AttentionPolicy, SpeedContext
from fleet.model_detector import prediction_to_readings
from fleet.risk import Measurements, RiskEngine


class AttentionTests(unittest.TestCase):
    def readings(self, speed, model=False):
        result = prediction_to_readings("turning", 0.95) if model else Measurements(looking_away=True)
        result.speed = speed
        return result

    def test_slow_manoeuvring_does_not_alert_even_for_a_long_time(self):
        for speed in (0, 3, 7, 10):
            for model in (False, True):
                engine = RiskEngine()
                for _ in range(120):
                    result = engine.update(self.readings(speed, model))
                    self.assertEqual(result.level, "LOW")

    def test_moderate_and_fast_thresholds_for_both_sources(self):
        for speed, caution, high in ((20, 5, 10), (30, 5, 10), (45, 3, 6)):
            for model in (False, True):
                engine = RiskEngine()
                for second in range(1, high + 1):
                    result = engine.update(self.readings(speed, model))
                    expected = "HIGH" if second >= high else "CAUTION" if second >= caution else "LOW"
                    self.assertEqual(result.level, expected, (speed, second, model))

    def test_phone_and_eye_rules_are_not_relaxed_at_manoeuvring_speed(self):
        for model in (False, True):
            engine = RiskEngine()
            readings = prediction_to_readings("texting_phone", 0.95) if model else Measurements(phone_use=True, looking_away=True)
            readings.speed = 7
            for _ in range(5):
                result = engine.update(readings)
            self.assertEqual(result.level, "HIGH")
        engine = RiskEngine()
        for _ in range(2):
            result = engine.update(Measurements(speed=7, eyes_closed=True, looking_away=True))
        self.assertEqual(result.level, "HIGH")

    def test_acceleration_does_not_reuse_manoeuvring_duration(self):
        engine = RiskEngine()
        for _ in range(60):
            engine.update(self.readings(5, True))
        for _ in range(2):
            self.assertEqual(engine.update(self.readings(45, True)).level, "LOW")
        for _ in range(2):
            self.assertEqual(engine.update(self.readings(45, True)).level, "LOW")
        self.assertEqual(engine.update(self.readings(45, True)).level, "CAUTION")

    def test_brief_speed_spike_does_not_change_band(self):
        context = SpeedContext(AttentionPolicy())
        context.update(5, 1)
        for speed in (45, 5, 45, 5):
            self.assertFalse(context.update(speed, 1))
        self.assertEqual(context.band, "manoeuvring")

    def test_boundary_jitter_does_not_toggle_band(self):
        context = SpeedContext(AttentionPolicy())
        context.update(20, 1)
        for _ in range(10):
            for speed in (29, 31, 30, 32):
                self.assertFalse(context.update(speed, 1))
        self.assertEqual(context.band, "moderate")

    def test_zero_elapsed_does_not_confirm_speed_transition(self):
        context = SpeedContext(AttentionPolicy())
        context.update(5, 0)
        for _ in range(100):
            self.assertFalse(context.update(45, 0))
        self.assertEqual(context.band, "manoeuvring")

    def test_speed_reduction_clears_existing_attention_warning_after_recovery(self):
        engine = RiskEngine()
        for _ in range(6):
            engine.update(self.readings(45, True))
        for _ in range(3):
            result = engine.update(self.readings(5, True))
        self.assertEqual(result.level, "LOW")
        self.assertIn("manoeuvring", result.reason)
        for _ in range(20):
            self.assertEqual(engine.update(self.readings(5, True)).level, "LOW")

    def test_unknown_camera_stays_unknown_at_low_speed(self):
        readings = prediction_to_readings("turning", 0.3)
        readings.speed = 5
        self.assertEqual(RiskEngine().update(readings).level, "UNKNOWN")
