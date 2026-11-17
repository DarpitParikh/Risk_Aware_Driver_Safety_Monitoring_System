"""Complement the driving classifier with observable eye and head movements."""
import math
import statistics
import time
from pathlib import Path


class FaceActivity:
    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        path = Path(__file__).resolve().parents[1] / "models" / "face_landmarker.task"
        options = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(path)),
            output_face_blendshapes=True, output_facial_transformation_matrixes=True)
        self.model = vision.FaceLandmarker.create_from_options(options)
        self.mp = mp
        self.reset_mount()

    def reset_mount(self):
        self.forward_yaw = None
        self.samples = []
        self.calibrating = False
        self.last_pose = 0
        self.calibration_id = None
        self.mount_note = ""

    def start_calibration(self, request_id):
        if request_id and request_id != self.calibration_id:
            self.reset_mount()
            self.calibration_id = request_id
            self.calibrating = True
            self.mount_note = "Look at the road and hold your head still."

    def relative_yaw(self, yaw):
        if self.calibrating:
            now = time.monotonic()
            if now - self.last_pose > 2:
                self.samples.clear()
            self.last_pose = now
            self.samples = (self.samples + [yaw])[-5:]
            if len(self.samples) == 5 and max(self.samples)-min(self.samples) <= 8:
                self.forward_yaw = statistics.median(self.samples)
                self.calibrating = False
                self.mount_note = "Road-facing position saved"
            else:
                return None
        return yaw if self.forward_yaw is None else (yaw-self.forward_yaw+180)%360-180

    def close(self):
        self.model.close()

    def observe(self, jpeg, readings):
        import cv2
        import numpy as np
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.model.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb))
        if not result.face_blendshapes or not result.facial_transformation_matrixes:
            if self.calibrating:
                self.samples.clear()
                self.mount_note = "Face unavailable. Adjust the mount so the camera sees both eyes."
            self.resolve_turn(readings, None)
            return
        scores = {s.category_name: s.score for s in result.face_blendshapes[0]}
        rotation = result.facial_transformation_matrixes[0]
        yaw = math.degrees(math.atan2(rotation[0, 2], rotation[2, 2]))
        yaw = self.relative_yaw(yaw)
        if self.calibrating:
            self.mount_note = f"Look at the road and hold still ({len(self.samples)}/5)"
        self.resolve_turn(readings, yaw)
        self.apply(readings, scores["eyeBlinkLeft"], scores["eyeBlinkRight"], yaw)

    def resolve_turn(self, readings, yaw):
        # The image classifier sees camera-relative turns. Once calibrated,
        # only road-relative pose can confirm its turning prediction.
        if readings.behavior == "turning" and (self.calibrating or self.forward_yaw is not None):
            if yaw is None or abs(yaw) < 25:
                readings.behavior = "unconfirmed_activity"
                readings.confidence = 0
                readings.assessment_available = yaw is not None
                readings.assessment_note = "" if yaw is not None else "Waiting for a reliable road-relative head position"

    @staticmethod
    def apply(readings, left_blink, right_blink, yaw):
        readings.face_activity = "Facing forward" if yaw is not None else ""
        if min(left_blink, right_blink) >= .55:
            readings.face_activity = "Eyes closed"
            readings.eyes_closed = True
        elif yaw is not None and abs(yaw) >= 25:
            readings.face_activity = "Looking aside"
            readings.looking_away = True
        if readings.eyes_closed or readings.looking_away:
            readings.assessment_available = True
            readings.assessment_note = ""
