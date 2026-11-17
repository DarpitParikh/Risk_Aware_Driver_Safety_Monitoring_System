# Phone GPS speed input

The Tkinter driver app can receive measured speed from a phone browser. The phone page is a sensor helper, not a replacement dashboard. Use the same Wi-Fi or phone hotspot for phone and driver PC. No coordinates are transmitted or stored. The browser supplies speed in metres/second; Python converts it to km/h.

## One-time HTTPS setup

Browsers require trusted HTTPS and location permission. Simply bypassing a certificate warning is not a reliable substitute. On the driver PC, find its LAN IPv4 address with `ipconfig`, then replace `192.168.1.10` below:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gps.txt
.\.venv\Scripts\python.exe tools/create_gps_certificate.py 192.168.1.10
```

Transfer **only** `data/gps-cert/phone-ca.crt` to your phone using USB or another trusted transfer method. Install it as a trusted CA certificate using the phone's certificate settings. On iOS, installing the profile also requires enabling full trust in Certificate Trust Settings. Exact menus depend on the phone. A managed phone may prohibit user certificates; in that case this local setup cannot be used without administrator support or an already trusted HTTPS endpoint.

Keep `server.key` on your PC. Remove the lab CA from the phone when finished with the project. Certificates expire after approximately 90 days. If the PC's IP changes, generate a fresh set in a different directory and install the corresponding CA.

## Run

```powershell
.\.venv\Scripts\python.exe main.py demo --phone-gps --gps-cert data/gps-cert/server.crt --gps-key data/gps-cert/server.key
```

The terminal prints a new pairing code each launch. On the phone open `https://192.168.1.10:8766/`, enter that code, tap **Start GPS**, and allow location access. If prompted by Windows Firewall, allow the connection on the private lab network. Leave the page foregrounded and screen awake. Synchronize phone and PC clocks.

For separate driver/server operation, add the same three GPS options to the existing `main.py driver ...` command. The phone connects to the **driver PC**, not the fleet server. Each driver process needs its own GPS port if several run on one PC. Demo vehicles 2 and 3 remain simulated.

## Expected behavior

- Motion sliders are disabled in GPS mode. Live speed feeds the existing speed-aware attention rules and is included in owner telemetry/logs with source `phone_gps`.
- Missing speed, no fix, position accuracy worse than 30 metres, or a fix older than five seconds makes assessment UNKNOWN. There is no automatic fallback to simulated speed or a stopped vehicle.
- An actual zero-speed fix is accepted. Browser speed can be null even when location is available; move outdoors with a good sky view to test, without operating the phone while driving.
- The 30-metre position-accuracy limit is a prototype filter, not a speed-accuracy guarantee. GPS can be unreliable at manoeuvring speeds and does not identify reverse gear.
- Acceleration is not measured in GPS mode. Its numeric telemetry field is zero as a placeholder; harsh-braking detection is unavailable. Camera behavior and GPS availability are both required in model mode.
- Stopping the sender, locking the screen, or losing the network produces UNKNOWN after at most five seconds without a fresh fix.

## Hardware acceptance check

Confirm a trusted connection, fresh speed displayed in Tkinter and on the owner console, and `phone_gps` in telemetry. Stop sending and verify UNKNOWN. Resume and verify recovery. Compare speed readings against a suitable reference on a controlled trip with a passenger operating the equipment. Automated tests use synthetic GPS samples; they do not establish physical GPS accuracy.

Browser references: [speed units and unavailable values](https://developer.mozilla.org/en-US/docs/Web/API/GeolocationCoordinates/speed), [location permissions and HTTPS](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/watchPosition).
