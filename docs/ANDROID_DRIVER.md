# Manager PC and Android driver phones

The manager runs the fleet server and Tkinter dashboard on one PC. Each driver carries an Android phone running a small Tkinter window through Termux:X11. The phone reads GPS, camera, accelerometer and gyroscope through Termux:API. The manager PC classifies each uploaded camera snapshot with the trained model. The phone combines that prediction with speed, evaluates risk and sounds warnings. The dashboard and trip logs show the result under the assigned vehicle and driver.

## Manager PC

On the trusted lab Wi-Fi, open two project terminals. Run one command per terminal.

```powershell
.\.venv\Scripts\python.exe main.py server --seed --host 0.0.0.0
.\.venv\Scripts\python.exe main.py owner
```

Assign each vehicle a driver and route. Read the device token from the server's data/config.json. Use ipconfig to find the manager PC's Wi-Fi IPv4 address. Allow inbound TCP port 8765 on the private lab network. This mode uses HTTP and a shared lab device token.

## Driver phone

Install Termux and Termux:API from matching distribution sources and install the Termux:X11 Android app. Grant the API app camera and precise location permissions. See the [Termux API installation guide](https://github.com/termux/termux-api) and [Termux:X11 installation guide](https://github.com/termux/termux-x11).

Run these commands in Termux.

```sh
pkg install x11-repo
pkg install python python-tkinter python-pillow termux-api termux-x11-nightly
termux-camera-info
termux-sensor -l
termux-x11 :1 &
export DISPLAY=:1
```

Copy main.py and the fleet folder to a directory in Termux home. In that directory run the following command, substituting the manager PC address, device token, assigned vehicle ID and the driver-facing camera ID from termux-camera-info.

```sh
python main.py phone --server http://MANAGER_PC_IP:8765 --token DEVICE_TOKEN --vehicle 1 --camera 1
```

Open Termux:X11 and tap **Start sensors and share camera**. Keep it foregrounded during the demonstration. A second phone uses the same server and a different assigned vehicle ID. Double-click a vehicle in the manager dashboard to view its latest camera snapshot. Closing the phone window ends monitoring.

## Explain the Python design

| Class | Responsibility |
| --- | --- |
| AndroidSensors | Reads the phone hardware and prepares small JPEGs and timestamped motion readings. |
| TrainedDetector | Runs one shared copy of the camera model on the manager PC. |
| RiskEngine | Combines behavior duration and speed to decide the alert level. |
| DeviceSession | Links readings to the current trip, queues them on the phone and uploads them to the server. |
| PhoneDriver | Updates the driver's Tkinter window and plays the warning. |
| OwnerApp and Store | Display all vehicles and preserve assignment history and events in SQLite. |

The classes use composition. For example, PhoneDriver receives its DeviceSession and AndroidSensors as constructor arguments. Both the desktop simulator and the phone use the same RiskEngine. Sensor and network operations run in background threads. A queue carries results to the Tkinter thread.

Accelerometer values include gravity and use the phone's axes. Gyroscope values measure rotation. Both are visible in the manager's live view. Vehicle braking would require calibration for the phone mount. The motion rule currently uses GPS speed. Some Android providers can return zero when speed is unavailable because the Termux location response omits Android's speed-validity flag. GPS alone cannot identify reverse gear.

## Verify on hardware

With a stationary vehicle, check the assigned name and route, driver-facing image, GPS reception outdoors, sensor readings and audible speech. Turn the phone slightly and watch the gyro change. With two phones verify the manager sees the correct camera for each vehicle. Disconnect Wi-Fi and check that camera assessment becomes UNKNOWN. Reconnect and verify queued readings reach the original trip. Snapshot rate depends on Android hardware. Field accuracy, audio volume and phone-specific permissions require a physical test.
