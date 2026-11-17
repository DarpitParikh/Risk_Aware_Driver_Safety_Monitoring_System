"""Command-line entry point. Run `python main.py demo` for the complete lab demo."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import secrets
import threading

from fleet.network import ApiClient
from fleet.server import FleetServer
from fleet.storage import Store
from fleet.model_detector import DEFAULT_MODEL

PROJECT_DIR = Path(__file__).resolve().parent


def load_config(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    config = {"owner_token": secrets.token_urlsafe(24), "device_token": secrets.token_urlsafe(24)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def main():
    parser = argparse.ArgumentParser(description="Fleet Guardian — Python/Tkinter programming lab")
    parser.add_argument("mode", choices=("demo", "server", "owner", "driver", "phone", "check"), nargs="?", default="demo")
    parser.add_argument("--host", default="127.0.0.1", help="Server listen address (use 0.0.0.0 for LAN)")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--server", help="Client server URL, for example http://192.168.1.5:8765")
    parser.add_argument("--vehicle", type=int, default=1)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Exported driver behavior checkpoint (CPU inference)")
    parser.add_argument("--token", help="Owner or device token, depending on mode")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR / "data")
    parser.add_argument("--seed", action="store_true", help="Create sample records if the server database is empty")
    parser.add_argument("--phone-gps", action="store_true", help="Use phone GPS instead of simulated motion (driver/demo)")
    parser.add_argument("--gps-port", type=int, default=8766)
    parser.add_argument("--gps-cert", type=Path)
    parser.add_argument("--gps-key", type=Path)
    args = parser.parse_args()
    if args.mode == "phone":
        if not args.server or not args.token:
            parser.error("Phone mode needs --server and the manager PC's --token (device token).")
        from fleet.android_driver import run_phone
        run_phone(args)
        return
    if args.phone_gps and (args.mode not in ("demo", "driver") or not args.gps_cert or not args.gps_key):
        parser.error("--phone-gps requires driver/demo mode, --gps-cert and --gps-key. See docs/PHONE_GPS.md.")
    if args.mode == "check":
        from fleet.preflight import run_checks
        raise SystemExit(run_checks(args.model))
    if args.mode in ("owner", "driver") and args.server and not args.token:
        parser.error("When using --server, supply --token from that server's data/config.json (owner token for owner; device token for driver).")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    log_file = args.data_dir / f"{args.mode}.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")])
    config = load_config(args.data_dir / "config.json")
    url = args.server or f"http://127.0.0.1:{args.port}"
    server = None
    demo = None
    gps_server = None
    try:
        if args.phone_gps:
            from fleet.phone_speed import PhoneSpeedServer
            gps_server = PhoneSpeedServer(("0.0.0.0", args.gps_port), args.gps_cert, args.gps_key)
            threading.Thread(target=gps_server.serve_forever, daemon=True).start()
            print(f"Phone GPS: https://DRIVER_PC_IP:{args.gps_port}/")
            print(f"Pairing code (changes each launch): {gps_server.token}")
        if args.mode in ("demo", "server"):
            # Demo data never shares the normal server's database.
            store = Store(args.data_dir / ("demo-fleet.sqlite3" if args.mode == "demo" else "fleet.sqlite3"))
            if args.seed or args.mode == "demo":
                store.seed()
            try:
                server = FleetServer((args.host, args.port), store, config["owner_token"], config["device_token"])
                server.model_path = args.model
            except OSError as error:
                parser.error(f"Cannot start server on port {args.port}: {error}. Choose another --port or close the running server.")
            if args.mode == "server":
                print(f"Fleet server listening on {args.host}:{args.port}")
                print(f"Access tokens: {args.data_dir / 'config.json'}")
                server.serve_forever()
                return
            threading.Thread(target=server.serve_forever, daemon=True).start()

        import tkinter as tk
        from fleet.ui_common import enable_high_dpi
        enable_high_dpi()
        if args.mode in ("owner", "demo"):
            from fleet.owner_ui import OwnerApp
            root = tk.Tk()
            OwnerApp(root, ApiClient(url, args.token or config["owner_token"]))
            if args.mode == "demo":
                from fleet.demo import DemoFleet
                from fleet.device import DeviceSession
                from fleet.driver_ui import DriverApp
                demo = DemoFleet(url, config["device_token"], args.data_dir)
                driver_window = tk.Toplevel(root)
                session = DeviceSession(1, ApiClient(url, config["device_token"]), args.data_dir / "demo-1-outbox.sqlite3")
                driver_app = DriverApp(driver_window, session, args.camera, args.model, gps_server.speed if gps_server else None)
                # Closing the owner closes the local demo and its driver workers.
                root.bind("<Destroy>", lambda event: driver_app.stop.set() if event.widget == root else None, add="+")
            root.mainloop()
        elif args.mode == "driver":
            from fleet.device import DeviceSession
            from fleet.driver_ui import DriverApp
            root = tk.Tk()
            session = DeviceSession(args.vehicle, ApiClient(url, args.token or config["device_token"]), args.data_dir / f"vehicle-{args.vehicle}-outbox.sqlite3")
            DriverApp(root, session, args.camera, args.model, gps_server.speed if gps_server else None)
            root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        if gps_server:
            gps_server.shutdown()
            gps_server.server_close()
        if demo:
            demo.close()
        if server:
            if args.mode == "demo":
                server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
