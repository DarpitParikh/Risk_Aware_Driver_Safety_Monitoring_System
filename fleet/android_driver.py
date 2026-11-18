"""Tkinter vehicle terminal for Android with Termux:API and Termux:X11."""
import base64
from io import BytesIO
import json
import logging
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk

from .device import DeviceSession
from .driver_alarm import DriverAlarm
from .model_detector import unavailable_readings
from .network import ApiClient, ApiError
from .phone_speed import PhoneSpeed
from .risk import Measurements


def command(*args, timeout=8):
    return subprocess.run(args, capture_output=True, text=True, check=True,
                          timeout=timeout).stdout


class AndroidSensors:
    """Read Android hardware off the UI thread. Expire missing or old readings."""
    def __init__(self, camera_id):
        self.camera_id = str(camera_id)
        self.gps = PhoneSpeed()
        self.motion = (0, {})

    def update_gps(self):
        fix = json.loads(command("termux-location", "-p", "gps", "-r", "once", timeout=20))
        age = fix["elapsedMs"] / 1000
        self.gps.accept({"timestamp": time.time() - age, "speed_mps": fix["speed"],
                         "accuracy_m": fix["accuracy"]})

    def update_motion(self):
        packet = json.loads(command("termux-sensor", "-s", "Accelerometer,Gyroscope", "-n", "1"))
        vectors = {}
        for name, sensor in packet.items():
            for kind in ("accelerometer", "gyroscope"):
                if kind in name.lower() and "uncalibrated" not in name.lower():
                    values = sensor.get("values", [])
                    if len(values) >= 3:
                        vectors[kind] = [round(float(v), 3) for v in values[:3]]
        self.motion = time.monotonic(), vectors

    def add_motion(self, readings):
        self.gps.apply(readings)
        timestamp, vectors = self.motion
        if time.monotonic() - timestamp <= 5:
            readings.accelerometer = vectors.get("accelerometer")
            readings.gyroscope = vectors.get("gyroscope")

    def capture(self):
        from PIL import Image, ImageOps
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "frame.jpg"
            command("termux-camera-photo", "-c", self.camera_id, str(path))
            with Image.open(path) as photo:
                photo = ImageOps.exif_transpose(photo).convert("RGB")
                photo.thumbnail((640, 640))
                output = BytesIO()
                photo.save(output, "JPEG", quality=65)
        return base64.b64encode(output.getvalue()).decode("ascii")


class PhoneDriver:
    """Collect phone readings, evaluate risk locally and display the active trip."""
    def __init__(self, root, session, sensors):
        self.root, self.session, self.sensors = root, session, sensors
        self.stop = threading.Event()
        self.messages = queue.Queue()
        self.last_frame = None
        self.alarm = DriverAlarm(root)
        root.title("Fleet Guardian • Driver")
        panel = ttk.Frame(root, padding=16)
        panel.pack(fill="both", expand=True)
        self.assignment = ttk.Label(panel, text=f"Vehicle {session.vehicle_id}")
        self.assignment.pack()
        self.status = ttk.Label(panel, text="Ready", wraplength=330, justify="center")
        self.status.pack(pady=10)
        self.start_button = ttk.Button(panel, text="Start sensors and share camera", command=self.start)
        self.start_button.pack()
        ttk.Button(panel, text="End monitoring", command=self.close).pack(pady=6)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(200, self.refresh)

    def start(self):
        self.start_button.state(["disabled"])
        self.status.configure(text="Connecting to fleet manager…")
        for action, pause in ((self.sensors.update_gps, 0.3), (self.sensors.update_motion, 0.5),
                              (self.session.synchronize, 1), (self.assess, 0.3)):
            threading.Thread(target=self.repeat, args=(action, pause), daemon=True).start()

    def repeat(self, action, pause):
        while not self.stop.is_set():
            try:
                action()
            except Exception as error:
                logging.warning("%s: %s", action.__name__, error)
            self.stop.wait(pause)

    def assess(self):
        trip = self.session.current_trip()
        if not trip:
            self.last_frame = None
            self.messages.put(("No active assignment", self.session.connection, False))
            return
        start = time.monotonic()
        try:
            jpeg = self.sensors.capture()
            capture_time = time.monotonic()
            response = self.session.api.request("/phone-frame", {"vehicle_id": self.session.vehicle_id,
                "trip_id": trip["id"], "jpeg": jpeg})
            if time.monotonic() - capture_time > 2.5:
                raise ValueError("Camera prediction expired")
            readings = Measurements.from_dict(response["readings"])
        except (OSError, subprocess.SubprocessError, ApiError, ValueError, ImportError) as error:
            readings = unavailable_readings(("Phone camera assessment unavailable: " + str(error))[:250])
        if self.stop.is_set() or self.session.current_trip() != trip:
            self.last_frame = None
            return
        gap = start - self.last_frame if self.last_frame is not None else 0
        if gap > 3:
            self.session.reset_risk()
            gap = 0
        self.last_frame = start
        self.sensors.add_motion(readings)
        risk = self.session.evaluate(readings, gap)
        speed = "GPS unavailable" if "GPS" in readings.assessment_note else f"{readings.speed:.1f} km/h"
        text = f"{risk.level}   {speed}\n{readings.behavior.replace('_', ' ')}\n{risk.reason}"
        alarm = risk.level == "HIGH"
        self.messages.put((f"{trip['driver_name']} • {trip['route_name']}", text, alarm))

    def refresh(self):
        while not self.messages.empty():
            trip, state, alarm = self.messages.get_nowait()
            self.assignment.configure(text=trip)
            self.status.configure(text=state)
            if alarm and not self.alarm.active:
                try:
                    subprocess.Popen(["termux-tts-speak", "Driver safety warning"])
                except OSError:
                    logging.warning("Android speech unavailable")
            self.alarm.set_active(alarm)
        self.root.after(200, self.refresh)

    def close(self):
        self.stop.set()
        self.root.destroy()


def run_phone(args):
    api = ApiClient(args.server, args.token)
    session = DeviceSession(args.vehicle, api, args.data_dir / f"phone-{args.vehicle}-outbox.sqlite3")
    root = tk.Tk()
    PhoneDriver(root, session, AndroidSensors(args.camera))
    root.mainloop()
