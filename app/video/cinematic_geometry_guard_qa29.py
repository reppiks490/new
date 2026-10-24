"""Opt-in, side-effect-free local master geometry admission guard (QA29).

This module is intentionally NOT wired into lead-owned cinematic_service.py.
The lead must choose an owner-PC resource budget before production integration.
No project data, media, credentials or prompts are read or logged.
"""
from __future__ import annotations

from fractions import Fraction
import re

# Conservative *proposal*, not a claim about the owner's GPU/CPU capability.
MAX_LOCAL_WIDTH = 8192
MAX_LOCAL_FRAME_PIXELS = 8192 * 2160


def validate_master_geometry(width: int, height: int, aspect_ratio: str) -> tuple[int, int]:
    """Reject impossible, oversized, or materially distorted output geometry.

    Uses exact rational arithmetic to avoid float overflow or lossy aspect
    comparisons. Error text intentionally never repeats owner input.
    """
    if (type(width) is not int or type(height) is not int
            or width < 2 or height < 2 or width % 2 or height % 2):
        raise ValueError("Master output geometry must have positive even dimensions")
    if (width > MAX_LOCAL_WIDTH or width * height > MAX_LOCAL_FRAME_PIXELS):
        raise ValueError("Master output geometry exceeds the proposed local resource budget")
    if not isinstance(aspect_ratio, str):
        raise ValueError("Master aspect ratio is invalid")
    match = re.fullmatch(r"([0-9]+):([0-9]+)", aspect_ratio)
    if match is None:
        raise ValueError("Master aspect ratio is invalid")
    numerator, denominator = map(int, match.groups())
    if numerator <= 0 or denominator <= 0:
        raise ValueError("Master aspect ratio is invalid")
    requested_width = Fraction(height * numerator, denominator)
    # An even-pixel width rounded to the nearest integer differs by <=1 pixel.
    # A clamped 2px output for an almost-zero requested width does not.
    if abs(Fraction(width) - requested_width) > 1:
        raise ValueError("Master output cannot represent the requested aspect ratio")
    return width, height
