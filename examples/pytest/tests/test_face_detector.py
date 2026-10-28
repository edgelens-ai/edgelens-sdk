"""Face detector benchmark suite — the example project.

Demonstrates the `device` fixture from pytest-edgelens against both
OS tiers. Every test is one acceptance criterion (no bundled
assertions) so a failure points straight at the broken bar.

Run against the platform with a real key in ``EDGELENS_API_KEY``:

    pytest -v                            # stock-os (default)
    pytest -v --edgelens-os=recamagined

Model + binary assets live in ``../models`` and are resolved by
``asset()`` (below) relative to this file, so the suite runs from any
working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest


MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

FACE_MODEL = "scrfd_500m_kps_int8.cvimodel"
CUSTOM_BINARY = "sscma-model"


def asset(name: str) -> str:
    """Absolute path to a bundled model/binary asset. Skips the test
    cleanly if the asset isn't present (so a partial checkout doesn't
    error at call time)."""
    path = MODELS_DIR / name
    if not path.exists():
        pytest.skip(f"asset {name!r} not found at {path}")
    return str(path)


# ---- stock-os: built-in inference engine ---------------------------------


@pytest.mark.edgelens(os="stock-os")
def test_face_latency(device):
    """p95 latency under 100 ms is the interactive-UX budget."""
    device.deploy(model=asset(FACE_MODEL))
    stats = device.inference.run(duration=30)
    assert stats.latency_ms.p95 < 100, (
        f"p95 latency {stats.latency_ms.p95}ms exceeds 100ms budget"
    )


@pytest.mark.edgelens(os="stock-os")
def test_face_fps_floor(device):
    """15 fps is the live-video floor for our use case."""
    device.deploy(model=asset(FACE_MODEL))
    stats = device.inference.run(duration=30)
    assert stats.fps.avg >= 15, (
        f"avg fps {stats.fps.avg} below 15 fps floor"
    )


# ---- recamagined: ship your own binary -----------------------------------


@pytest.mark.edgelens(os="recamagined")
def test_custom_binary_runs_clean(device):
    """For customers who bring their own inference binary.

    ``deploy`` lands the binary + model in ``/userdata/Models/`` on
    reCamaginedOS; run it from there over the exec channel.
    """
    device.deploy(model=asset(CUSTOM_BINARY), files=[asset(FACE_MODEL)])
    r = device.exec(
        f"/userdata/Models/{CUSTOM_BINARY} "
        f"--model /userdata/Models/{FACE_MODEL} --duration 5"
    )
    assert r.success, r.stderr
    assert "ERROR" not in r.stdout


# ---- OS-agnostic ---------------------------------------------------------


def test_device_info(device):
    """Works on either OS — just sanity checks the device record."""
    info = device.info()
    assert info.hostname
    # `hardware` is a free-form dict from collect_device_info.sh — use
    # item access, not attribute access.
    assert info.hardware.get("cpu_arch") == "riscv64"
