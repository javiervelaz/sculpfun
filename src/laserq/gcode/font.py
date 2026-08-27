"""Tipografía de trazo simple, para rotular piezas.

Cada glifo es una lista de polilíneas en una caja de 0.6 (ancho) por 1.0
(alto), que después se escala al alto pedido en milímetros. Trazo único:
el láser recorre la línea, no rellena contornos, así que grabar un nombre
son décimas de segundo en vez de minutos.

Cubre A-Z, 0-9 y algunos signos. Alcanza para etiquetas, numeración de
series y personalización con nombres, que es el 90% de lo que se graba.
Para tipografías con peso, serifas o acentos hay que ir a una fuente real
o convertir SVG; en ese caso lo que se reutiliza es el pipeline, no los
glifos.

Los acentos se descartan en lugar de fallar: "MARTÍN" se graba "MARTIN".
Es preferible eso a un hueco en la pieza.
"""

from __future__ import annotations

import unicodedata

Polyline = list[tuple[float, float]]

GLYPH_ASPECT = 0.6  # ancho / alto de la caja del glifo
GLYPH_SPACING = 0.25  # separación entre caracteres, en unidades de alto

# Coordenadas normalizadas: (0,0) abajo a la izquierda, (0.6,1.0) arriba a
# la derecha. El orden de los puntos define el recorrido del cabezal.
GLYPHS: dict[str, list[Polyline]] = {
    " ": [],
    "A": [[(0, 0), (0.3, 1), (0.6, 0)], [(0.12, 0.4), (0.48, 0.4)]],
    "B": [
        [(0, 0), (0, 1), (0.45, 1), (0.6, 0.85), (0.6, 0.65), (0.45, 0.5), (0, 0.5)],
        [(0.45, 0.5), (0.6, 0.35), (0.6, 0.15), (0.45, 0), (0, 0)],
    ],
    "C": [[(0.6, 0.85), (0.45, 1), (0.15, 1), (0, 0.85), (0, 0.15), (0.15, 0),
           (0.45, 0), (0.6, 0.15)]],
    "D": [[(0, 0), (0, 1), (0.4, 1), (0.6, 0.8), (0.6, 0.2), (0.4, 0), (0, 0)]],
    "E": [[(0.6, 1), (0, 1), (0, 0), (0.6, 0)], [(0, 0.5), (0.45, 0.5)]],
    "F": [[(0.6, 1), (0, 1), (0, 0)], [(0, 0.5), (0.45, 0.5)]],
    "G": [[(0.6, 0.85), (0.45, 1), (0.15, 1), (0, 0.85), (0, 0.15), (0.15, 0),
           (0.45, 0), (0.6, 0.15), (0.6, 0.45), (0.35, 0.45)]],
    "H": [[(0, 1), (0, 0)], [(0.6, 1), (0.6, 0)], [(0, 0.5), (0.6, 0.5)]],
    "I": [[(0.1, 1), (0.5, 1)], [(0.3, 1), (0.3, 0)], [(0.1, 0), (0.5, 0)]],
    "J": [[(0.6, 1), (0.6, 0.2), (0.45, 0), (0.2, 0), (0.05, 0.2)]],
    "K": [[(0, 1), (0, 0)], [(0.6, 1), (0, 0.45)], [(0.2, 0.62), (0.6, 0)]],
    "L": [[(0, 1), (0, 0), (0.6, 0)]],
    "M": [[(0, 0), (0, 1), (0.3, 0.55), (0.6, 1), (0.6, 0)]],
    "N": [[(0, 0), (0, 1), (0.6, 0), (0.6, 1)]],
    "O": [[(0.15, 1), (0.45, 1), (0.6, 0.85), (0.6, 0.15), (0.45, 0), (0.15, 0),
           (0, 0.15), (0, 0.85), (0.15, 1)]],
    "P": [[(0, 0), (0, 1), (0.45, 1), (0.6, 0.85), (0.6, 0.6), (0.45, 0.45), (0, 0.45)]],
    "Q": [[(0.15, 1), (0.45, 1), (0.6, 0.85), (0.6, 0.15), (0.45, 0), (0.15, 0),
           (0, 0.15), (0, 0.85), (0.15, 1)], [(0.35, 0.25), (0.62, -0.02)]],
    "R": [[(0, 0), (0, 1), (0.45, 1), (0.6, 0.85), (0.6, 0.6), (0.45, 0.45), (0, 0.45)],
          [(0.3, 0.45), (0.6, 0)]],
    "S": [[(0.6, 0.85), (0.45, 1), (0.15, 1), (0, 0.85), (0, 0.65), (0.15, 0.5),
           (0.45, 0.5), (0.6, 0.35), (0.6, 0.15), (0.45, 0), (0.15, 0), (0, 0.15)]],
    "T": [[(0, 1), (0.6, 1)], [(0.3, 1), (0.3, 0)]],
    "U": [[(0, 1), (0, 0.15), (0.15, 0), (0.45, 0), (0.6, 0.15), (0.6, 1)]],
    "V": [[(0, 1), (0.3, 0), (0.6, 1)]],
    "W": [[(0, 1), (0.15, 0), (0.3, 0.6), (0.45, 0), (0.6, 1)]],
    "X": [[(0, 1), (0.6, 0)], [(0, 0), (0.6, 1)]],
    "Y": [[(0, 1), (0.3, 0.5), (0.6, 1)], [(0.3, 0.5), (0.3, 0)]],
    "Z": [[(0, 1), (0.6, 1), (0, 0), (0.6, 0)]],
    "0": [[(0.15, 1), (0.45, 1), (0.6, 0.85), (0.6, 0.15), (0.45, 0), (0.15, 0),
           (0, 0.15), (0, 0.85), (0.15, 1)]],
    "1": [[(0.1, 0.8), (0.3, 1), (0.3, 0)], [(0.1, 0), (0.5, 0)]],
    "2": [[(0, 0.85), (0.15, 1), (0.45, 1), (0.6, 0.85), (0.6, 0.65), (0, 0), (0.6, 0)]],
    "3": [[(0, 1), (0.6, 1), (0.25, 0.55), (0.45, 0.55), (0.6, 0.4), (0.6, 0.15),
           (0.45, 0), (0.15, 0), (0, 0.15)]],
    "4": [[(0.45, 0), (0.45, 1), (0, 0.3), (0.6, 0.3)]],
    "5": [[(0.6, 1), (0, 1), (0, 0.55), (0.4, 0.6), (0.6, 0.45), (0.6, 0.15),
           (0.45, 0), (0.15, 0), (0, 0.15)]],
    "6": [[(0.55, 0.9), (0.4, 1), (0.15, 1), (0, 0.8), (0, 0.15), (0.15, 0), (0.45, 0),
           (0.6, 0.15), (0.6, 0.35), (0.45, 0.5), (0.15, 0.5), (0, 0.35)]],
    "7": [[(0, 1), (0.6, 1), (0.2, 0)]],
    "8": [[(0.15, 0.5), (0, 0.65), (0, 0.85), (0.15, 1), (0.45, 1), (0.6, 0.85),
           (0.6, 0.65), (0.45, 0.5), (0.15, 0.5), (0, 0.35), (0, 0.15), (0.15, 0),
           (0.45, 0), (0.6, 0.15), (0.6, 0.35), (0.45, 0.5)]],
    "9": [[(0.05, 0.1), (0.2, 0), (0.45, 0), (0.6, 0.2), (0.6, 0.85), (0.45, 1),
           (0.15, 1), (0, 0.85), (0, 0.65), (0.15, 0.5), (0.45, 0.5), (0.6, 0.65)]],
    ".": [[(0.25, 0), (0.35, 0)]],
    ",": [[(0.3, 0.1), (0.2, -0.1)]],
    "-": [[(0.1, 0.5), (0.5, 0.5)]],
    "_": [[(0, 0), (0.6, 0)]],
    "/": [[(0, 0), (0.6, 1)]],
    "\\": [[(0, 1), (0.6, 0)]],
    ":": [[(0.25, 0.3), (0.35, 0.3)], [(0.25, 0.7), (0.35, 0.7)]],
    "'": [[(0.3, 0.8), (0.3, 1)]],
    "+": [[(0.3, 0.25), (0.3, 0.75)], [(0.05, 0.5), (0.55, 0.5)]],
    "=": [[(0.05, 0.35), (0.55, 0.35)], [(0.05, 0.65), (0.55, 0.65)]],
    "#": [[(0.15, 0), (0.25, 1)], [(0.4, 0), (0.5, 1)], [(0, 0.3), (0.6, 0.3)],
          [(0, 0.7), (0.6, 0.7)]],
    "(": [[(0.45, 1), (0.2, 0.7), (0.2, 0.3), (0.45, 0)]],
    ")": [[(0.15, 1), (0.4, 0.7), (0.4, 0.3), (0.15, 0)]],
    "!": [[(0.3, 0.25), (0.3, 1)], [(0.3, 0), (0.3, 0.05)]],
    "?": [[(0, 0.8), (0.15, 1), (0.45, 1), (0.6, 0.8), (0.6, 0.6), (0.3, 0.45),
           (0.3, 0.25)], [(0.3, 0), (0.3, 0.05)]],
    "*": [[(0.3, 0.3), (0.3, 0.9)], [(0.05, 0.45), (0.55, 0.75)],
          [(0.05, 0.75), (0.55, 0.45)]],
    "\u00b0": [[(0.2, 0.75), (0.35, 0.75), (0.4, 0.85), (0.35, 0.95), (0.2, 0.95),
                (0.15, 0.85), (0.2, 0.75)]],
}


