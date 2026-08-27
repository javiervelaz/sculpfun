"""Parseo del status report de GRBL 1.1 y modelo de estado de la máquina.

El reporte llega como respuesta al comando realtime `?` y tiene esta forma:

    <Idle|MPos:0.000,0.000,0.000|FS:0,0>
    <Run|MPos:10.500,3.200,0.000|FS:6000,850|Ov:100,100,100>
    <Hold:0|MPos:...|FS:0,0>
    <Alarm|MPos:...|FS:0,0>

Los campos son opcionales y dependen de la máscara `$10`. Nunca asumas
que un campo está: parseá lo que venga.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class MachineState(str, Enum):
    IDLE = "Idle"
    RUN = "Run"
    HOLD = "Hold"
    JOG = "Jog"
    ALARM = "Alarm"
    DOOR = "Door"
    CHECK = "Check"
    HOME = "Home"
    SLEEP = "Sleep"
    UNKNOWN = "Unknown"

    @property
    def is_movable(self) -> bool:
        """True si la máquina puede aceptar movimiento ahora mismo."""
        return self in (MachineState.IDLE, MachineState.RUN, MachineState.JOG)

    @property
    def is_blocked(self) -> bool:
        """True si hace falta intervención antes de seguir."""
        return self in (MachineState.ALARM, MachineState.DOOR, MachineState.SLEEP)


@dataclass(frozen=True)
class Status:
    """Una foto del estado de la máquina."""

    state: MachineState
    substate: int | None = None
    mpos: tuple[float, float, float] | None = None
    wpos: tuple[float, float, float] | None = None
    wco: tuple[float, float, float] | None = None
    feed: float | None = None
    spindle: float | None = None
    planner_blocks: int | None = None
    rx_bytes: int | None = None
    overrides: tuple[int, int, int] | None = None
    raw: str = ""

    @property
    def position(self) -> tuple[float, float, float] | None:
        """Posición de trabajo, derivada de MPos - WCO si hace falta."""
        if self.wpos is not None:
            return self.wpos
        if self.mpos is not None and self.wco is not None:
            return tuple(m - o for m, o in zip(self.mpos, self.wco))  # type: ignore[return-value]
        return self.mpos

    def __str__(self) -> str:
        pos = self.position
        pos_s = "?" if pos is None else ",".join(f"{v:8.3f}" for v in pos)
        sub = f":{self.substate}" if self.substate is not None else ""
        return f"[{self.state.value}{sub}] pos={pos_s} F={self.feed or 0:.0f} S={self.spindle or 0:.0f}"


_STATUS_RE = re.compile(r"^<(?P<body>.*)>$")


def _triple(value: str) -> tuple[float, float, float] | None:
    parts = value.split(",")
    if len(parts) < 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return None


def parse_status(line: str) -> Status | None:
    """Convierte una línea `<...>` en un Status. Devuelve None si no es un reporte."""
    match = _STATUS_RE.match(line.strip())
    if not match:
        return None

    fields = match.group("body").split("|")
    if not fields:
        return None

    # El primer campo es siempre el estado, opcionalmente con subestado.
    head = fields[0]
    substate: int | None = None
    if ":" in head:
        head, _, sub = head.partition(":")
        try:
            substate = int(sub)
        except ValueError:
            substate = None
    try:
        state = MachineState(head)
    except ValueError:
        state = MachineState.UNKNOWN

    kwargs: dict = {"state": state, "substate": substate, "raw": line.strip()}

    for item in fields[1:]:
        key, _, value = item.partition(":")
        if key == "MPos":
            kwargs["mpos"] = _triple(value)
        elif key == "WPos":
            kwargs["wpos"] = _triple(value)
        elif key == "WCO":
            kwargs["wco"] = _triple(value)
        elif key == "FS":
            parts = value.split(",")
            if len(parts) >= 2:
                try:
                    kwargs["feed"] = float(parts[0])
                    kwargs["spindle"] = float(parts[1])
                except ValueError:
                    pass
        elif key == "F":
            try:
                kwargs["feed"] = float(value)
            except ValueError:
                pass
        elif key == "Bf":
            parts = value.split(",")
            if len(parts) >= 2:
                try:
                    kwargs["planner_blocks"] = int(parts[0])
                    kwargs["rx_bytes"] = int(parts[1])
                except ValueError:
                    pass
        elif key == "Ov":
            parts = value.split(",")
            if len(parts) >= 3:
                try:
                    kwargs["overrides"] = (int(parts[0]), int(parts[1]), int(parts[2]))
                except ValueError:
                    pass

    return Status(**kwargs)


@dataclass
class Settings:
    """Los parámetros `$N=valor` leídos de la máquina."""

    values: dict[int, float] = field(default_factory=dict)

    def get(self, number: int, default: float | None = None) -> float | None:
        return self.values.get(number, default)

    def diff(self, expected: dict[int, float]) -> dict[int, tuple[float | None, float]]:
        """Devuelve {n: (actual, esperado)} para cada parámetro que no coincide."""
        out: dict[int, tuple[float | None, float]] = {}
        for number, want in expected.items():
            have = self.values.get(number)
            if have is None or abs(have - want) > 1e-6:
                out[number] = (have, want)
        return out


_SETTING_RE = re.compile(r"^\$(?P<n>\d+)=(?P<v>-?[\d.]+)")


def parse_setting(line: str) -> tuple[int, float] | None:
    """Parsea una línea `$32=1.000` de la respuesta a `$$`."""
    match = _SETTING_RE.match(line.strip())
    if not match:
        return None
    try:
        return int(match.group("n")), float(match.group("v"))
    except ValueError:
        return None
