"""Generación de G-code: builder, raster, rotativo, tipografía de trazo."""

from .builder import BoundingBox, GcodeOptions, GcodeProgram, measure
from .raster import RasterOptions, dither, engrave_image, raster_to_gcode
from .preview import parse_segments, render, travel_distance
from .rotary import ConeMapping, RotaryConfig, cylinder, focus_band_width, full_turn_mm

__all__ = [
    "GcodeProgram", "GcodeOptions", "BoundingBox", "measure",
    "RasterOptions", "engrave_image", "raster_to_gcode", "dither",
    "ConeMapping", "RotaryConfig", "cylinder", "full_turn_mm", "focus_band_width",
    "render", "parse_segments", "travel_distance",
]
