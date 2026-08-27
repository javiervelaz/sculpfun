"""Códigos de error y alarma de GRBL 1.1.

Traducir el número a texto en el momento en que ocurre te ahorra
media hora de buscar tablas en foros cada vez que algo falla.
"""

from __future__ import annotations


class LaserqError(Exception):
    """Base de todos los errores de la librería."""


class ConnectionError_(LaserqError):
    """No se pudo abrir o mantener el puerto serie."""


class GrblError(LaserqError):
    """GRBL respondió `error:N` a una línea de G-code."""

    def __init__(self, code: int, line: str = "", line_no: int | None = None):
        self.code = code
        self.line = line
        self.line_no = line_no
        msg = ERROR_CODES.get(code, "código desconocido")
        where = f" (línea {line_no})" if line_no is not None else ""
        super().__init__(f"error:{code}{where}: {msg} | enviado: {line.strip()!r}")


class GrblAlarm(LaserqError):
    """GRBL entró en estado ALARM. La máquina queda bloqueada hasta un reset."""

    def __init__(self, code: int):
        self.code = code
        msg = ALARM_CODES.get(code, "código desconocido")
        super().__init__(f"ALARM:{code}: {msg}")


class JobAborted(LaserqError):
    """El job se cortó a pedido del operador (Ctrl-C, botón de pánico)."""


ERROR_CODES: dict[int, str] = {
    1: "Letra de comando G-code no reconocida",
    2: "Falta un valor numérico o está mal formado",
    3: "Comando '$' del sistema no reconocido",
    4: "Se esperaba un valor positivo",
    5: "Homing pedido pero deshabilitado ($22=0)",
    6: "El paso mínimo debe ser mayor a 3 microsegundos",
    7: "EEPROM leída sin datos válidos",
    8: "Comando '$' solo válido con la máquina en Idle",
    9: "G-code bloqueado durante estado de alarma o jog",
    10: "Soft limits requieren homing habilitado ($22=1)",
    11: "Línea excede el largo máximo de caracteres",
    12: "El valor de $ excede la velocidad máxima de paso",
    13: "Puerta de seguridad detectada como abierta",
    14: "Línea de build info o startup excede el largo máximo",
    15: "Jog fuera del rango de la máquina",
    16: "Comando de jog mal formado o con prefijo inválido",
    17: "Laser mode requiere PWM ($32)",
    20: "Comando G-code no soportado o no reconocido",
    21: "Más de un comando del mismo grupo modal en la línea",
    22: "Falta feed rate: hay un movimiento que lo requiere",
    23: "Se esperaba un entero en un comando que solo acepta enteros",
    24: "Dos comandos que requieren el mismo valor en la misma línea",
    25: "Una letra de parámetro repetida",
    26: "Falta la palabra de eje en un comando que la requiere",
    27: "Número de línea (N) fuera del rango válido",
    28: "Falta un valor requerido por el comando",
    29: "Sistema de coordenadas de trabajo no soportado",
    30: "G53 solo es válido con G0 o G1",
    31: "Hay palabras de eje sobrantes para este comando",
    32: "Arco G2/G3 sin palabras de eje en el plano seleccionado",
    33: "Objetivo de movimiento inválido",
    34: "Arco con radio geométricamente inválido",
    35: "Arco en formato offset sin los offsets del plano",
    36: "Palabras de G-code sin usar en el bloque",
    37: "G43.1 sobre un eje que no es el configurado",
    38: "Número de herramienta mayor al máximo soportado",
}

ALARM_CODES: dict[int, str] = {
    1: "Disparo de límite por hardware. Posición perdida: rehacer homing",
    2: "Movimiento G-code fuera del espacio de trabajo (soft limit)",
    3: "Reset mientras la máquina estaba en movimiento. Posición perdida",
    4: "Probe fail: el probe no estaba en el estado inicial esperado",
    5: "Probe fail: no hubo contacto dentro del recorrido programado",
    6: "Homing fail: reset durante el ciclo de homing",
    7: "Homing fail: puerta de seguridad abierta durante el homing",
    8: "Homing fail: el límite no se liberó al retroceder. Revisar cableado",
    9: "Homing fail: no se encontró el límite. Revisar finales de carrera",
    10: "Homing fail: dual axis fuera de tolerancia",
}
