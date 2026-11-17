"""One phone supplies speed to one driver process over authenticated HTTPS."""
import json
import math
from pathlib import Path
import secrets
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class PhoneSpeed:
    def __init__(self):
        self.lock = threading.Lock()
        self.sample = None
        self.last_timestamp = -1

    def accept(self, data, now=None):
        now = time.time() if now is None else now
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
        stamp, speed, accuracy = (data.get(key) for key in ("timestamp", "speed_mps", "accuracy_m"))
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            raise ValueError("Invalid timestamp")
        if not -2 <= now - stamp <= 5:
            raise ValueError("Expired GPS fix or phone/PC clocks disagree")
        for value in (speed, accuracy):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError("Invalid GPS value")
        if speed is not None and not 0 <= speed <= 250 / 3.6:
            raise ValueError("Speed out of range")
        if accuracy is not None and accuracy < 0:
            raise ValueError("Accuracy out of range")
        with self.lock:
            if stamp <= self.last_timestamp:
                raise ValueError("Old or repeated GPS fix")
            self.last_timestamp = stamp
            self.sample = (stamp, time.monotonic(), speed, accuracy)

    def apply(self, readings, now=None, monotonic=None):
        now = time.time() if now is None else now
        monotonic = time.monotonic() if monotonic is None else monotonic
        readings.motion_source = "phone_gps"
        readings.acceleration = 0  # Not measured; never infer harsh braking from GPS jitter.
        readings.speed = 0  # Placeholder only; unavailable assessment prevents stopped logic.
        with self.lock:
            sample = self.sample
        note = "Waiting for phone GPS"
        if sample:
            stamp, received, speed, accuracy = sample
            if not -2 <= now - stamp <= 5 or monotonic - received > 5:
                note = "Phone GPS stale or disconnected"
            elif accuracy is None or accuracy > 30:
                note = "Phone GPS position accuracy insufficient (limit 30 m)"
            elif speed is None:
                note = "Phone GPS cannot measure speed"
            else:
                readings.speed = round(speed * 3.6, 1)
                return readings
        readings.assessment_available = False
        readings.assessment_note = note
        return readings


class PhoneSpeedServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, certificate, key):
        self.speed = PhoneSpeed()
        self.token = secrets.token_urlsafe(24)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certificate, key)
        super().__init__(address, PhoneHandler)
        self.socket = context.wrap_socket(self.socket, server_side=True)


class PhoneHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # Pairing credentials must not appear in request logs.

    def respond(self, code, body, kind="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/":
            return self.respond(404, b"Not found")
        self.respond(200, Path(__file__).with_name("phone_speed.html").read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                return self.respond(400, b"Invalid body size")
            body = self.rfile.read(length)
            if self.path != "/speed":
                return self.respond(404, b"Not found")
            if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.token):
                return self.respond(401, b"Invalid pairing code")
            self.server.speed.accept(json.loads(body))
            self.respond(200, b"OK")
        except (ValueError, UnicodeError) as error:
            self.respond(400, str(error).encode())
