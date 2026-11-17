# Lab demonstration and acceptance checks

## Installation

Install Python 3.13 including Tkinter. Copy the project, including `models`, to each PC; do not copy `.venv` between computers. Run `setup.bat` to create the environment and install dependencies. Internet is needed for installation, not ordinary model inference.

Run `.\.venv\Scripts\python.exe main.py check` to check Tkinter, SQLite, camera packages and an actual CPU inference. It does not access the webcam or certify prediction accuracy.

## One-PC demonstration

1. Run `run_demo.bat`. Confirm three vehicles appear.
2. On vehicle 1, set speed to 45 and select phone use. Expect caution after two seconds and HIGH after five seconds, with sound enabled. Confirm an owner log event.
3. Clear phone use and allow three seconds recovery.
4. Set speed to 7 and select looking away for at least ten seconds. Attention warnings should be suppressed. Phone-use warnings must still work at this speed.
5. Clear the switches. Enable **Use trained model** and position the camera to include the seated person's upper body and hands. Test while stationary, away from traffic.
6. Check the class label, score and inference time. This model does not measure eye closure or yawning. Try different lighting and camera positions; record wrong predictions rather than treating the dataset accuracy as webcam accuracy.
7. Enable **Share video with owner**, then open vehicle 1 in Live monitoring. Verify the video and values.
8. Disconnect the camera. Confirm UNKNOWN instead of a fresh safe assessment. Reconnect and check recovery.
9. Test sound and compact view. Review logs and export CSV.

## Two-PC demonstration

Connect both PCs to the same trusted LAN. On the server PC:

```powershell
.\.venv\Scripts\python.exe main.py server --host 0.0.0.0 --seed
```

Run `ipconfig` to identify that PC's LAN IPv4 address. If Windows asks, allow Python on the private lab network. Keep the server terminal running. Start the owner in another terminal:

```powershell
.\.venv\Scripts\python.exe main.py owner
```

Read the device token from the server's `data/config.json`. On the driver PC replace the placeholders:

```powershell
.\.venv\Scripts\python.exe main.py driver --server http://SERVER_PC_IP:8765 --vehicle 1 --token DEVICE_TOKEN
```

Use the device token for drivers; the owner token is for a remote owner console. Never start two driver clients for the same vehicle. Use normal server mode here, because demo mode creates its own simulated clients.

Verify camera sharing and warnings. Temporarily disconnect the driver PC's network: local assessment should continue and the owner should show the vehicle offline after about eight seconds. Reconnect: queued samples should upload. Confirm driver/route reassignment and that the new trip is shown on the driver side. Synchronize both PCs' clocks.

## Record the result

For each check record PASS/FAIL, date, PC/camera used and any error. A successful software check does not substitute for these manual checks.

The lab version defaults to simulated speed/acceleration and a PC as the driver device. Optional measured phone GPS speed is available: see [Phone GPS setup](PHONE_GPS.md). A complete mobile client, genuine drowsiness detection and independent-driver model evaluation remain separate development work. Network transport is intended for a trusted lab LAN.
