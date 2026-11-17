"""Vehicle device transport and durable offline buffering."""
import json
import logging
from pathlib import Path
import sqlite3
from threading import Lock
import uuid
from contextlib import contextmanager

from .network import ApiError
from .risk import RiskEngine
from .storage import utc_now


class Outbox:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS pending(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS rejected(id INTEGER PRIMARY KEY, payload TEXT, reason TEXT)")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, payload):
        with self.connection() as db:
            db.execute("INSERT INTO pending(payload) VALUES(?)", (json.dumps(payload),))

    def count(self):
        with self.connection() as db:
            return db.execute("SELECT COUNT(*) FROM pending").fetchone()[0]

    def flush(self, api, maximum=10):
        with self.connection() as db:
            rows = db.execute("SELECT id,payload FROM pending ORDER BY id LIMIT ?", (maximum,)).fetchall()
        for row_id, payload in rows:
            try:
                api.request("/telemetry", json.loads(payload))
            except ApiError as error:
                if error.status != 400:
                    raise
                # Keep rejected records for inspection rather than silently losing them.
                logging.warning("Telemetry rejected: %s", error)
                with self.connection() as db:
                    db.execute("INSERT INTO rejected(payload,reason) VALUES(?,?)", (payload, str(error)))
                    db.execute("DELETE FROM pending WHERE id=?", (row_id,))
            else:
                with self.connection() as db:
                    db.execute("DELETE FROM pending WHERE id=?", (row_id,))


class DeviceSession:
    """Local risk evaluation remains independent of HTTP/network availability."""
    def __init__(self, vehicle_id, api, outbox_path):
        self.vehicle_id = vehicle_id
        self.api = api
        self.outbox = Outbox(outbox_path)
        self.trip = None
        self.engine = RiskEngine()
        self.connection = "Connecting"
        self.lock = Lock()

    def refresh_assignment(self):
        trip = self.api.request(f"/assignment/{self.vehicle_id}")["trip"]
        with self.lock:
            old_id = self.trip["id"] if self.trip else None
            new_id = trip["id"] if trip else None
            if old_id != new_id:
                self.engine = RiskEngine()
            self.trip = trip
        return trip

    def evaluate(self, readings, elapsed):
        with self.lock:
            risk = self.engine.update(readings, elapsed)
            if self.trip:
                self.outbox.put({"id": str(uuid.uuid4()), "vehicle_id": self.vehicle_id,
                                 "trip_id": self.trip["id"], "captured_at": utc_now(),
                                 "readings": readings.to_dict(), "risk": risk.to_dict()})
        return risk

    def current_trip(self):
        with self.lock:
            return dict(self.trip) if self.trip else None

    def reset_risk(self):
        with self.lock:
            self.engine = RiskEngine()

    def synchronize(self):
        try:
            self.refresh_assignment()
            self.outbox.flush(self.api)
            self.connection = "Connected" if self.trip else "Connected — no active trip"
        except ApiError as error:
            self.connection = str(error)
        return self.connection
