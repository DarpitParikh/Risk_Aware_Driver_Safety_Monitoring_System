"""Readiness checks without opening a webcam or changing fleet records."""
import importlib
import sqlite3
import sys


def run_checks(model_path):
    failures = []

    def check(name, action):
        try:
            detail = action()
            print(f"PASS {name}" + (f": {detail}" if detail else ""))
        except Exception as error:
            failures.append(name)
            print(f"FAIL {name}: {error}")

    def tkinter_check():
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()

    def database_check():
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE TABLE readiness (value INTEGER)")
            connection.execute("INSERT INTO readiness VALUES (1)")
            assert connection.execute("SELECT value FROM readiness").fetchone() == (1,)
        finally:
            connection.close()

    def model_check():
        import numpy as np
        from .model_detector import TrainedDetector
        detector = TrainedDetector(model_path)
        reading = detector.read(np.zeros((224, 224, 3), dtype=np.uint8))
        return f"CPU inference completed in {reading.inference_ms:.0f} ms (synthetic image; not an accuracy test)"

    print(f"Python: {sys.version.split()[0]}\nInterpreter: {sys.executable}")
    check("Tkinter display", tkinter_check)
    check("SQLite", database_check)
    for module in ("cv2", "PIL", "torch", "torchvision"):
        check(module, lambda name=module: getattr(importlib.import_module(name), "__version__", "available"))
    check("Exported model", model_check)
    print("Camera was not opened. Speed remains simulated; drowsiness is not measured by this model.")
    if failures:
        print("Install dependencies using setup.bat, then run this check again.")
        return 1
    print("Software checks passed. Follow docs/LAB_DEMO.md for hardware and network checks.")
    return 0
