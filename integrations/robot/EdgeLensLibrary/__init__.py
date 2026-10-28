"""Robot Framework library for the EdgeLens Edge AI Device Farm.

Import in a Robot suite via ``Library    EdgeLensLibrary``. Keywords
mirror the Python SDK's surface — session lifecycle (Request Device /
Release Device), file ops (Deploy Model), the display
namespace (Play On Display / Show On Display / ...), the inference
namespace (Start Inference / Run Inference / ...), and helpers (Get
SSH Details / Execute On Device / Get Device Info).
"""

from EdgeLensLibrary._version import __version__ as __version__
from EdgeLensLibrary.library import EdgeLensLibrary

__all__ = ["EdgeLensLibrary"]
