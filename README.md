# laserq

Control y automatización de grabado láser para **SculpFun S30 Pro Max** (GRBL 1.1),
con foco en producción por lotes y en grabado rotativo sobre objetos cónicos.

No es un reemplazo de LightBurn para diseñar. Es la capa que hace falta para que
la máquina reciba trabajo de un proceso automático en vez de un humano con el mouse.

## Por qué existe

Un láser de diodo es un commodity: cualquiera compra el mismo equipo. Lo que no
se compra hecho es el software que convierte datos en piezas sin que nadie abra
un editor gráfico. Este proyecto es esa capa.

## Arquitectura

Tres capas con límites duros entre ellas. Esta separación es lo más importante
del diseño: hoy la cola la dispara un operador, mañana un webhook, y el núcleo
no cambia una línea.

```
  generadores          cola              driver           máquina
  ───────────      ──────────────    ──────────────    ────────────
  raster.py    ->  queue.py      ->  streamer.py   ->  GRBL / USB
  rotary.py        worker.py         machine.py
  font.py          (SQLite)          connection.py
  testcard.py                        state.py
```

`laserq.driver` es lo único que toca el puerto serie. Ninguna función genera
G-code y lo graba al mismo tiempo.

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                      # 67 tests, ninguno necesita hardware
```

En Linux hay que estar en el grupo del puerto serie, o cada comando falla con
un permiso denegado poco descriptivo:

```bash
sudo usermod -aG dialout $USER   # cerrar sesión y volver a entrar
```

## Primeros pasos

```bash
# 1. Verificar los parámetros críticos de GRBL (ver docs/parametros.md)
laserq settings
laserq settings --apply

# 2. Homing. Sin origen absoluto repetible no hay automatización posible.
laserq home

# 3. Generar y revisar una placa de test antes de tocar el material
laserq testcard -o out/mdf.gcode -m "MDF 3mm"
laserq preview out/mdf.gcode -o out/mdf.png
laserq check out/mdf.gcode

# 4. Grabarla
laserq run out/mdf.gcode
```

## El material no siempre está en el (0,0) absoluto

Todo G-code que genera este proyecto asume que empieza en el origen absoluto
de máquina, el mismo que deja el homing. Pero esa esquina puede tener un
final de carrera en el medio, o simplemente no ser donde apoyaste la pieza.
Si el material no está exactamente ahí, el job graba igual en esa esquina —
sobre la mesa, no sobre el material.

Para que el (0,0) del archivo coincida con una esquina del material:

```bash
laserq home                      # origen absoluto, precondición de todo esto
laserq jog --x 120 --y 80        # alineá el cabezal con la esquina del material
laserq set-origin                # esa posición pasa a ser el (0,0) del próximo job
laserq run out/mdf.gcode --no-home   # sin --no-home, un home vuelve a la esquina absoluta y pisa el origen fijado
```

`set-origin --clear` vuelve a coordenadas absolutas de máquina. El offset
dura hasta ahí o hasta un reset — no sobrevive a un `home()` posterior sin
volver a alinearlo. Por eso la cola también acepta `--no-home` (ver Lotes).

Todo el CLI funciona sin máquina conectada usando `--fake`, que simula un GRBL
que responde `ok` a todo. Sirve para probar generadores y la cola.

## El flujo que importa: calibrar primero

La tabla de perfiles de `profiles/materials/` es el activo real del proyecto.
Los valores que vienen son **plantillas sin verificar**: los parámetros que
andan bien dependen de tu lente, tu foco, tu ventilación y tu proveedor de MDF,
y no están en ningún foro.

1. `laserq testcard` genera una grilla de potencia × velocidad con etiquetas grabadas.
2. Cortás una, la mirás, elegís la celda que te gusta.
3. Cargás esos valores en el YAML del material y ponés la fecha en `verified_on`.

`laserq focus-ramp` hace lo propio con el foco: una sola línea sobre una pieza
inclinada, y el punto más fino y oscuro es la distancia focal correcta. Con foco
manual como el de la S30, este truco ahorra mucho tiempo cada vez que cambiás
de espesor.

## Rotativo

```bash
laserq rotary-info -d 90 --diameter-end 70 -l 100
```

```
objeto: 90 -> 70 mm en 100 mm
vuelta completa: 251.33 mm de Y
franja útil de foco: 13.4 mm de arco
CÓNICO: semiángulo -5.71°, hace falta corrección de arco
un punto a 20 mm del centro se desplaza 5.08 mm de Y entre la base y el tope
```

Ese último número es el punto de todo el módulo. Un mate no es un cilindro: su
superficie lateral no se despliega en un rectángulo sino en un sector de corona
circular. Envolver un diseño recto deja las letras de distinto ancho según la
altura y la línea de base curvada. En un mate típico son más de 5 mm de error,
perfectamente visibles en la pieza.

La corrección está en `ConeMapping.warp_polyline`: en vez de repartir ángulo
uniforme, conserva la longitud de arco física en cada altura.

Con rotativo de rodillos, **`$101` se calibra una sola vez** y no depende del
diámetro del objeto, porque la superficie del objeto recorre la misma distancia
lineal que la del rodillo. Lo que cambia por objeto es cuánto Y hace falta para
una vuelta: π × D.

## Lotes

```bash
python examples/lote_desde_csv.py nombres.csv \
    --diametro 90 --diametro-tope 70 --largo 90 --encolar
