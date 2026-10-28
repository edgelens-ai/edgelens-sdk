"""Type definitions and result models."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DeviceType(str, Enum):
    RECAMERA_2002 = "recamera-2002"


class OSType(str, Enum):
    # Value matches the API's documented OS type enum and the
    # image-registry path "stock-os/<version>/...". The TypeScript SDK
    # uses the same string.
    STOCK = "stock-os"
    RECAMAGINED = "recamagined"


class SessionStatus(str, Enum):
    PENDING = "pending"
    ALLOCATING = "allocating"
    FLASHING = "flashing"
    READY = "ready"
    EXPIRED = "expired"
    RELEASED = "released"
    ERROR = "error"


class BBox(BaseModel):
    """Bounding box in pixel coordinates."""

    x: int
    y: int
    w: int
    h: int


class Detection(BaseModel):
    """A single detection result from inference."""

    label: str
    confidence: float
    bbox: Optional[BBox] = None
    frame: Optional[int] = None


class PercentileStats(BaseModel):
    """Distribution statistics for a metric."""

    avg: float
    min: float
    max: float
    p50: float
    p95: float
    p99: float


class MemoryStats(BaseModel):
    rss_mb_start: float = Field(alias="start")
    rss_mb_end: float = Field(alias="end")
    rss_mb_peak: float = Field(alias="peak")


class InferenceStats(BaseModel):
    """Aggregated metrics from an inference run."""

    duration_s: float
    total_frames: int
    fps: PercentileStats
    latency_ms: PercentileStats
    detections: list[Detection] = Field(default_factory=list)
    memory: Optional[dict] = None
    temperature_c: Optional[dict] = None


class InferenceSnapshot(BaseModel):
    """Single point-in-time inference metrics, used by streaming/snapshots."""

    fps: float
    latency_ms: float
    detection_count: int
    temperature_c: Optional[float] = None


class DeviceConnection(BaseModel):
    """Connection details for a ready session."""

    mac: str
    host: str
    ssh_port: int = 22
    ssh_user: str
    # Kept out of repr()/str() so assertion output, tracebacks and logs
    # never carry it. model_dump() still includes it.
    ssh_password: str = Field(repr=False)
    web_ui: Optional[str] = None
    os: OSType


class DeviceInfo(BaseModel):
    """Device information report (from collect_device_info.sh)."""

    collected_at: str
    hostname: str
    hardware: dict
    firmware: dict
    storage: dict
    network: dict
    peripherals: dict
    npu: dict
    system: dict
    logs: dict


class SSHCredentials(BaseModel):
    user: str
    host: str
    port: int = 22
    password: str = Field(repr=False)
