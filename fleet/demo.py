"""Several independent simulated devices, communicating over the real HTTP API."""
import logging
import threading
import time

from .detectors import ScenarioDetector
from .device import DeviceSession
from .network import ApiClient


class DemoFleet:
    def __init__(self, url, token, data_dir, vehicle_ids=(2, 3)):
        self.stop = threading.Event()
        self.threads = []
        for vehicle_id in vehicle_ids:
            session = DeviceSession(vehicle_id, ApiClient(url, token), data_dir / f"demo-{vehicle_id}-outbox.sqlite3")
            thread = threading.Thread(target=self.run_device, args=(session,), daemon=True)
            thread.start()
            self.threads.append(thread)

    def run_device(self, session):
        detector = ScenarioDetector(session.vehicle_id)
        last = time.monotonic()
        while not self.stop.is_set():
            try:
                session.synchronize()
                now = time.monotonic()
                session.evaluate(detector.read(), now - last)
                last = now
            except Exception:
                logging.exception("Demo device failed")
            self.stop.wait(1)

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=4)
