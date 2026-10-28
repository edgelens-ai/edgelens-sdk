# Robot Framework

`robotframework-edgelens` ships keywords that map directly to the
SDK surface — useful when your QA team writes tests in Robot's
keyword-driven style and you want them to hit real hardware without
learning Python.

```bash
pip install robotframework-edgelens
export EDGELENS_API_KEY=el_live_xxx
```

## Quickstart

```robot
*** Settings ***
Library    EdgeLensLibrary    api_key=%{EDGELENS_API_KEY}

*** Test Cases ***
Face Detector Hits Latency Budget
    Request Device    device_type=recamera-2002    os=stock-os
    Deploy Model    ${CURDIR}/models/face.cvimodel
    ${stats}=    Run Inference    duration=30
    Should Be True    ${stats}[fps][avg] >= 15
    Should Be True    ${stats}[latency_ms][p95] < 100
    [Teardown]    Release Device
```

## Library scope

By default `EdgeLensLibrary` is **suite-scoped** — tests in one suite
share a session. Override when each test needs a fresh device:

```robot
*** Settings ***
Library    EdgeLensLibrary    api_key=%{EDGELENS_API_KEY}    scope=TEST
```

| Scope | When |
|---|---|
| `TEST` | Each test needs a fresh device. |
| `SUITE` (default) | Tests in one suite share a device. |
| `GLOBAL` | One device for the whole run. |

## Keywords

| Keyword | What |
|---|---|
| `Request Device    device_type=...    os=...    timeout=...    wait_timeout=300` | Allocate and block until `status=ready`. Returns the session id. |
| `Release Device` | Release. Safe in `[Teardown]` when no session was allocated. |
| `Get Session Id` | Id of the active session. |
| `Get Session Status` | Current session status. |
| `Deploy Model    ${path}    config=${path}    files=${list}` | Push a model, plus optional config and extra files, from local paths. On `recamagined` they land in `/userdata/Models/`, not executable. |
| `Run Inference    duration=${seconds}` | Run for N seconds; return aggregated stats. |
| `Start Inference` / `Stop Inference` | Start / stop the built-in inference engine. |
| `Run Inference Once` | One frame of detections. |
| `Get Inference Stats` | One snapshot of fps + latency. |
| `Play On Display    ${source_url}    loop=${True}` | Play a video. |
| `Show On Display    ${source_url}` | Show a still. |
| `Stop Display` | Stop. |
| `Get Display Status` | Current display state. |
| `Execute On Device    ${command}    timeout=60` | Run a shell command; returns `stdout`, `stderr`, `exit_code`. |
| `Get Device Info` | Hostname, hardware, OS version. |
| `Get Stream URL` | Camera stream WebSocket URL (stock-os only). |
| `Get SSH Details` | `{user, host, port}` dict. |
| `Set SSH Password Variable    name=${SSH_PASSWORD}    scope=TEST` | Store the SSH password in a variable without logging its value. Robot logs keyword arguments only at TRACE, so passing `${SSH_PASSWORD}` on stays out of `log.html` and `output.xml` at the default log level. |
| `Get SSH Password` | SSH password as a return value. **Robot logs the assignment `${pw}=    Get SSH Password` at INFO, value included**, so the password lands in `log.html` and `output.xml`, which CI presets upload as artifacts. Use `Set SSH Password Variable` instead. |

## Patterns

### Parameterized tests via templates

```robot
*** Settings ***
Library    EdgeLensLibrary    api_key=%{EDGELENS_API_KEY}    scope=SUITE
Test Template    Model Meets FPS Floor

*** Test Cases ***                    MODEL                 MIN_FPS
Face Detector                         ${CURDIR}/face.cvimodel       15
Person Detector                       ${CURDIR}/person.cvimodel     12
Vehicle Detector                      ${CURDIR}/vehicle.cvimodel    10

*** Keywords ***
Model Meets FPS Floor
    [Arguments]    ${model}    ${min_fps}
    Deploy Model    ${model}
    ${stats}=    Run Inference    duration=20
    Should Be True    ${stats}[fps][avg] >= ${min_fps}
```

`scope=SUITE` shares one device across the three template variants —
otherwise each row would pay the flash cost.

### Custom binary on `recamagined`

```robot
*** Test Cases ***
Custom Binary Runs Clean
    Request Device    device_type=recamera-2002    os=recamagined
    ${files}=    Create List    ${CURDIR}/build/my_inference
    Deploy Model    ${CURDIR}/models/m.cvimodel    files=${files}
    ${r}=    Execute On Device
    ...    chmod +x /userdata/Models/my_inference && /userdata/Models/my_inference --model /userdata/Models/m.cvimodel --duration 5
    Should Be Equal As Integers    ${r}[exit_code]    0
    Should Not Contain    ${r}[stdout]    ERROR
    [Teardown]    Release Device
```

On `recamagined`, `Deploy Model` places the model and each file in
`/userdata/Models/` under its base filename. Files arrive readable but
not executable: `chmod +x` a deployed binary before running it.

## Anti-patterns

- Calling `Request Device` without a `[Teardown]    Release Device`.
  Robot's test isolation doesn't auto-release for you — be explicit.
- `Sleep    30s` to "wait for ready" — `Request Device` already polls
  until ready, bounded by `wait_timeout`.
- One session per row when you can share via `scope=SUITE` and
  parametrized templates.

## Example project

Full working project: [`examples/robot/`](../../examples/robot/).
