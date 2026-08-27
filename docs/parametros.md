# Parámetros de GRBL que importan

`laserq settings` verifica los cuatro críticos y `--apply` los corrige. Este
documento explica por qué son esos y no otros, y cuáles conviene revisar a mano.

Los parámetros viven en la EEPROM del microcontrolador, así que sobreviven al
apagado. La EEPROM tiene un número finito de ciclos de escritura: esto se
configura una vez, no en cada job.

## Los críticos

### `$32=1` — laser mode

El más importante de todos. Con laser mode activo, GRBL sincroniza los cambios
de potencia con el movimiento en lugar de detener el cabezal en cada cambio de
`S`. Sin esto, un raster con miles de cambios de potencia se convierte en una
sucesión de arranques y frenadas, y además `M4` no funciona.

### `$30=1000` / `$31=0` — rango de potencia

Define la escala de `S`. Todo el código de este proyecto genera potencias entre
0 y `$30`. Si `$30` fuera otro valor, cada perfil de material estaría mintiendo:
un `power: 800` significaría 80% en una máquina y 26% en otra.

`$31` en 0 para que `S0` sea realmente apagado.

### `$22=1` — homing

Es la precondición de todo lo automatizable. Con homing, `$H` deja el cabezal en
un origen absoluto repetible: apagás la máquina, la prendés al otro día, hacés
homing, y el (0,0) es el mismo. Sin eso no hay cola de jobs, ni plantillas
reutilizables, ni nada que se pueda repetir sin volver a alinear a mano.

La S30 Pro Max trae los finales de carrera en la caja. Si no están montados, es
lo primero que hay que hacer antes de escribir una línea de código.

## Los que hay que medir

### `$100` / `$101` — pasos por milímetro

`$100` (X) viene bien de fábrica y rara vez se toca. `$101` (Y) es el que cambia
cuando se monta el rotativo, porque ahí Y deja de ser la mesa y pasa a ser el
rodillo.

Procedimiento de calibración del rotativo:

1. Poner un objeto de diámetro conocido y bien medido con calibre.
2. Grabar una línea longitudinal corta.
3. Mover Y exactamente `π × D` milímetros: una vuelta completa según el software.
4. Grabar otra línea.
5. Medir la separación entre las dos.

```python
from laserq.gcode.rotary import calibrate_from_wrap
nuevo = calibrate_from_wrap(actual, diametro_mm=100.0, error_mm=2.0)
```

`error_mm` positivo si la segunda línea quedó pasada, negativo si quedó corta.

**Importante**: guardá el `$101` de la mesa plana antes de tocarlo. Cambiar entre
mesa y rotativo significa cambiar este valor en las dos direcciones.

### `$121` — aceleración de Y

Para la mesa plana, el valor de fábrica está bien. **Para el rotativo hay que
bajarlo bastante**, del orden de 200 mm/s². Un termo lleno o un mate pesado
tienen inercia y patinan sobre los rodillos cuando la aceleración es agresiva.
Un patinazo a mitad de pasada arruina la pieza y la máquina no se entera: sigue
creyendo que está donde debería.

Si ves grabados que se desfasan progresivamente hacia el final de la pasada,
casi siempre es esto y no el `$101`.

### `$110` / `$111` — velocidad máxima

Techo de velocidad por eje. No hace falta tocarlos salvo que quieras limitar la
máquina a propósito: si un perfil pide más `F` del que permite `$110`, GRBL
recorta en silencio y el resultado no coincide con la placa de test.

### `$130` / `$131` — recorrido máximo

Definen el espacio de trabajo para los soft limits. Tienen que coincidir con
`work_area_mm` de `profiles/machine.yaml`, o `laserq check` va a validar contra
un área distinta de la que la máquina cree tener.

Con el kit de extensión de Y, `$131` pasa a 935. Con el kit XY completo, `$130`
también cambia.

### `$27` — retroceso tras el homing

Cuánto se aleja el cabezal del final de carrera al terminar el ciclo. Si es muy
chico, cualquier vibración vuelve a disparar el límite y tira `ALARM:1`.

## Backlash: no es un parámetro de GRBL

GRBL 1.1 no compensa holgura. En este proyecto se compensa del lado del
generador, con `backlash_mm` en `machine.yaml`.

Cómo medirlo: grabá un bloque denso en modo bidireccional y mirá el borde
vertical con lupa. Si las líneas pares e impares quedan desfasadas entre sí (el
clásico "efecto fantasma"), poné en `backlash_mm` la mitad del desfasaje
observado y repetí hasta que desaparezca.

Antes de compensar por software, revisá que las correas estén tensas: casi
siempre es mecánico y compensar una correa floja solo esconde el problema.

## Ver todo

```bash
laserq settings          # solo los críticos, con nombre y valor esperado
```

Para el volcado completo, `$$` desde cualquier terminal serie a 115200.
