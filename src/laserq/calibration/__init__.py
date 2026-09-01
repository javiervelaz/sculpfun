"""Placas de calibración: grabado, corte, letras y foco."""

from .cutcard import CutTestSpec, KerfCombSpec, build_cut_test, build_kerf_comb
from .lettercard import LetterTestSpec, build_letter_test
from .testcard import TestCardSpec, build_focus_ramp, build_test_card

__all__ = [
    "TestCardSpec", "build_test_card", "build_focus_ramp",
    "CutTestSpec", "build_cut_test", "KerfCombSpec", "build_kerf_comb",
    "LetterTestSpec", "build_letter_test",
]
