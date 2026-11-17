# Fleet Guardian

**Demo over mobile data:** Run `start_trip_fleet.bat` on the manager PC, copy the assigned vehicle's link and open it on the phone in Chrome. Tap **Start monitoring** and allow camera and location access. Keep the PC running. Trip mode uses a Cloudflare Quick Tunnel to the phone service. Each vehicle link contains its own access token. Closing the launcher stops the tunnel, and the next launch issues fresh links. Live inference and alerts depend on connectivity. The PC helper is `tools/cloudflared.exe`; on another PC without the bundled file, install it using `winget install --id Cloudflare.cloudflared -e`.

For the fleet-manager PC and Android driver-phone setup, follow [Android driver setup and code walkthrough](docs/ANDROID_DRIVER.md). Each phone reports to the same manager and uses the vehicle ID for its assignment.

A Python programming-lab project for monitoring a fleet's drivers. The owner and driver interfaces use **Tkinter**. The application, HTTP server, database, risk rules, simulated devices, and tests use the **Python standard library**. OpenCV and Pillow are optional camera packages.

**Current stage:** fleet application with the team's trained MobileNetV3 Small classifier, optional webcam sharing, and a manual simulation mode. Camera behavior predictions run locally on the CPU. Motion defaults to simulation; optional [phone GPS speed input](docs/PHONE_GPS.md) supplies real speed over HTTPS. Acceleration is unmeasured in GPS mode. Risk thresholds and the model-score cutoff are demonstration settings, not validated road-safety thresholds.

## Quick start on Windows

On a fresh PC, run `setup.bat`. Run `.\.venv\Scripts\python.exe main.py check` for installation and model readiness checks without accessing the webcam. See [the lab demonstration guide](docs/LAB_DEMO.md) for real-camera, two-PC and offline/reconnect acceptance checks.

Python 3.13 with Tkinter is supported. From this folder:

```powershell
.\.venv\Scripts\python.exe main.py demo
```

Or double-click `run_demo.bat`, which selects the project's virtual environment when present. Without the model dependencies, `py -3.13 main.py demo` still runs the manual simulation.

This opens:

- The owner's dashboard with three demo vehicles, drivers, routes, and active trips.
- A driver window for vehicle 1 with controls for simulated readings.
- Background simulators for vehicles 2 and 3, using the same HTTP API as real clients.

The demo uses `data/demo-fleet.sqlite3`. The normal server uses `data/fleet.sqlite3`, so demo and normal records stay separate. Closing the owner window stops the demo server and simulators. Closing only the driver window makes vehicle 1 go offline after about eight seconds. Do not run two clients for the same vehicle simultaneously.

### Demonstrate a warning

1. Keep vehicle 1's speed above 3 km/h.
2. Check **Eyes closed** for at least two seconds.
3. The driver window turns red and plays a warning sound. The owner sees HIGH risk and an event appears in the logs.
4. Uncheck **Eyes closed**. The risk clears after three seconds of recovery.
5. Uncheck **Face visible** to demonstrate UNKNOWN instead of falsely reporting safe.
6. Set speed to zero to demonstrate suppression of motion-related warnings.

Use **Test sound** to check the operating system's alert volume. Automatic sound is enabled by default, plays at HIGH risk, and repeats at most every ten seconds during a continuous HIGH episode. A new HIGH episode can sound immediately.

Use **Compact view** in the driver window to hide the simulator controls and keep a smaller monitoring window.

## Trained model and optional webcam

The exported model is installed at `models/driver_behavior/driver_behavior.pth`. Its metadata and Colab test report are beside it. On another PC, prepare the environment and install dependencies:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-model.txt
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

This workspace's environment inherits the already installed camera packages and installs PyTorch locally; it does not require CUDA or a GPU.

In the driver window, enable **Use trained model**. This turns on the local camera and disables the manual behavior switches. The window shows the predicted class, top softmax score and inference time. Enable **Share video with owner** separately to send preview images. In the owner console, double-click that vehicle or select it under **Live monitoring**. Predictions appear even when video sharing is off. Keep the simulated speed above 3 km/h to exercise motion-related warning rules.

