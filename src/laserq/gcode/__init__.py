"""Generación de G-code: builder, corte, raster, rotativo, tipografía de trazo."""

from .builder import BoundingBox, GcodeOptions, GcodeProgram, measure
from .cut import HOLE, PART, Contour, CutOptions, compensate, cut_contours, notch
from .preview import parse_segments, render, travel_distance
from .raster import RasterOptions, dither, engrave_image, raster_to_gcode
from .rotary import ConeMapping, RotaryConfig, cylinder, focus_band_width, full_turn_mm

__all__ = [
    "GcodeProgram", "GcodeOptions", "BoundingBox", "measure",
    "Contour", "CutOptions", "HOLE", "PART", "compensate", "cut_contours", "notch",
    "RasterOptions", "engrave_image", "raster_to_gcode", "dither",
    "ConeMapping", "RotaryConfig", "cylinder", "full_turn_mm", "focus_band_width",
    "render", "parse_segments", "travel_distance",
]
