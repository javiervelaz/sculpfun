"""laserq — control y automatización para SculpFun S30 Pro Max (GRBL 1.1).

Tres capas, con límites duros entre ellas:

    generadores  ->  cola  ->  driver  ->  máquina

* ``laserq.gcode``       : diseño -> G-code (raster, vectores, rotativo)
* ``laserq.jobs``        : cola persistente y worker
* ``laserq.driver``      : serie, streaming y estado de GRBL
* ``laserq.profiles``    : perfiles de material y máquina
* ``laserq.calibration`` : placas de test

El driver es lo único que toca el puerto serie. Nada de generar G-code y
grabarlo en la misma función: esa separación es la que después te deja
poner un HTTP adelante sin reescribir nada.
"""

__version__ = "0.1.0"

from .profiles import MachineProfile, MaterialProfile, load_machine, load_material

__all__ = ["MachineProfile", "MaterialProfile", "load_machine", "load_material", "__version__"]
