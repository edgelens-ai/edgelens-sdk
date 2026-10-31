# pytest example

A minimal pytest project using the `edgelens-pytest` plugin. It
allocates one device for the run, runs a shell command on it, reads its
device info, and releases it when the run ends.

```
examples/pytest-basic/
├── README.md
├── requirements.txt
└── tests/
    └── test_device.py
```

## Setup

```bash
cd examples/pytest-basic
pip install -r requirements.txt
export EDGELENS_API_KEY=el_test_xxxxxxxxxxxxxxxxxxxx
```

Or run it in the `edgelensai/edgelens-sdk` CI image, which already has
the SDK and the pytest plugin installed.

## Run

```bash
pytest
```

The plugin is loaded automatically through its `pytest11` entry point,
so there is no `conftest.py`. The `device` fixture is session-scoped:
both tests share one device.

Useful flags:

```bash
pytest --edgelens-os=recamagined          # pick the OS to flash
pytest --edgelens-scope=function          # a fresh device per test
pytest --junit-xml=junit.xml              # JUnit with device metadata
```

`EDGELENS_BASE_URL` (or `--edgelens-base-url`) overrides the API base
URL; the default is `https://api.edgelens.ai`.

## What the tests do

- `test_run_command` runs `uname -a` on the device with `device.exec()`
  and checks that it exited 0 and printed something.
- `test_device_info` reads `device.info()` and checks the hostname, and
  that the allocated device has a MAC address.

See the [pytest framework guide](../../docs/frameworks/pytest.md) for
markers, scopes and every CLI option.
