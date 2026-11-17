"""Prediction semantics, freshness, and real exported-model CPU checks."""
import importlib.util
import unittest

from fleet.model_detector import (DEFAULT_MODEL, LatestObservation, TrainedDetector,
                                  prediction_to_readings, unavailable_readings)
from fleet.risk import Measurements, RiskEngine


class PredictionTests(unittest.TestCase):
    def test_phone_classes_feed_temporal_risk(self):
        for label in ("talking_phone", "texting_phone"):
            engine = RiskEngine()
            readings = prediction_to_readings(label, 0.95)
            readings.speed = 45
            for _ in range(5):
                result = engine.update(readings)
            self.assertEqual(result.level, "HIGH")
            self.assertIn("predicted phone", result.reason)

    def test_other_activities_never_becomes_drowsiness(self):
        readings = prediction_to_readings("other_activities", 0.99)
        readings.speed = 45
        self.assertFalse(readings.eyes_closed)
        self.assertFalse(readings.yawning)
        self.assertIsNone(readings.face_visible)
        self.assertEqual(RiskEngine().update(readings).level, "UNKNOWN")

    def test_low_score_is_unknown_not_safe(self):
        readings = prediction_to_readings("safe_driving", 0.40)
        readings.speed = 45
        self.assertEqual(RiskEngine().update(readings).level, "UNKNOWN")

    def test_turning_at_speed_requires_time_before_high_warning(self):
        engine = RiskEngine()
        readings = prediction_to_readings("turning", 0.95)
        readings.speed = 45
        self.assertFalse(readings.looking_away)
        self.assertEqual(engine.update(readings).level, "LOW")
        for _ in range(20):
            result = engine.update(readings)
        self.assertEqual(result.level, "HIGH")
        self.assertIn("45 km/h", result.reason)

    def test_model_data_round_trips_without_claiming_real_speed_or_face(self):
        original = prediction_to_readings("texting_phone", 0.95, 24.0)
        restored = Measurements.from_dict(original.to_dict())
        self.assertEqual(restored, original)
        self.assertEqual(restored.motion_source, "simulation")
        self.assertIsNone(restored.face_visible)
        invalid = original.to_dict()
        invalid["eyes_closed"] = True
        with self.assertRaises(ValueError):
            Measurements.from_dict(invalid)

    def test_prediction_validation_rejects_nan_and_bad_classes(self):
        for label, score in (("sleeping", 0.9), ("safe_driving", float("nan")), ("turning", 1.1)):
            with self.assertRaises(ValueError):
                prediction_to_readings(label, score)

    def test_switching_sources_resets_previous_alarm(self):
        engine = RiskEngine()
        for _ in range(3):
            engine.update(Measurements(speed=45, eyes_closed=True))
        readings = prediction_to_readings("safe_driving", 0.95)
        readings.speed = 45
        result = engine.update(readings)
        self.assertEqual(result.level, "LOW")
        self.assertIn("drowsiness is not measured", result.reason)

    def test_missing_prediction_clears_old_duration(self):
        engine = RiskEngine()
        readings = prediction_to_readings("texting_phone", 0.95)
        readings.speed = 45
        for _ in range(5):
            engine.update(readings)
        self.assertEqual(engine.update(unavailable_readings("Camera off")).level, "UNKNOWN")
        self.assertEqual(engine.update(readings).level, "LOW")

    def test_repainting_one_frame_cannot_accumulate_risk(self):
        engine = RiskEngine()
        readings = prediction_to_readings("texting_phone", 0.95)
        readings.speed = 45
        for _ in range(100):
            result = engine.update(readings, elapsed=0)
        self.assertEqual(result.level, "LOW")

    def test_latest_observation_expires_and_drops_inflight_old_mode(self):
        latest = LatestObservation()
        old_ticket = latest.ticket()
        latest.publish(prediction_to_readings("texting_phone", 0.95), 10, old_ticket)
        value, capture = latest.read_with_time(now=11)
        self.assertEqual(capture, 10)
        value.speed = 45
        self.assertEqual(latest.read(now=11).speed, 0)
        self.assertFalse(latest.read(now=13).assessment_available)
        latest.reset("Camera off")
        latest.publish(prediction_to_readings("safe_driving", 0.99), 14, old_ticket)
        self.assertFalse(latest.read(now=14).assessment_available)


HAS_MODEL_RUNTIME = (DEFAULT_MODEL.exists() and importlib.util.find_spec("torch") is not None
                     and importlib.util.find_spec("torchvision") is not None)


@unittest.skipUnless(HAS_MODEL_RUNTIME, "Install requirements-model.txt for CPU model checks")
class ExportedModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = TrainedDetector()

    def test_export_loads_on_cpu_and_matches_saved_parameters(self):
        import torch
        saved = torch.load(DEFAULT_MODEL, map_location="cpu", weights_only=True)
        self.assertEqual(str(next(self.detector.model.parameters()).device), "cpu")
        self.assertFalse(self.detector.model.training)
        self.assertEqual(self.detector.classes, ["other_activities", "safe_driving", "talking_phone", "texting_phone", "turning"])
        self.assertTrue(torch.equal(self.detector.model.classifier[-1].weight, saved["model_state"]["classifier.3.weight"]))

    def test_bgr_conversion_and_preprocessing_match_training(self):
        import numpy as np
        import torch
        from PIL import Image
        from torchvision import transforms
        frame = np.zeros((180, 320, 3), dtype=np.uint8)
        frame[:, :, 0] = 255  # OpenCV blue, not RGB red.
        reference = transforms.Compose([
            transforms.Resize((224, 224)), transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])(Image.fromarray(frame[:, :, ::-1].copy())).unsqueeze(0)
        with torch.inference_mode():
            scores = self.detector.model(reference).softmax(1)[0]
        result = self.detector.read(frame)
        self.assertEqual(result.behavior, self.detector.classes[scores.argmax().item()])
        self.assertAlmostEqual(result.confidence, scores.max().item(), places=5)
        self.assertGreater(result.inference_ms, 0)
        self.assertEqual(Measurements.from_dict(result.to_dict()), result)

    def test_empty_frame_is_unknown(self):
        self.assertFalse(self.detector.read(None).assessment_available)

    def test_high_phone_score_without_handset_cannot_raise_phone_alert(self):
        from unittest.mock import patch
        import numpy as np
        import torch
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        logits = torch.zeros((1, 5))
        logits[0, self.detector.classes.index("talking_phone")] = 10
        with patch.object(self.detector.model, "forward", return_value=logits):
            # Exercise actual COCO weights on a frame containing no objects.
            absent = self.detector.read(frame)
            self.assertEqual(absent.behavior, "unconfirmed_activity")
            self.assertFalse(Measurements.from_dict(absent.to_dict()).phone_use)
            with patch.object(self.detector, "handset_visible", return_value=True):
                self.assertTrue(self.detector.read(frame).phone_use)