Camera and video sharing default to off. Sharing requires an active trip. Only the latest JPEG is held in server memory; video is not recorded to disk. A frame expires after six seconds or when the trip changes. `--model PATH` selects another compatible export.

The classifier uses the whole frame. It does not provide bounding boxes, face-presence checks, eye closure, or yawning measurements. Its risk mapping is:

| Model output | Application behavior |
| --- | --- |
| Talking/texting phone, score at least 0.65 | Phone-duration rules: caution after 2 seconds, high after 5 |
| Turning, score at least 0.65 | Speed-dependent attention rules below; low-speed manoeuvring allowance |
| Safe driving, score at least 0.65 | No modeled behavior flag; this does not certify driver safety |
| Other activities | UNKNOWN because this label mixes unrelated behaviors |
| Score below 0.65, missing model/camera, or stale frame | UNKNOWN; no fallback to invented simulation readings |

The score is not a calibrated probability of correctness. The 0.65 cutoff needs calibration on separate validation footage. Mode changes reset temporal history. Refreshing the same prediction does not add behavior duration. Predictions expire after 2.5 seconds without a fresh frame. HTTP uploads run separately from camera inference, so server outages do not block local analysis.

The supplied Colab report records **91.25% test accuracy** and **0.9094 macro-F1** on 1,097 test images. It uses a provisional image-level split, with no established driver/session independence. These are supplied dataset results, not locally remeasured webcam performance. The broad `other_activities` class has F1 0.804. See `docs/MODEL_INTEGRATION.md` for exact preprocessing and limitations.

Use `--camera 1` if the desired camera is not device 0. Phone cameras are not connected; the driver laptop represents the vehicle device. Phone GPS speed is available through `--phone-gps`; follow [the setup guide](docs/PHONE_GPS.md).

## Run the components separately

Start the server:

```powershell
.\.venv\Scripts\python.exe main.py server --seed
```

In separate terminals:

```powershell
.\.venv\Scripts\python.exe main.py owner
.\.venv\Scripts\python.exe main.py driver --vehicle 1
```

Omit `--seed` for an empty normal database. Add drivers, vehicles and routes in the owner console, then assign a trip. IDs appear in the tables. With an existing database, `--seed` does not replace records.

For a trusted LAN demonstration, start the server with `--host 0.0.0.0`. On the driver PC:

```powershell
.\.venv\Scripts\python.exe main.py driver --server http://SERVER_PC_IP:8765 --vehicle 1 --token DEVICE_TOKEN
```

The server generates owner and device tokens in `data/config.json`. Give driver clients the **device token**; owner-only operations reject it. Remote owner clients use the owner token. Tokens are not printed in application logs. The prototype uses HTTP and a shared device token, so it is intended for localhost or a trusted lab LAN, not public Internet deployment. Per-device identity and TLS belong in a later deployment phase.

Client and server clocks should be synchronized, because timestamps determine trip membership and stale telemetry. Use `--port 8766` to select a different port and `--data-dir PATH` to select a separate data directory.

## Owner workflow

| Page | Features |
| --- | --- |
| Overview | Vehicle and active-trip counts, online count, HIGH/CAUTION/UNKNOWN counts, live fleet rows, recent transitions |
| Vehicles | Add/edit registration and model; open monitoring |
| Drivers | Add/edit name, license, contact; current vehicle and risk; open active vehicle |
| Routes | Add/edit route name, origin and destination |
| Assignments | Start/change assignments, end a trip, inspect trip history |
| Live monitoring | Selected vehicle's driver, route, score, reason, measurements, last sample time, camera |
| Logs & reports | Vehicle/driver/severity/date filters, latest 1,000 matching transitions, CSV export |

A driver cannot have two active trips. Reassigning a vehicle atomically closes the previous trip and creates a new one. Trip records retain the driver, vehicle, and route names from assignment time, so later edits do not rewrite history. End a driver's existing trip before assigning that driver to another vehicle. No permanent deletion UI is provided because records support historical logs.

## Offline behavior and data

Risk assessment and warnings run on the driver device, independently of the server. Once a device knows its trip, it saves samples in a local SQLite outbox. A background worker sends them in order and retries after connection failures. Unique sample IDs prevent duplicates. Rejected samples remain in the outbox database's `rejected` table with the reason. Samples captured during a previous trip can be replayed after that trip ends; samples captured after its end are rejected.

