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

Cubre además Ñ y las vocales acentuadas, que no son un lujo: un soporte
personalizado que dice "PENA" en vez de "PEÑA" es una pieza tirada y un
cliente enojado. Los diacríticos se dibujan por encima de la caja del
glifo (hasta y = 1.26), así que una línea con acentos ocupa un poco más de
alto que una sin ellos; el ancho no cambia.

Un diacrítico que **no** tenemos —una cedilla, una diéresis sobre la i— se
descarta en lugar de fallar: "Français" se graba "FRANCAIS". Es preferible
eso a un hueco en la pieza.
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
    """Pasa a mayúsculas y resuelve los diacríticos contra la fuente.

    Lo que tiene glifo se conserva: "Martín" queda "MARTÍN" y se graba con
    su tilde. Lo que no lo tiene se descompone y se le sacan las marcas,
    así "Français" queda "FRANCAIS". Se pierde la cedilla, pero se graba:
    en una pieza personalizada es mucho peor un hueco donde iba una letra.
    """
    out = []
    for char in text.upper():
        if char in GLYPHS:
            out.append(char)
            continue
        decomposed = unicodedata.normalize("NFD", char)
        out.append("".join(c for c in decomposed if unicodedata.category(c) != "Mn"))
    return "".join(out)


#: Diacríticos, dibujados por encima de la caja del glifo. Van aparte y se
#: componen con la letra base para no repetir veinte veces los mismos trazos.
_ACUTE: list[Polyline] = [[(0.22, 1.12), (0.42, 1.26)]]
_TILDE: list[Polyline] = [[(0.10, 1.15), (0.20, 1.24), (0.40, 1.13), (0.50, 1.22)]]
_DIAERESIS: list[Polyline] = [[(0.16, 1.16), (0.25, 1.16)], [(0.35, 1.16), (0.44, 1.16)]]

for _base, _mark, _accented in (
    ("A", _ACUTE, "Á"),
    ("E", _ACUTE, "É"),
    ("I", _ACUTE, "Í"),
    ("O", _ACUTE, "Ó"),
    ("U", _ACUTE, "Ú"),
    ("N", _TILDE, "Ñ"),
    ("U", _DIAERESIS, "Ü"),
):
    GLYPHS[_accented] = [list(stroke) for stroke in GLYPHS[_base]] + \
                        [list(stroke) for stroke in _mark]
del _base, _mark, _accented


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


#: Separación entre pasadas al engrosar un trazo. Menos que esto es tiempo
#: de máquina sin ganancia visible; más deja el trazo rayado.
PASO_GROSOR = 0.15


def thicken(polylines: list[Polyline], grosor_mm: float,
            *, paso: float = PASO_GROSOR) -> list[Polyline]:
    """Repite cada trazo desplazado, para que la letra tenga cuerpo.

    Una tipografía de trazo único deja una línea del ancho del kerf: a 12 mm
    de alto eso se lee flaco aunque esté bien quemado. Repetir el mismo
    recorrido corrido unas décimas en cruz le da ancho al trazo sin rellenar
    contornos ni pasar a raster.

    `grosor_mm` es el ancho **agregado**, aproximado: el ancho final incluye
    además el kerf del láser. 0 devuelve el trazo pelado.

    Las copias de un mismo trazo salen juntas y no intercaladas, para no
    pagar un traslado por cada desplazamiento.
    """
    if grosor_mm <= 0:
        return [list(trazo) for trazo in polylines]

    anillos = max(1, round(grosor_mm / (2 * paso)))
    offsets: list[tuple[float, float]] = [(0.0, 0.0)]
    for indice in range(1, anillos + 1):
        distancia = indice * paso
        offsets += [(distancia, 0.0), (-distancia, 0.0),
                    (0.0, distancia), (0.0, -distancia)]

    out: list[Polyline] = []
    for trazo in polylines:
        for dx, dy in offsets:
            out.append([(x + dx, y + dy) for x, y in trazo])
    return out
