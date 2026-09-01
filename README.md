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
pytest                      # 119 tests, ninguno necesita hardware
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

## Corte

Cortar no es grabar con otros números. Necesita tres cosas más, y las tres
deciden si la pieza sirve:

* **Multipasada.** Un diodo no atraviesa 6 mm de una. `passes` del perfil se
  aplica contorno por contorno, no repitiendo el programa entero: el material
  ya está caliente y el aire ya está soplando en esa ranura.
* **Kerf.** El láser no corta *sobre* la línea, se come un canal centrado en
  ella. Una ranura dibujada de 6.0 queda de 6.0 + kerf y una pieza dibujada de
  6.0 queda de 6.0 - kerf. Por eso las ranuras se dibujan **más angostas** que
  la medida final y las piezas **más anchas**.
* **Orden.** Los interiores antes que el contorno. Al revés, la pieza se suelta
  cuando termina el perímetro y las ranuras que faltan salen corridas.

### Calibrar antes de cortar nada vendible

```bash
# 1. ¿Con qué velocidad y cuántas pasadas atraviesa?
laserq cut-test -o out/cut-test.gcode -m mdf_3mm_corte
laserq preview out/cut-test.gcode -o out/cut-test.png
laserq run out/cut-test.gcode
```

Los rangos por defecto (1-4 pasadas, 200-800 mm/min) están pensados para
material fino. Para 6 mm o más:
`laserq cut-test --passes 3,4,5,6 --speeds 100,150,250,400`.

Se corta, se da vuelta la plancha y se mira de atrás: las líneas que se ven
atravesaron. La celda más rápida que atraviesa limpio va al perfil.

```bash
# 2. ¿Cuánto se come el láser? (con el perfil ya cargado del paso 1)
laserq kerf-comb -o out/kerf-comb.gcode -m mdf_3mm_corte -t 2.9
```

`-t` es el espesor **medido con calibre**, no el nominal. El MDF de "3 mm"
anda entre 2.7 y 3.2 y cambia de plancha a plancha; si centrás el barrido en
3.00 se te puede ir todo el peine para un lado. Es el mismo número que después
va a definir todas las ranuras del producto, así que vale medirlo bien.

El peine corta ranuras de ancho creciente en pasos de 0.05 mm más una galga de
la misma plancha. Probás la galga en cada ranura; la que entra con presión de
mano y sin juego te da el número:

```
kerf = espesor medido con calibre - ancho nominal de esa ranura
```

Ese valor va a `kerf_mm` en el perfil y de ahí en más el generador compensa
solo. **El peine se corta sin compensar**: es la única pieza del sistema donde
eso es correcto, porque compensar con un kerf que todavía no conocés sería
medir tu propia suposición.

## El primer producto: soporte de notebook

```bash
laserq soporte --nombre "Javi"                  # alto, con teclado externo
laserq soporte --preset bajo --nombre "Javi"    # bajo, para tipear encima
laserq preview out/soporte.gcode -o out/soporte.png
laserq check out/soporte.gcode
laserq run out/soporte.gcode --no-home
```

Dos piezas que se cruzan a 90° con una muesca a media altura. Con dos piezas
planas es la única forma de que se sostengan solas: cualquier disposición en
paralelo necesita un tercer elemento.

* **T (transversal)**: rectángulo, la muesca baja desde el canto de arriba.
  Se ve de frente y lleva el nombre grabado.
* **L (longitudinal)**: canto superior inclinado, la muesca sube desde la base.
  Es la que da el ángulo, y lleva la firma.

Lo que hace que funcione es que el tope de la T queda **al ras** del canto
inclinado de la L justo en el cruce: la notebook apoya sobre dos líneas que se
cortan y queda firme en los dos ejes. Un milímetro de más en la T y se hamaca.

Todo sale de parámetros y nada está escrito en el código:

```bash
laserq soporte --ancho 300 --fondo 220 --altura 100 --angulo 15 \
               --nombre "Martín" --marca "CounterLabs"
laserq soporte --espesor 2.83        # plancha de otro lote, remedida
laserq soporte --sin-pasa-cables --sin-marca
```

`--espesor` está aparte a propósito: el MDF varía entre planchas más de lo que
uno espera, y 0.2 mm de más es un encastre que baila. Si comprás otro lote,
medí y pasalo.

### Detalles que no son detalles

**Primero graba, después corta.** Una pieza recién cortada está suelta sobre el
panal; grabar después es pasar el cabezal sobre algo que se puede mover. El
generador emite todo el grabado antes que el primer corte y lo deja escrito en
el encabezado del G-code.

**Alivio en la raíz de cada muesca.** Un círculo de 3.5 mm en el fondo. Saca el
esquinero interno vivo, que en MDF es por donde arranca la fisura, y le da lugar
al radio que el láser deja en el canto de la otra pieza para que asiente hasta
el fondo.

**El nombre va en un ala, no en el medio.** El centro de la T es exactamente
donde se para la L: grabado ahí, el texto queda partido al medio y tapado. Se
descubre mirando la primera pieza armada, no un preview. `--nombre-lado izq|der`.

**El texto se autoescala.** Si no entra a 20 mm de alto, baja hasta 8 antes de
salirse. Un "Ana" sale grande y un "Guadalupe" un poco más chico, pero los dos
salen centrados y completos.

**Dónde viven los valores de las letras.** En un perfil de material propio,
`mdf_3mm_texto`, separado del de relleno. La velocidad y el grosor se miden
juntos en la misma placa, así que viven juntos:

```yaml
speed: 1000        # columna de la placa de letras
power: 600
grosor_mm: 0.4     # fila de la placa de letras
```

`laserq soporte` lo lee por defecto; `--grabado otro_perfil` y `--grosor N` lo
pisan para una corrida suelta.

**El trazo necesita grosor.** La fuente es de trazo único: sin `--grosor` la
letra sale del ancho del kerf y casi no se lee. `--grosor 0.3` repite el
recorrido en cruz y le da cuerpo. Cuánto hace falta se mide con
`laserq letter-test`, que **no** se puede deducir de la placa de relleno: en
una celda rellena el calor de una línea oscurece a la de al lado, y un trazo
suelto no tiene vecinos que lo ayuden.

**Fieltro en los apoyos.** La notebook va a apoyar sobre cantos de 3 mm. Cuatro
fieltros autoadhesivos cuestan centavos y son la diferencia con una tapa rayada.

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
| `testcard` | Placa de test potencia × velocidad (grabado) |
| `cut-test` | Placa de corte: pasadas × velocidad |
| `kerf-comb -t 5.8` | Peine para medir el kerf de un material |
| `soporte --nombre "Javi"` | Soporte de notebook de dos piezas encastradas |
| `letter-test` | Placa para calibrar el grabado de texto |
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
- `air_assist` y `backlash_mm` de los perfiles no llegan al G-code
  (`passes` ya sí, en el camino de corte)
- Optimización del orden de recorrido dentro de una pieza
- `queue cancel` / `queue requeue` existen en `JobQueue` y no en el CLI
- `check` no conoce el offset de `set-origin`
- Importación de SVG (hoy solo hay tipografía de trazo)
- Optimización del orden de recorrido (el preview ya reporta la métrica)
- Alineación asistida por cámara con OpenCV
- Capa HTTP sobre la cola

## Licencia

MIT.
