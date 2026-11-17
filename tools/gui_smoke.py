"""Interactive-window smoke check. Uses temporary data, never the user's fleet DB."""
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageGrab
from fleet.device import DeviceSession
from fleet.driver_ui import DriverApp
from fleet.network import ApiClient
from fleet.owner_ui import OwnerApp
from fleet.server import FleetServer
from fleet.storage import Store
from fleet.ui_common import enable_high_dpi
from fleet.model_detector import prediction_to_readings


def run():
    enable_high_dpi()
    output = Path(__file__).resolve().parents[1] / "build" / "gui-check"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        data = Path(directory)
        store = Store(data / "fleet.sqlite3")
        store.seed()
        server = FleetServer(("127.0.0.1", 0), store, "owner-smoke", "device-smoke")
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        owner = OwnerApp(root, ApiClient(url, "owner-smoke"))
        root.geometry("1280x800+10+10")
        driver_root = tk.Toplevel(root)
        session = DeviceSession(1, ApiClient(url, "device-smoke"), data / "outbox.sqlite3")
        driver = DriverApp(driver_root, session)
        driver_root.withdraw()
        sounds = []
        driver.play_sound = lambda: sounds.append(True)

        def pump(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(0.02)
            assert not errors, errors

        def capture(window, name):
            window.lift()
            window.update()
            time.sleep(0.25)
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes
                get_ancestor = ctypes.windll.user32.GetAncestor
                get_ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
                get_ancestor.restype = wintypes.HWND
                handle = get_ancestor(window.winfo_id(), 2)
                ImageGrab.grab(window=handle).save(output / name)
            else:
                box = (window.winfo_rootx(), window.winfo_rooty(),
                       window.winfo_rootx() + window.winfo_width(), window.winfo_rooty() + window.winfo_height())
                ImageGrab.grab(bbox=box).save(output / name)

        try:
            pump(2)
            assert owner.online
            assert len(owner.table.get_children()) == 3
            driver.flags["eyes_closed"].set(True)
            pump(4)
            assert "HIGH" in driver.risk_label.cget("text")
            assert sounds, "Driver did not request its local warning sound"
            assert any(event["level"] == "HIGH" for event in owner.logs)
            capture(root, "owner-overview.png")
            for page in ("Vehicles", "Drivers", "Routes", "Assignments"):
                owner.show_page(page)
                pump(0.2)
                assert owner.table.get_children(), page
            owner.entity_dialog("drivers")
            pump(0.2)
            for window in root.winfo_children():
                if isinstance(window, tk.Toplevel) and window != driver_root:
                    window.destroy()
            owner.assignment_dialog()
            pump(0.2)
            for window in root.winfo_children():
                if isinstance(window, tk.Toplevel) and window != driver_root:
                    window.destroy()
            owner.show_page("Live monitoring")
            owner.choose_vehicle(1)
            pump(0.2)
            assert "Aarav" in owner.monitor_details.cget("text")
            image_bytes = BytesIO()
            Image.new("RGB", (480, 270), "#284662").save(image_bytes, format="JPEG")
            owner.render_frame(1, image_bytes.getvalue())
            assert owner.video.image is not None
            capture(root, "owner-monitor.png")
            owner.show_page("Logs & reports")
            owner.filters["level"].set("HIGH")
            owner.apply_filters()
            pump(2)
            assert owner.logs and all(event["level"] == "HIGH" for event in owner.logs)
            with patch("fleet.owner_ui.filedialog.asksaveasfilename", return_value=str(output / "events.csv")), patch("fleet.owner_ui.messagebox.showinfo"):
                owner.export_logs()
            assert "HIGH" in (output / "events.csv").read_text(encoding="utf-8-sig")
            capture(root, "owner-logs.png")
            root.withdraw()
            driver_root.deiconify()
            driver_root.geometry("650x940+20+20")
            pump(0.2)
            capture(driver_root, "driver-warning.png")
            driver.toggle_compact()
            pump(0.2)
            assert not driver.simulation_panel.winfo_ismapped()
            capture(driver_root, "driver-compact.png")
            driver.flags["eyes_closed"].set(False)
            pump(3.5)
            assert "LOW" in driver.risk_label.cget("text")
            # Controlled fixtures exercise camera/model plumbing without activating hardware.
            # Actual exported-weight inference is checked separately in test_model.py.
            import numpy as np

            class FixtureCamera:
                def __init__(self, *args):
                    pass

                def set(self, *args):
                    pass

                def read(self):
                    return True, np.zeros((360, 480, 3), dtype=np.uint8)

                def release(self):
                    pass

            class FixtureDetector:
                label = "texting_phone"

                def __init__(self, *args):
                    pass

                def read(self, frame):
                    return prediction_to_readings(self.label, 0.95, 20)

            with patch("cv2.VideoCapture", FixtureCamera), patch("fleet.driver_ui.TrainedDetector", FixtureDetector):
                driver.model_var.set(True)
                driver.toggle_model()
                driver.share_var.set(True)
                driver.toggle_sharing()
                pump(7)
                assert "HIGH" in driver.risk_label.cget("text")
                assert "texting phone" in driver.prediction_label.cget("text")
                assert all("disabled" in control.state() for control in driver.flag_controls)
                sample = store.snapshot()["vehicles"][0]["sample"]
                assert sample["readings"]["source"] == "trained_model"
                assert sample["readings"]["motion_source"] == "simulation"
                assert sample["readings"]["face_visible"] is None
                assert sample["level"] == "HIGH"
                assert owner.api.request("/frame/1", raw=True).startswith(b"\xff\xd8")
                assert driver.compact_button.winfo_rooty() + driver.compact_button.winfo_height() <= driver_root.winfo_rooty() + driver_root.winfo_height(), "Compact controls are clipped"
                assert driver.camera_view.image.height() <= driver.camera_view.winfo_height(), "Driver preview is cropped"
                capture(driver_root, "driver-model-fixture.png")
                root.deiconify()
                driver_root.withdraw()
                owner.show_page("Live monitoring")
                owner.choose_vehicle(1)
                pump(1.5)
                assert "Texting" in owner.monitor_details.cget("text")
                assert "km/h" in owner.monitor_details.cget("text")
                assert owner.video.image.height() <= owner.video.winfo_height(), "Owner preview is cropped"
                capture(root, "owner-model-fixture.png")
                FixtureDetector.label = "other_activities"
                pump(2)
                assert "UNKNOWN" in driver.risk_label.cget("text")
                assert "specific hazard" in driver.reason.cget("text")
                driver.camera_var.set(False)
                driver.toggle_camera()
                pump(0.7)
                assert "UNKNOWN" in driver.risk_label.cget("text")
                assert "Camera off" in driver.reason.cget("text")
                driver.model_var.set(False)
                driver.toggle_model()
                pump(0.7)
                assert "LOW" in driver.risk_label.cget("text")
                assert all("disabled" not in control.state() for control in driver.flag_controls)
            print("GUI smoke PASS: all pages, dialogs, CSV, recovery, model mode, model telemetry, video upload, ambiguous class, camera-off UNKNOWN, simulation fallback by explicit toggle")
            print(f"Screenshots: {output}")
        finally:
            owner.stop.set()
            driver.stop.set()
            root.destroy()
            time.sleep(1.2)
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=3)


if __name__ == "__main__":
    run()