def normalize(text: str) -> str:
    """Pasa a mayúsculas y saca acentos y diacríticos.

    Descomponer y filtrar las marcas convierte "MARTÍN" en "MARTIN" y "ñ"
    en "N". Se pierde el acento, pero se graba: en una pieza personalizada
    es mucho peor un hueco donde iba una letra.
    """
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.upper()


def glyph(char: str) -> list[Polyline]:
    """Polilíneas de un carácter en la caja unitaria. Desconocido -> vacío."""
    return [list(p) for p in GLYPHS.get(char.upper(), [])]


def unsupported(text: str) -> list[str]:
    """Caracteres del texto que la fuente no puede grabar.

    Chequealo antes de una tirada: es la diferencia entre enterarte ahora o
    cuando ya tenés 200 piezas con un nombre incompleto.
    """
    return sorted({c for c in normalize(text) if c not in GLYPHS})


def text_width(text: str, height: float) -> float:
    """Ancho total que va a ocupar el texto al alto dado, en mm."""
    text = normalize(text)
    if not text:
        return 0.0
    per_char = GLYPH_ASPECT + GLYPH_SPACING
    return (len(text) * per_char - GLYPH_SPACING) * height


def text_polylines(
    text: str, x: float, y: float, height: float = 4.0, *, center: bool = False
) -> list[Polyline]:
    """Convierte un texto en polilíneas ubicadas en (x, y), en mm.

    (x, y) es la esquina inferior izquierda, salvo que `center` sea True,
    en cuyo caso (x, y) es el centro horizontal sobre la línea de base.
    """
    text = normalize(text)
    if center:
        x -= text_width(text, height) / 2

    out: list[Polyline] = []
    cursor = x
    step = (GLYPH_ASPECT + GLYPH_SPACING) * height
    for char in text:
        for polyline in glyph(char):
            out.append([(cursor + px * height, y + py * height) for px, py in polyline])
        cursor += step
    return out
