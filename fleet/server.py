"""Local/LAN fleet server. Interfaces never access SQLite directly."""
import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
from io import BytesIO
import sqlite3
from threading import Lock
from urllib.parse import parse_qs, urlparse

from .risk import Measurements


def validate_sample(data):
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    for name in ("vehicle_id", "trip_id"):
        if type(data.get(name)) is not int or data[name] < 1:
            raise ValueError(f"Invalid {name}.")
    if not isinstance(data.get("id"), str) or not 1 <= len(data["id"]) <= 100:
        raise ValueError("Invalid sample identifier.")
    try:
        captured = datetime.fromisoformat(data["captured_at"])
        if captured.tzinfo is None:
            raise ValueError("Timestamp needs a timezone.")
        captured = captured.astimezone(timezone.utc)
        if (captured - datetime.now(timezone.utc)).total_seconds() > 30:
            raise ValueError("Timestamp is in the future. Check the device clock.")
        data["captured_at"] = captured.isoformat(timespec="milliseconds")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Invalid capture time: " + str(error)) from error
    data["readings"] = Measurements.from_dict(data.get("readings")).to_dict()
    risk = data.get("risk")
    if not isinstance(risk, dict) or risk.get("level") not in ("LOW", "CAUTION", "HIGH", "UNKNOWN"):
        raise ValueError("Invalid risk result.")
    if type(risk.get("score")) is not int or not 0 <= risk["score"] <= 100:
        raise ValueError("Risk score must be 0–100.")
    if not isinstance(risk.get("reason"), str) or len(risk["reason"]) > 500:
        raise ValueError("Invalid risk reason.")
    return data


class FleetServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, owner_token, device_token):
        super().__init__(address, Handler)
        self.store = store
        self.owner_token = owner_token
        self.device_token = device_token
        self.frames = {}
        self.frame_lock = Lock()
        self.detector = None
        self.model_lock = Lock()

    def classify(self, jpeg):
        from PIL import Image
        import numpy as np
        from .model_detector import DEFAULT_MODEL, TrainedDetector
        with Image.open(BytesIO(jpeg)) as picture:
            if picture.format != "JPEG" or max(picture.size) > 1024:
                raise ValueError("Expected a JPEG up to 1024 pixels per side.")
            bgr = np.asarray(picture.convert("RGB"))[:, :, ::-1]
        with self.model_lock:
            if self.detector is None:
                self.detector = TrainedDetector(getattr(self, "model_path", DEFAULT_MODEL))
            return self.detector.read(bgr)


class Handler(BaseHTTPRequestHandler):
    server_version = "FleetLab/1.0"

    def log_message(self, format_string, *args):
        logging.debug(format_string, *args)

    def respond(self, status, data, content_type="application/json"):
        body = json.dumps(data).encode("utf-8") if content_type == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, posting):
        try:
            url = urlparse(self.path)
            path = url.path
            body = None
            if posting:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 400_000:
                    raise ValueError("Request is empty or too large.")
                self.connection.settimeout(5)
                # Consume the bounded body before replying, including auth failures.
                # Otherwise Windows may reset the socket with unread request data.
                body = self.rfile.read(size)
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            owner = hmac.compare_digest(token, self.server.owner_token)
            device = hmac.compare_digest(token, self.server.device_token)
            if not (owner or device):
                self.respond(401, {"error": "Incorrect access token."})
                return
            owner_only = path in ("/snapshot", "/logs", "/entity", "/assign", "/end-trip") or path.startswith("/frame/")
            if owner_only and not owner:
                self.respond(403, {"error": "Owner access required."})
                return
            if posting:
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object.")
                self.post_route(path, data)
            else:
                self.get_route(path, parse_qs(url.query))
        except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as error:
            message = str(error)
            if isinstance(error, sqlite3.IntegrityError):
                message = "Duplicate or invalid record. Registration, license, and route names must be unique."
            self.respond(400, {"error": message})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            logging.exception("Server request failed")
            self.respond(500, {"error": "Server error. See the server log."})

    def get_route(self, path, query):
        if path == "/health":
            self.respond(200, {"status": "ok"})
        elif path == "/snapshot":
            self.respond(200, self.server.store.snapshot())
        elif path == "/logs":
            filters = {key: values[0] for key, values in query.items() if key in ("vehicle_id", "driver_id", "level", "since", "until")}
            self.respond(200, self.server.store.logs(**filters))
        elif path.startswith("/assignment/"):
            self.respond(200, {"trip": self.server.store.assignment(int(path.split("/")[-1]))})
        elif path.startswith("/frame/"):
            vehicle_id = int(path.split("/")[-1])
            with self.server.frame_lock:
                frame = self.server.frames.get(vehicle_id)
            trip = self.server.store.assignment(vehicle_id)
            if not frame or not trip or frame[2] != trip["id"] or (datetime.now(timezone.utc) - frame[0]).total_seconds() > 6:
                self.respond(404, {"error": "No recent camera frame. Enable camera sharing in the driver window."})
            else:
                self.respond(200, frame[1], "image/jpeg")
        else:
            self.respond(404, {"error": "Unknown endpoint."})

    def post_route(self, path, data):
        store = self.server.store
        if path == "/entity":
            self.respond(200, {"id": store.save_entity(data["kind"], data["values"])})
        elif path == "/assign":
            trip_id = store.assign(int(data["vehicle_id"]), int(data["driver_id"]), int(data["route_id"]))
            self.respond(200, {"trip_id": trip_id})
        elif path == "/end-trip":
            store.end_trip(int(data["trip_id"]))
            self.respond(200, {"ok": True})
        elif path == "/telemetry":
            store.add_sample(validate_sample(data))
            self.respond(200, {"ok": True})
        elif path in ("/camera", "/phone-frame"):
            vehicle_id, trip_id = int(data["vehicle_id"]), int(data["trip_id"])
            trip = store.assignment(vehicle_id)
            if not trip or trip["id"] != trip_id:
                raise ValueError("Camera requires the current active trip.")
            frame = base64.b64decode(data["jpeg"], validate=True)
            if len(frame) > 250_000 or not frame.startswith(b"\xff\xd8"):
                raise ValueError("Expected a small JPEG frame.")
            readings = self.server.classify(frame) if path == "/phone-frame" else None
            with self.server.frame_lock:
                self.server.frames[vehicle_id] = (datetime.now(timezone.utc), frame, trip_id)
            self.respond(200, {"readings": readings.to_dict()} if readings else {"ok": True})
        else:
            self.respond(404, {"error": "Unknown endpoint."})
