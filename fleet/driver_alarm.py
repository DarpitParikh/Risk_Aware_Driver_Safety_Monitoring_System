"""Loop a two-tone warning without blocking the Tkinter event loop."""
from array import array
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import wave


class DriverAlarm:
    def __init__(self, root):
        self.root = root
        self.active = False
        self.bell_timer = None
        self.directory = None
        self.player = None
        root.bind("<Destroy>", self.close, add="+")

    def set_active(self, active):
        if active == self.active:
            return
        self.active = active
        if not active:
            if self.bell_timer is not None:
                self.root.after_cancel(self.bell_timer)
                self.bell_timer = None
            if self.player is not None:
                self.player.PlaySound(None, 0)
                self.player = None
            return
        try:
            import winsound

            if self.directory is None:
                self.directory = TemporaryDirectory()
                path = Path(self.directory.name) / "driver-warning.wav"
                samples = array("h")
                rate = 16000
                for frequency in (880, 1320):
                    samples.extend(round(10500 * math.sin(math.tau * frequency * i / rate))
                                   for i in range(rate // 4))
                with wave.open(str(path), "wb") as output:
                    output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                    output.writeframes(samples.tobytes())
            path = Path(self.directory.name) / "driver-warning.wav"
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP | winsound.SND_NODEFAULT)
            self.player = winsound
        except (ImportError, OSError, RuntimeError):
            self.ring()

    def ring(self):
        self.root.bell()
        self.bell_timer = self.root.after(250, self.ring)

    def close(self, event):
        if event.widget == self.root:
            self.set_active(False)
            if self.directory is not None:
                self.directory.cleanup()
