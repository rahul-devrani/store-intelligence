"""
pipeline/reid.py — Re-identification utilities.

Re-exports CrossCameraReIDEngine and LocalTrackRepairer from tracker.py
so that detect.py can import from a single dedicated module.

Also exposes a convenience function to build appearance descriptors
without importing the full tracker module.
"""
from __future__ import annotations

# Re export the two engines defined in tracker.py
from pipeline.tracker import CrossCameraReIDEngine, LocalTrackRepairer, _build_rich_descriptor

import numpy as np


def build_descriptor(frame: "np.ndarray", bbox: "np.ndarray") -> "np.ndarray":
    """
    Build a 66-dim appearance descriptor from a frame region.

    The descriptor combines:
      - RGB colour histogram (3 × 16 bins)
      - HSV hue histogram (16 bins)
      - Bounding-box aspect ratio (normalised)
      - Height estimate (normalised)

    Used by both the cross-camera Re-ID engine and the REENTRY detector.
    Caller should L2-normalise before cosine comparison (handled internally).
    """
    return _build_rich_descriptor(frame, bbox)


__all__ = [
    "CrossCameraReIDEngine",
    "LocalTrackRepairer",
    "build_descriptor",
]
