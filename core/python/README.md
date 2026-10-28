# edgelens-sdk — Python client for the EdgeLens Edge AI Device Farm

The base Python client used by all Python EdgeLens integrations (pytest, Robot Framework, MLflow, W&B, the CLI, and the MCP server).

## Install

```bash
pip install edgelens-sdk
```

The distribution is `edgelens-sdk`; the import name is `edgelens`
(`from edgelens import EdgeLensClient`). The PyPI package named
`edgelens` is an unrelated project and is not this SDK.

## Quick Start

```python
from edgelens import EdgeLensClient

client = EdgeLensClient()  # reads EDGELENS_API_KEY from env

with client.create_session(device_type="recamera-2002", os="stock-os") as session:
    session.wait_ready()

    session.device.deploy(model="./models/face_detection.cvimodel")
    session.device.display.play("./test_data/crowd_scene.mp4")

    stats = session.device.inference.run(duration=30)
    assert stats.fps.avg > 15
```

For reCamaginedOS (raw, customer provides binary):

```python
with client.create_session(device_type="recamera-2002", os="recamagined") as session:
    session.wait_ready()

    # Files land in /userdata/Models/ on reCamaginedOS.
    session.device.deploy(
        model="./build/my_inference",
        files=["./models/my_model.cvimodel"],
    )

    result = session.device.exec(
        "chmod +x /userdata/Models/my_inference && "
        "/userdata/Models/my_inference "
        "--model /userdata/Models/my_model.cvimodel --duration 10"
    )
    assert result.success
```

On reCamaginedOS, `deploy(model=..., files=[...])` places the model and
each file in `/userdata/Models/` under its base filename. Files arrive
readable but not executable: before running a deployed binary, make it
executable, e.g. `chmod +x /userdata/Models/my_inference`.

## API Surface

- `EdgeLensClient` — entry point, creates sessions
- `Session` — session lifecycle (wait_ready, refresh, release)
- `Device` — device operations
  - `device.deploy()` — model deployment
  - `device.display.*` — display control (play, show, stop)
  - `device.inference.*` — built-in inference (stock OS only)
  - `device.exec()` — run commands via SSH
  - `device.ssh()` — SSH connection details
  - `device.info()` — device info report
  - `device.stream_url()` — camera stream URL (stock OS only)

## Development

```bash
cd core/python
pip install -e ".[dev]"
pytest
```

## License

MIT
