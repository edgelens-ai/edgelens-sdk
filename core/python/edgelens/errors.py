"""EdgeLens client exceptions."""

from __future__ import annotations


class EdgeLensError(Exception):
    """Base exception for all EdgeLens client errors."""


class AuthenticationError(EdgeLensError):
    """API key is missing, invalid, or scope-restricted."""


class SessionError(EdgeLensError):
    """Session could not be created, allocated, or accessed."""


class DeviceError(EdgeLensError):
    """An operation on the device failed."""


class TimeoutError(EdgeLensError):
    """An operation did not complete within the allotted time."""
