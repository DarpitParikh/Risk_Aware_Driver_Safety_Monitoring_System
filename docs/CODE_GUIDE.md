# Explaining the project in the programming lab

## Architecture

```text
Driver Tkinter controls / trained camera classifier
                    |
               Measurements
                    |
               RiskEngine
                /       \
       local warning     SQLite outbox
                              |
                        HTTP JSON API
                              |
                     FleetServer + Store
                              |
                         SQLite database
                              |
                       Owner Tkinter app

Optional webcam -> JPEG -> server memory -> selected owner preview
```

Behavior measurements and camera preview are separate. The camera worker can run the trained classifier locally without sharing video with the owner. Speed and acceleration still come from explicitly simulated controls. The model does not infer eye closure or yawning.

## Read the code in this order

1. `fleet/risk.py`: small data classes, input validation, temporal risk calculation.
2. `fleet/detectors.py`: abstract interface, manually controlled and scenario implementations.
   `fleet/model_detector.py`: trained CPU classifier, exact preprocessing, confidence handling and observation freshness.
3. `fleet/storage.py`: database schema, CRUD, transactional assignments, logs.
4. `fleet/network.py`: one HTTP client method and a custom exception.
5. `fleet/server.py`: URL routing, authorization, validation, persistence.
6. `fleet/device.py`: local evaluation, durable queue, retry and deduplication behavior.
7. `fleet/driver_ui.py`: driver controls, local warnings, background networking/camera.
8. `fleet/owner_ui.py`: sidebar pages, tables, dialogs, live monitoring, export.
9. `main.py` and `fleet/demo.py`: startup and the multi-device demonstration.

## Python concepts used for a reason

| Concept | Example and purpose |
| --- | --- |
| Variables, conditions, loops | Score thresholds, per-behavior duration checks, rendering table rows |
| Functions and methods | Small operations for assigning trips, applying filters and evaluating risk |
| Lists, tuples, dictionaries | Rows, rules, records, snapshots and JSON messages |
| Deque | Rolling history of yawning episodes |
| Data classes | Explicit fields in `Measurements` and `RiskResult` |
| Object-oriented programming | `Store`, `ApiClient`, `DeviceSession`, UI classes |
| Abstraction and polymorphism | `Detector.read()` implemented by different input sources |
| Composition | `DeviceSession` contains an API client, risk engine and outbox |
| Modules and packages | Separate storage, networking, UI and business rules |
| Exceptions | `ApiError`, validation errors and recoverable camera failures |
| Context managers | Database transactions, files and HTTP responses close reliably |
| File handling | Config JSON, CSV export, rotating diagnostic logs |
| SQLite | Relationships, constraints, indexes, transactions and parameterized queries |
| Threads and synchronization | HTTP workers, camera thread, lock around assignment/risk state |
| Queues and events | Workers communicate with the Tkinter main thread without modifying widgets |
| Inheritance | HTTP request handler and detector implementations |
| Standard-library testing | Unit tests and HTTP/database integration tests |

We do not add advanced concepts merely to make the code look larger. For example, a generator or decorator is useful only when it simplifies a real responsibility. `@dataclass`, `@contextmanager`, and `@abstractmethod` already demonstrate purposeful decorators.

## Design principles

- **Single responsibility:** the risk engine computes risk, the store manages persistence, and UI classes manage widgets.
- **Separation of concerns:** widgets do not contain SQL; the server does not manipulate widgets.
- **Dependency injection:** constructors receive a store, API client or device session, making tests independent of production data.
- **Open for extension:** the trained detector implements `read()` without redesigning the database. More detectors can use the same interface later.
- **Composition over unnecessary inheritance:** the session owns collaborators rather than inheriting their behavior.
- **One source of truth:** trips and fleet records live on the server; local device state handles immediate warnings and queued telemetry.
- **Explicit limitations:** UNKNOWN and OFFLINE are distinct from LOW risk.

## Threading explanation

Tkinter runs its event loop on the main thread. Blocking network requests would freeze the window, so a worker performs HTTP requests and sends results through a queue. The main thread uses `after()` to read that queue and update widgets. The driver computes local risk on a regular Tkinter timer while separate workers handle HTTP and camera capture. A lock prevents assignment changes from racing with sample creation.

## Database integrity explanation

Each trip references one vehicle, driver and route. Partial unique indexes prevent a vehicle or driver from appearing in two active trips. Changing an assignment is one transaction: either both ending the old trip and creating the new one succeed, or neither does. Historical names are copied into the trip at creation time. Sample UUIDs make retry delivery idempotent.

## Suggested demonstration order

1. Explain the problem: a fleet owner needs actionable warnings and vehicle context.
2. Launch `main.py demo` and introduce the two interfaces.
3. Trigger prolonged eye closure; show the local sound and owner event.
4. Demonstrate recovery, UNKNOWN, and stopped-vehicle suppression.
5. Add a driver and change a trip; explain why earlier logs retain their old driver.
6. Filter logs by vehicle or driver and export CSV.
7. Enable **Use trained model**, explain the class score and simulated motion, then optionally enable video sharing. Explain why `other_activities` is UNKNOWN and why this model cannot measure drowsiness.
8. Run the tests and explain one risk test and one transaction test.

For a live disconnection demonstration, run server/owner/driver separately. Stop the server while keeping the driver open, trigger a warning, then restart the server with the same data directory. Local warnings continue and queued readings replay. If an assignment changed while the client was offline, readings outside the old trip are preserved as rejected records rather than attributed to the wrong driver.
