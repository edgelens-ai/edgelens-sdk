"""EdgeLens Python client.

Test edge AI models on real hardware from your Python code.

Example:
    from edgelens import EdgeLensClient

    client = EdgeLensClient(api_key="...")
    session = client.create_session(device_type="recamera-2002", os="stock-os")
    session.wait_ready()

    session.device.deploy(model="./models/face_detection.cvimodel")
    session.device.display.play("./test_data/crowd_scene.mp4")
    stats = session.device.inference.run(duration=30)

    assert stats.fps.avg > 15
    session.release()
"""

from edgelens._version import __version__ as __version__
from edgelens._http import RetryPolicy
from edgelens.client import EdgeLensClient
from edgelens.errors import (
    EdgeLensError,
    AuthenticationError,
    SessionError,
    DeviceError,
    TimeoutError,
)
from edgelens.session import Session
from edgelens.device import Device
from edgelens.types import (
    DeviceType,
    OSType,
    SessionStatus,
    InferenceStats,
    Detection,
    DeviceInfo,
    BBox,
    PercentileStats,
)

__all__ = [
    "EdgeLensClient",
    "Session",
    "Device",
    "DeviceType",
    "OSType",
    "SessionStatus",
    "InferenceStats",
    "Detection",
    "DeviceInfo",
    "BBox",
    "PercentileStats",
    "RetryPolicy",
    "EdgeLensError",
    "AuthenticationError",
    "SessionError",
    "DeviceError",
    "TimeoutError",
]
