"""Driver window: manual simulation or local model inference with optional sharing."""
import base64
from io import BytesIO
import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from .detectors import ManualDetector
from .driver_alarm import DriverAlarm
from .model_detector import DEFAULT_MODEL, LatestObservation, TrainedDetector
from .network import ApiError
from .risk import Measurements
from .ui_common import COLORS, setup_style


class DriverApp:
    def __init__(self, root, session, camera_index=0, model_path=DEFAULT_MODEL, phone_speed=None):
        self.root, self.session = root, session
        self.camera_index = camera_index
        self.model_path = model_path
        self.phone_speed = phone_speed
        self.detector = ManualDetector()
        self.stop = threading.Event()
        self.camera_enabled = threading.Event()
        self.model_enabled = threading.Event()
        self.sharing_enabled = threading.Event()
        self.observation = LatestObservation()
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.events = queue.Queue(maxsize=20)
        self.last_tick = time.monotonic()
        self.last_prediction_time = None
        self.alarm = DriverAlarm(root)
        self.high_risk = False
        self.sound_test = None
        root.title(f"Fleet Guardian • Vehicle {session.vehicle_id}")
        root.geometry("650x940")
        root.minsize(610, 620)
        setup_style(root)
        self.build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self.network_worker, daemon=True).start()
        threading.Thread(target=self.camera_worker, daemon=True).start()
        root.after(500, self.tick)

    def build(self):
        panel = ttk.Frame(self.root, padding=20)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=f"Vehicle {self.session.vehicle_id}", style="Title.TLabel").pack(anchor="w")
        self.assignment = ttk.Label(panel, text="Waiting for assignment…", wraplength=550)
        self.assignment.pack(anchor="w", pady=(4, 12))
        self.risk_label = tk.Label(panel, text="INITIALIZING", bg="#64748b", fg="white", font=("Segoe UI", 23, "bold"), pady=12)
        self.risk_label.pack(fill="x")
        self.reason = ttk.Label(panel, text="", wraplength=550)
        self.reason.pack(anchor="w", pady=10)
        self.connection = ttk.Label(panel, text="Connecting…", style="Subtitle.TLabel", wraplength=550)
        self.connection.pack(anchor="w")
        self.prediction_label = ttk.Label(panel, text="Behavior and motion: simulated", wraplength=600)
        self.prediction_label.pack(anchor="w", pady=(4, 0))
        # The image must not force controls off-screen in compact mode.
        camera_area = tk.Frame(panel, bg="#14283f", height=40)
        camera_area.pack(fill="both", expand=True, pady=10)
        self.camera_view = tk.Label(camera_area, text="Camera off", bg="#14283f", fg="white")
        self.camera_view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.camera_note = ttk.Label(panel, text="", wraplength=550, style="Subtitle.TLabel")
        self.camera_note.pack(anchor="w")
        options = ttk.Frame(panel)
        options.pack(fill="x", pady=6)
        self.camera_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Camera", variable=self.camera_var, command=self.toggle_camera).pack(side="left")
        self.sound_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="Audible warnings", variable=self.sound_var, command=self.update_alarm).pack(side="left", padx=14)
        ttk.Button(options, text="Test sound", command=self.play_sound).pack(side="right")
        model_options = ttk.Frame(panel)
        model_options.pack(fill="x", pady=4)
        self.model_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(model_options, text="Use trained model", variable=self.model_var, command=self.toggle_model).pack(side="left")
        self.share_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(model_options, text="Share video with owner", variable=self.share_var, command=self.toggle_sharing).pack(side="right")
        self.compact_button = ttk.Button(panel, text="Compact view — hide simulation controls", command=self.toggle_compact)
        self.compact_button.pack(fill="x", pady=(6, 0))
        self.simulation_panel = ttk.Frame(panel)
        self.simulation_panel.pack(fill="x")
        self.compact = False
        ttk.Separator(self.simulation_panel).pack(fill="x", pady=8)
        ttk.Label(self.simulation_panel, text="SIMULATED SENSOR INPUTS", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(self.simulation_panel, text="Behavior switches apply only in simulation. " + ("Motion uses phone GPS; sliders disabled." if self.phone_speed else "Motion stays simulated."), wraplength=600, style="Subtitle.TLabel").pack(anchor="w", pady=(3, 6))
        controls = ttk.Frame(self.simulation_panel)
        controls.pack(fill="x")
        self.flags = {}
        self.flag_controls = []
        for index, (name, label, initial) in enumerate((("eyes_closed", "Eyes closed", False), ("looking_away", "Looking away", False),
                                                      ("phone_use", "Phone use", False), ("yawning", "Yawning", False), ("face_visible", "Face visible", True))):
            variable = tk.BooleanVar(value=initial)
            self.flags[name] = variable
            checkbox = ttk.Checkbutton(controls, text=label, variable=variable)
            checkbox.grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 25), pady=4)
            self.flag_controls.append(checkbox)
        self.speed = tk.DoubleVar(value=45)
        self.acceleration = tk.DoubleVar(value=0)
        for label, variable, start, end in (("Speed (km/h)", self.speed, 0, 120), ("Acceleration (m/s²)", self.acceleration, -8, 8)):
            line = ttk.Frame(self.simulation_panel)
            line.pack(fill="x", pady=4)
            ttk.Label(line, text=label, width=23).pack(side="left")
            slider = ttk.Scale(line, from_=start, to=end, variable=variable)
            slider.pack(side="left", fill="x", expand=True)
            if self.phone_speed:
                slider.state(["disabled"])
            display = ttk.Label(line, width=7)
            display.pack(side="right")
            def update_value(*args, label=display, value=variable):
                label.configure(text=f"{value.get():.1f}")
            variable.trace_add("write", update_value)
            update_value()

    def toggle_compact(self):
        self.compact = not self.compact
        if self.compact:
            self.simulation_panel.pack_forget()
            self.compact_button.configure(text="Show simulation controls")
            self.root.geometry("650x650")
        else:
            self.simulation_panel.pack(fill="x")
            self.compact_button.configure(text="Compact view — hide simulation controls")
            self.root.geometry("650x940")

    def toggle_camera(self):
        self.last_prediction_time = None
        self.session.reset_risk()
        self.observation.reset("Waiting for a camera prediction" if self.camera_var.get() else "Camera off; behavior cannot be assessed")
        if self.camera_var.get():
            self.camera_enabled.set()
        else:
            self.camera_enabled.clear()
            with self.frame_lock:
                self.latest_frame = None
            self.camera_view.configure(image="", text="Camera off", height=2)
            self.camera_view.image = None

    def toggle_model(self):
        self.last_prediction_time = None
        self.session.reset_risk()
        self.observation.reset("Loading model; waiting for a fresh prediction")
        if self.model_var.get():
            self.model_enabled.set()
            self.camera_var.set(True)
            self.toggle_camera()
        else:
            self.model_enabled.clear()
        for control in self.flag_controls:
            control.state(["disabled"] if self.model_var.get() else ["!disabled"])

    def toggle_sharing(self):
        if self.share_var.get():
            self.sharing_enabled.set()
            self.camera_var.set(True)
            self.toggle_camera()
        else:
            self.sharing_enabled.clear()
            self.camera_note.configure(text="Video sharing off; local analysis can continue")

    def notify(self, kind, value):
        try:
            self.events.put_nowait((kind, value))
        except queue.Full:
            pass

    def network_worker(self):
        while not self.stop.is_set():
            try:
                message = self.session.synchronize()
                self.notify("connection", (message, self.session.outbox.count()))
                # Upload separately so a disconnected server cannot slow local inference.
                with self.frame_lock:
                    frame = self.latest_frame
                trip = self.session.current_trip()
                if self.sharing_enabled.is_set() and self.camera_enabled.is_set() and frame and trip:
                    jpeg, captured_at, trip_id = frame
                    if time.monotonic() - captured_at <= 2.5 and trip_id == trip["id"]:
                        try:
                            self.session.api.request("/camera", {"vehicle_id": self.session.vehicle_id,
                                "trip_id": trip_id, "jpeg": base64.b64encode(jpeg).decode("ascii")})
                            self.notify("camera_note", "Video sharing active")
                        except ApiError as error:
                            self.notify("camera_note", "Local camera active; upload unavailable: " + str(error))
            except Exception:
                logging.exception("Driver synchronization failed")
                self.notify("connection", ("Synchronization failed; see application log", self.session.outbox.count()))
            self.stop.wait(1)

    def camera_worker(self):
        camera = None
        model_detector = None
        model_failed = False
        try:
            while not self.stop.is_set():
                if not self.camera_enabled.is_set():
                    if camera is not None:
                        camera.release()
                        camera = None
                    self.stop.wait(0.2)
                    continue
                try:
                    import cv2
                    if not self.model_enabled.is_set():
                        model_failed = False
                    elif model_detector is None and not model_failed:
                        try:
                            model_detector = TrainedDetector(self.model_path)
                            self.notify("camera_note", "Model ready on CPU; video sharing is optional")
                        except Exception as error:
                            logging.exception("Could not load trained model")
                            self.observation.reset("Model unavailable; check model file and requirements-model.txt")
                            self.notify("camera_note", "Model load failed: " + str(error))
                            model_failed = True
                    if camera is None:
                        camera = cv2.VideoCapture(self.camera_index)
                        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    ticket = self.observation.ticket()
                    ok, frame = camera.read()
                    captured_at = time.monotonic()
                    if not ok:
                        raise RuntimeError("Camera unavailable. Close other camera apps and try again.")
                    if self.model_enabled.is_set() and model_detector is not None:
                        prediction = model_detector.read(frame)
                        self.observation.publish(prediction, captured_at, ticket)
                    height, width = frame.shape[:2]
                    frame = cv2.resize(frame, (480, max(1, int(height * 480 / width))))
                    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    if not ok:
                        raise RuntimeError("Camera frame could not be encoded.")
                    jpeg = encoded.tobytes()
                    if not self.camera_enabled.is_set():
                        continue
                    self.notify("preview", jpeg)
                    trip = self.session.current_trip()
                    with self.frame_lock:
                        self.latest_frame = (jpeg, captured_at, trip["id"] if trip else None)
                    if self.sharing_enabled.is_set() and not trip:
                        self.notify("camera_note", "Local preview only; assign a trip to share video")
                except (ImportError, RuntimeError) as error:
                    self.notify("camera_error", "Install optional camera packages first." if isinstance(error, ImportError) else str(error))
                    self.camera_enabled.clear()
                    self.observation.reset("Camera unavailable; behavior cannot be assessed")
                except Exception as error:
                    logging.exception("Camera failed")
                    self.notify("camera_error", "Camera failed: " + str(error))
                    self.camera_enabled.clear()
                    self.observation.reset("Camera or inference failed; behavior cannot be assessed")
                self.stop.wait(0.5)
        finally:
            if camera is not None:
                camera.release()

    def tick(self):
        if self.stop.is_set():
            return
        now = time.monotonic()
        elapsed = now - self.last_tick
        if self.model_enabled.is_set():
            readings, prediction_time = self.observation.read_with_time(now)
            # Repainting the same prediction must not add observed behavior duration.
            elapsed = 0.0
            if prediction_time is not None and self.last_prediction_time is not None:
                gap = prediction_time - self.last_prediction_time
                if 0 <= gap <= 2.5:
                    elapsed = gap
                else:
                    self.session.reset_risk()
            self.last_prediction_time = prediction_time
            label = readings.behavior.replace("_", " ") or "waiting"
            self.prediction_label.configure(text=f"Model: {label} | class score {readings.confidence:.0%} | {readings.inference_ms:.0f} ms\n"
                "Motion simulated. Drowsiness and driver presence are not measured.")
        else:
            self.detector.values = Measurements(**{name: variable.get() for name, variable in self.flags.items()})
            readings = self.detector.read()
            self.prediction_label.configure(text="Behavior and motion: simulated")
        readings.speed = round(self.speed.get(), 1)
        readings.acceleration = round(self.acceleration.get(), 1)
        if self.phone_speed:
            self.phone_speed.apply(readings)
            self.speed.set(readings.speed)
            self.acceleration.set(0)
            behavior = "Model: " + (readings.behavior or "waiting") if self.model_enabled.is_set() else "Behavior simulated"
            gps_value = "unavailable" if readings.assessment_note.startswith(("Phone GPS", "Waiting for phone GPS")) else f"{readings.speed:.1f} km/h"
            self.prediction_label.configure(text=f"{behavior} | Phone GPS: {gps_value}\nAcceleration not measured. "
                + (readings.assessment_note if not readings.assessment_available else "GPS fix current; drowsiness not measured by classifier."))
        try:
            risk = self.session.evaluate(readings, elapsed)
            self.risk_label.configure(text=f"{risk.level}  •  {risk.score}/100", bg=COLORS[risk.level])
            self.reason.configure(text=risk.reason)
            self.high_risk = risk.level == "HIGH"
            self.update_alarm()
        except (OSError, ValueError) as error:
            self.high_risk = False
            self.update_alarm()
            self.reason.configure(text="Could not save local reading: " + str(error))
        self.last_tick = now
        trip = self.session.current_trip()
        self.assignment.configure(text=f"{trip['driver_name']}  •  {trip['route_name']}  •  Trip {trip['id']}" if trip else "No active trip. Owner must assign this vehicle. Local warning demo remains available.")
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "connection":
                self.connection.configure(text=f"{value[0]}  •  {value[1]} queued readings")
            elif kind == "preview" and self.camera_enabled.is_set():
                try:
                    from PIL import Image, ImageTk
                    picture = Image.open(BytesIO(value))
                    picture.thumbnail((max(1, self.camera_view.winfo_width() - 8),
                                       max(1, self.camera_view.winfo_height() - 8)))
                    photo = ImageTk.PhotoImage(picture)
                    self.camera_view.configure(image=photo, text="", height=0)
                    self.camera_view.image = photo
                except ImportError:
                    self.camera_note.configure(text="Install Pillow for local preview. Camera sharing can continue.")
                except OSError:
                    self.camera_note.configure(text="Could not decode local preview")
            elif kind in ("camera_note", "camera_error"):
                self.camera_note.configure(text=value)
                if kind == "camera_error":
                    self.camera_var.set(False)
                    self.camera_view.configure(image="", text="Camera unavailable", height=2)
                    self.camera_view.image = None
        self.root.after(500, self.tick)

    def play_sound(self):
        if self.sound_test is not None:
            self.root.after_cancel(self.sound_test)
        self.sound_test = self.root.after(1000, self.finish_sound_test)
        self.update_alarm()

    def finish_sound_test(self):
        self.sound_test = None
        self.update_alarm()

    def update_alarm(self):
        self.alarm.set_active(self.sound_test is not None or (self.high_risk and self.sound_var.get()))

    def close(self):
        self.stop.set()
        self.camera_enabled.clear()
        self.root.destroy()
