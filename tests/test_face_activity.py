import unittest
from fleet.face_activity import FaceActivity
from fleet.face_preview import behavior_label
from fleet.model_detector import prediction_to_readings
from fleet.phone_speed import PhoneSpeed
from fleet.risk import Measurements, RiskEngine


class ActivityTests(unittest.TestCase):
    def test_side_mount_uses_road_reference_for_label_and_alert(self):
        pose = FaceActivity.__new__(FaceActivity)
        pose.reset_mount()
        pose.start_calibration("parked")
        for yaw in (39, 40, 41, 40, 40):
            relative = pose.relative_yaw(yaw)
        self.assertEqual(relative, 0)
        engine = RiskEngine()
        for yaw, label, level in ((40, "Facing forward", "LOW"), (5, "Looking aside", "HIGH")):
            for _ in range(7):
                r = prediction_to_readings("turning", .95)
                relative = pose.relative_yaw(yaw)
                pose.resolve_turn(r, relative)
                pose.apply(r, .1, .1, relative)
                r.speed = 45
                risk = engine.update(r)
            self.assertEqual(behavior_label(r.behavior, r.confidence, r.face_activity), label)
            self.assertEqual(risk.level, level)
        pose.reset_mount()
        self.assertIsNone(pose.forward_yaw)

    def test_closed_eyes_visible_without_gps_and_alert_when_moving(self):
        for speed, expected in ((None, "UNKNOWN"), (0, "LOW"), (45, "HIGH")):
            readings = prediction_to_readings("other_activities", .5)
            FaceActivity.apply(readings, .8, .9, 0)
            if speed is None:
                PhoneSpeed().apply(readings)
            else:
                readings.speed = speed
            readings = Measurements.from_dict(readings.to_dict())
            self.assertEqual(behavior_label(readings.behavior, readings.confidence, readings.face_activity), "Eyes closed")
            engine = RiskEngine()
            for _ in range(3):
                result = engine.update(readings)
            self.assertEqual(result.level, expected)

    def test_turn_is_visible_even_while_manoeuvring(self):
        readings = prediction_to_readings("safe_driving", .95)
        FaceActivity.apply(readings, .1, .2, -35)
        self.assertEqual(behavior_label(readings.behavior, readings.confidence, readings.face_activity), "Looking aside")
        readings.speed = 5
        engine = RiskEngine()
        for _ in range(12):
            result = engine.update(readings)
        self.assertEqual(result.level, "LOW")
