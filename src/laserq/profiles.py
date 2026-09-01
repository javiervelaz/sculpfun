"""Perfiles de material y configuración de máquina.

El perfil es el activo real del negocio. Que viva en YAML versionado y no
hardcodeado en el código es deliberado: cada valor de acá se ganó quemando
una placa de test, y querés poder ver en el historial de git cuándo
cambiaste el foco o el proveedor de MDF y qué pasó con los resultados.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PROFILE_DIR = Path("profiles")


@dataclass
class MaterialProfile:
    """Parámetros probados para una combinación de material y operación."""

    name: str
    material: str = ""
    thickness_mm: float | None = None
    operation: str = "engrave"  # engrave | cut | mark
    speed: int = 3000  # mm/min
    power: int = 700  # 0..$30
    passes: int = 1
    line_interval_mm: float = 0.1
    dpi: int | None = None
    dither: str = "jarvis"
    gamma: float = 1.0
    air_assist: bool = True
    #: Ancho del canal que se come el láser al cortar, en mm. Se mide una vez
    #: por material y espesor con `laserq kerf-comb`, y de ahí en más el
    #: generador compensa solo: las ranuras salen más angostas que la medida
    #: final y las piezas más anchas. Es lo que decide si un encastre encastra.
    kerf_mm: float = 0.0
    focus_offset_mm: float = 0.0
    #: Milímetros a levantar el material desde la mesa (panal, calzas).
    z_offset_mm: float = 0.0
    notes: str = ""
    verified_on: str = ""  # fecha de la última placa de test que lo validó

    @property
    def effective_dpi(self) -> int:
        if self.dpi:
            return self.dpi
        return max(1, round(25.4 / self.line_interval_mm))

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}


@dataclass
class MachineProfile:
    """Datos de la máquina y sus límites físicos."""

    name: str = "SculpFun S30 Pro Max"
    port: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    max_power: int = 1000  # $30
    work_area_mm: tuple[float, float] = (410.0, 400.0)
    travel_feed: int = 6000
    #: Compensación de holgura para barrido bidireccional. Se mide una vez
    #: grabando líneas alternadas y viendo el desfasaje entre pares e impares.
    backlash_mm: float = 0.0
    has_rotary: bool = False
    rotary_roller_diameter_mm: float = 15.0
    rotary_steps_per_mm: float | None = None

    def fits(self, width_mm: float, height_mm: float) -> bool:
        return width_mm <= self.work_area_mm[0] and height_mm <= self.work_area_mm[1]


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("hace falta PyYAML: pip install pyyaml") from exc
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_material(name: str, directory: Path | str = DEFAULT_PROFILE_DIR) -> MaterialProfile:
    """Carga un perfil por nombre desde `<directory>/materials/<name>.yaml`."""
    base = Path(directory) / "materials"
    path = base / f"{name}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in base.glob("*.yaml")) if base.exists() else []
        raise FileNotFoundError(
            f"no existe el perfil {name!r} en {base}. "
            f"Disponibles: {', '.join(available) or 'ninguno'}"
        )
    data = _load_yaml(path)
    data.setdefault("name", name)
    known = {f for f in MaterialProfile.__dataclass_fields__}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"{path}: campos desconocidos: {', '.join(sorted(unknown))}")
    return MaterialProfile(**data)


def list_materials(directory: Path | str = DEFAULT_PROFILE_DIR) -> list[str]:
    base = Path(directory) / "materials"
    if not base.exists():
        return []
    return sorted(p.stem for p in base.glob("*.yaml"))


def load_machine(directory: Path | str = DEFAULT_PROFILE_DIR) -> MachineProfile:
    path = Path(directory) / "machine.yaml"
    if not path.exists():
        return MachineProfile()
    data = _load_yaml(path)
    if "work_area_mm" in data and isinstance(data["work_area_mm"], list):
        data["work_area_mm"] = tuple(data["work_area_mm"])
    known = {f for f in MachineProfile.__dataclass_fields__}
    return MachineProfile(**{k: v for k, v in data.items() if k in known})


def save_material(profile: MaterialProfile, directory: Path | str = DEFAULT_PROFILE_DIR) -> Path:
    """Guarda un perfil. Se usa después de leer una placa de test."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("hace falta PyYAML: pip install pyyaml") from exc

    base = Path(directory) / "materials"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{profile.name}.yaml"
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(profile.to_dict(), handle, allow_unicode=True, sort_keys=False)
    return path