The owner marks devices offline if their latest capture or receipt is older than eight seconds. Replaying old samples cannot make a disconnected device appear live. On startup a device needs to contact the server to discover its assignment; local warning simulation can still work before that, but unassigned readings are not added to trip history.

Server tables:

- `vehicles`, `drivers`, `routes`: fleet records.
- `trips`: assignment history and stable display-name snapshots.
- `samples`: all accepted telemetry.
- `events`: risk-level changes, including initial state and recovery.

The database retains samples indefinitely for this lab version. CSV export includes up to the 1,000 matching events displayed, not every raw sample. Application diagnostics use rotating logs under `data/`. Stop the server before copying its database for backup.

## Explainable risk rules

| Evidence while moving | Score contribution |
| --- | --- |
| Eyes closed for at least 2 seconds | 75 |
| Looking away / model turning | Speed-dependent: 45 at caution duration, 75 at high duration |
| Phone use for at least 2 seconds | 65; becomes 80 after 5 seconds |
| Yawning for at least 2 seconds | 25 |
| At least 3 yawning episodes in the last 60 seconds | 35 |
| Acceleration at or below −4 m/s² | 35 |

Scores sum and cap at 100. LOW is 0–29, CAUTION is 30–69, HIGH is 70–100. A lower level needs three seconds of recovery. Missing face produces UNKNOWN. Speed below 3 km/h suppresses motion-related warnings. The numerical bands are implementation choices to calibrate later, not claimed results from the PPT or a trained model.

### Speed-aware attention warnings

`fleet/attention.py` contains the prototype settings for looking away and model-predicted turning:

| Speed context | Caution | High risk |
| --- | --- | --- |
| Stopped, below 3 km/h | Existing motion-alert suppression | Suppressed |
| Possible manoeuvring, 3–10 km/h inclusive | Attention warnings suppressed even during prolonged looking around | Suppressed |
| Moderate speed, above 10 through 30 km/h | After 5 seconds | After 10 seconds |
| Faster travel, above 30 km/h | After 3 seconds | After 6 seconds |

At startup, the current speed chooses the band. Subsequent changes use a 2 km/h hysteresis margin and require two seconds of consistent observations: leaving manoeuvring requires above 12 km/h, entering it requires at most 8 km/h, entering faster travel requires above 32 km/h, and returning to moderate speed requires at most 28 km/h. Independently of that retained band, an actual reading at or below 10 km/h suppresses attention scoring immediately. Existing warnings still use the normal three-second recovery period.

On a confirmed band change, attention duration restarts from zero. Time spent looking around while manoeuvring never carries into a faster-speed alert. A frame repaint with no new observation cannot confirm a band change. Phone use, eye closure, yawning and harsh-deceleration rules are not relaxed by the manoeuvring allowance; the existing below-3 km/h suppression still applies to them.

Risk explanations show the speed and timer threshold, or say that possible low-speed manoeuvring suppressed the attention warning. Speed alone cannot confirm reversing, a narrow road or a safe manoeuvre. Speed inputs remain simulated, and all thresholds need calibration with real data. Model weights do not change for this feature.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite checks temporal risk, stopped/missing-face states, repeated yawns, validation, HTTP authorization, assignment integrity, historical names, trip boundaries, duplicate delivery, offline replay, camera transport, and stale-device detection. It also checks real CPU checkpoint loading, matching Colab preprocessing, prediction semantics, source preservation, and stale model results. Tests use temporary databases and loopback servers; no webcam is required. Real-model tests skip when PyTorch is absent.

## Code guide and model integration

Read [docs/CODE_GUIDE.md](docs/CODE_GUIDE.md) for the architecture, Python concepts, and explanation order. Read [docs/MODEL_INTEGRATION.md](docs/MODEL_INTEGRATION.md) for the integrated model and future detector extensions.

This is a desktop lab prototype. Actual phone deployment requires a mobile client or a phone-to-PC sensor bridge. GPS maps, genuine GPS/IMU readings, dedicated drowsiness detection, and validation with live driving footage remain future work.
