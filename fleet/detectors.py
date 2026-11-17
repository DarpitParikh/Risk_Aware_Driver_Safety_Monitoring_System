"""Replace only the detector when the team's trained model is ready."""
from abc import ABC, abstractmethod
from .risk import Measurements


class Detector(ABC):
    @abstractmethod
    def read(self, frame=None):
        """Return Measurements from a frame and/or a sensor source."""


class ManualDetector(Detector):
    """The lab operator controls simulated behavior using Tkinter controls."""
    def __init__(self):
        self.values = Measurements()

    def read(self, frame=None):
        return Measurements.from_dict(self.values.to_dict())


class ScenarioDetector(Detector):
    """Repeatable scenarios for demonstrating multiple vehicles without hardware."""
    def __init__(self, vehicle_id):
        self.vehicle_id = vehicle_id
        self.tick = 0

    def read(self, frame=None):
        self.tick += 1
        phase = (self.tick + self.vehicle_id * 9) % 75
        return Measurements(speed=45 + self.vehicle_id * 4,
                            eyes_closed=20 <= phase < 26,
                            looking_away=40 <= phase < 48,
                            phone_use=43 <= phase < 48,
                            yawning=10 <= phase < 13,
                            face_visible=not 60 <= phase < 65)