laserq queue list
laserq queue work --no-home        # rotativo montado: ver abajo
```

De un CSV a N piezas únicas sin abrir un editor. Este es el primer producto
vendible del sistema.

### Homing en una tirada

Por defecto la cola homea **una sola vez**, antes del primer job, y vuelve a
homear después de cualquier falla (un `emergency_stop()` hace soft reset, así
que la posición deja de ser confiable). Cincuenta termos no necesitan cincuenta
ciclos de homing.

| Modo | Cuándo |
|---|---|
| `--home once` (por defecto) | Mesa plana, tirada normal |
| `--home each` | Si entre pieza y pieza alguien mueve el cabezal a mano |
| `--no-home` (`--home never`) | **Rotativo montado**, o después de `set-origin` |

`--no-home` no es una optimización: con el rotativo, Y deja de ser la mesa y
pasa a ser el rodillo, así que un `$H` sale a buscar un final de carrera que en
ese eje no existe y el objeto gira hasta que alguien corta.

## Comandos

| Comando | Qué hace |
|---|---|
| `status` | Estado actual de la máquina |
| `settings [--apply]` | Verifica y corrige los parámetros `$N` críticos |
| `home` | Ciclo de homing |
| `jog --x --y [--rel]` | Mueve el cabezal sin grabar, para alinearlo con el material |
| `set-origin [--clear]` | Fija la posición actual como (0,0) del próximo job |
| `testcard` | Placa de test potencia × velocidad |
| `focus-ramp` | Línea para encontrar el foco |
| `raster IMG -w 80` | Imagen a G-code con dithering |
| `rotary-info -d 90` | Números del rotativo para un objeto |
| `preview F.gcode` | Dibuja el recorrido a PNG |
| `check F.gcode` | Bounding box y validación sin grabar |
| `run F.gcode` | Graba un archivo |
| `queue add\|list\|work` | Cola de jobs |
| `queue work --no-home` | Igual, sin homear (rotativo, `set-origin`) |
| `materials` | Lista los perfiles y cuáles están sin verificar |

## Seguridad

El módulo láser de la S30 Pro Max es **clase 4**. No es una formalidad legal:

- Antiparras con densidad óptica específica para **445-450 nm**. Las genéricas
  de "protección láser" pueden no cubrir esa banda.
- Extracción al exterior si se trabaja cuero, plásticos o MDF. El humo de MDF
  lleva resinas de urea-formaldehído.
- **Nunca cuero curtido al cromo**: al quemarse libera compuestos de cromo
  hexavalente.
- Nunca PVC, vinilo ni nada con cloro: genera cloruro de hidrógeno, que además
  de tóxico corroe la máquina.
- Extintor al alcance de la mano. Un corte de MDF que se prende no avisa.
- Un interruptor físico en serie con la fuente, al alcance. `emergency_stop()`
  es software y depende de que el proceso siga vivo.

`laserq queue work --no-confirm` ejecuta la cola sin pedir confirmación por
pieza. **No usarlo sin gabinete cerrado, extracción y enclavamiento de puerta.**

Del lado del software, cualquier falla durante el streaming (un `error:N`, una
alarma, una excepción cualquiera) hace feed hold y después soft reset antes de
propagar el error. Hace falta porque un `error:N` no detiene nada por sí solo:
GRBL sigue ejecutando los ~128 bytes que ya tenía en el buffer, con el láser
encendido. Sigue sin reemplazar al interruptor físico.

## Estado

Esqueleto funcional con la parte crítica cubierta por tests. Falta:

- Raster sobre cónico (`laserq rotary`): el mapeo inverso `ConeMapping.design_u()`
  está escrito y todavía no lo usa nadie. Vectores sobre cónico sí funcionan.
- `passes`, `air_assist` y `backlash_mm` de los perfiles no llegan al G-code
- `queue cancel` / `queue requeue` existen en `JobQueue` y no en el CLI
- `check` no conoce el offset de `set-origin`
- Importación de SVG (hoy solo hay tipografía de trazo)
- Optimización del orden de recorrido (el preview ya reporta la métrica)
- Alineación asistida por cámara con OpenCV
- Capa HTTP sobre la cola

## Licencia

MIT.
