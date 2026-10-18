# Contrato del TP4: el teatro y el instrumento

Este documento es todo lo que un músico necesita saber para hablar con los
programas de la cátedra. Lo que pasa adentro del músico lo deciden ustedes,
dentro de las reglas de la consigna.

## 1. Quién es quién

La cátedra pone dos programas:

- **El teatro**, donde está el director. Reparte la partitura, lleva el reloj,
  da las señas, recibe lo que suena, lo mezcla y lo mide. Hay uno solo, y
  puede estar en otra máquina.
- **El instrumento**, uno por músico. Corre en la máquina del músico. Recibe
  los movimientos de los dedos y la energía, resuelve qué suena y se lo manda
  al teatro.

Ustedes ponen **el músico**: un `cerebro` que habla con el teatro, y las partes
del cuerpo que hablan con el instrumento: `mano izquierda`, `mano derecha` y,
según el instrumento, `pulmones` o `arco`. Cada uno es un proceso aparte.
Cómo se comunican entre ellos es de ustedes, con la única condición de que sea
por sockets.

El músico se levanta con un script en la raíz del repo del grupo:

```
./correr.sh <nombre> <tipo> <teatro> <instrumento>
./correr.sh violin1 violin 127.0.0.1:5100 127.0.0.1:6000
```

`nombre` identifica al músico ante el teatro, `tipo` es el instrumento (ver §6),
`teatro` es `host:puerto` del teatro, `instrumento` es `host:puerto` del
instrumento. El script levanta todos los procesos del músico y no termina hasta
que el teatro manda `FIN`. El instrumento lo levanta la cátedra, no ustedes.

## 2. Convenciones

- Todo es texto. Campos separados por un espacio; decimales con punto.
- En TCP, un mensaje es una línea terminada en `\n`. Pueden llegar varias en
  un `recv`, o una partida en dos.
- En UDP, un datagrama es un mensaje, sin `\n`.
- El tiempo musical se mide en **beats**, fraccionarios. El tempo está en
  beats por minuto. Las notas son números MIDI (69 es el La de 440 Hz).
- El teatro escucha TCP en el puerto 5100 y UDP en el 5101. El instrumento
  escucha UDP en el 6000. Todo configurable, estos son los valores por defecto.

## 3. El teatro por TCP

El cerebro se conecta, se registra, recibe su parte y queda escuchando señas.

| quién manda | mensaje | qué es |
|---|---|---|
| músico | `HOLA <nombre> <tipo>` | registro; un solo `HOLA` por conexión |
| teatro | `PARTE <tipo> <tempo> <n>` | empieza la parte: tempo inicial y cantidad de notas |
| teatro | `NOTA <beat> <dur> <pitch> <din>` | una nota, `n` veces, ordenadas por beat |
| teatro | `FIN_PARTE` | terminó la parte |
| teatro | `ERROR <texto>` | el registro falló; el teatro cierra |
| músico | `LISTO` | todas las partes del cuerpo están conectadas y listas |

`beat` es cuándo empieza la nota, `dur` cuánto dura en beats, `din` la dinámica
escrita de 0 a 100. Los silencios no se escriben: son los huecos entre notas.
En los vientos, una parte tiene una sola voz, nunca dos notas superpuestas. En
las cuerdas puede haber notas superpuestas: un acorde en la guitarra, un doble
cuerda en el violín, o un bajo que sigue sonando mientras entra otra nota.
Toda obra que les demos es digitable con la tabla (§6): nunca van a tener que
elegir entre dos digitaciones.

Después de la parte, el teatro manda **señas**, en cualquier momento:

| seña | qué tiene que pasar |
|---|---|
| `EMPIEZA` | el director va a arrancar. El reloj lo marcan los ticks (§4), no esta seña: hay dos beats de cuenta antes del beat 0 |
| `PARAR` | silencio inmediato; el reloj se detiene |
| `DESDE <beat>` | retomar desde ese beat, con dos beats de cuenta; el reloj salta |
| `TEMPO <bpm>` | cambia el tempo; los ticks ya vienen con el nuevo |
| `DINAMICA <0-100>` | multiplica la dinámica escrita: `100` es como está escrito, `50` la mitad |
| `FIN` | se terminó: cerrar todo y salir |

Se mide cuánto tarda el músico en obedecer una seña. Un beat es demasiado.

## 4. El teatro por UDP: el reloj

El cerebro le manda al puerto UDP del teatro:

```
TIC? <nombre>
```

y a partir de ahí recibe, cada 250 ms, en la misma dirección desde la que mandó:

```
TIC <beat> <tempo> <corriendo>
```

`beat` es el beat actual con tres decimales, `tempo` el vigente, `corriendo`
es `1` si el reloj avanza y `0` si está parado. Entre tick y tick el reloj
avanza solo; un tick perdido no es un problema, el siguiente lo corrige. El
beat puede saltar hacia atrás o hacia adelante (`DESDE`), y el tempo puede
cambiar en cualquier tick.

Hay que repetir `TIC? <nombre>` por lo menos cada 5 segundos. Sin eso el
teatro deja de mandar ticks a esa dirección a los 15 segundos. Esto es lo que
mantiene abierto el camino de vuelta cuando hay un router en el medio.

## 5. El instrumento por UDP

Cada parte del cuerpo le habla al instrumento **desde su propio socket**. El
instrumento se acuerda de la dirección de cada parte y le contesta ahí. Si dos
partes hablan desde la misma dirección, el instrumento lo reporta al teatro.

Al arrancar, todos los dedos están arriba y la energía es 0. Cualquier parte
puede pedir su estado sin mover nada:

```
ECO? <mano>        → ECO <mano> 0 ...
ECO? energia       → ECO energia 0 ...
```

Sirve para saber dónde están los dedos antes de tocar, y para que el
instrumento conozca la dirección de la parte desde el principio.

### 5.1 Los dedos

```
DEDO <mano> <dedo> <lugar> <seq>
```

`mano` es `izq` o `der`; `dedo` va de 1 a la cantidad de dedos de esa mano
según la tabla; `lugar` es adónde va el dedo: `arriba`, o `abajo` en los
vientos, o `<cuerda>:<posicion>` en las cuerdas, o `<tecla>:<fuerza>` en el
piano; `seq` es un entero positivo que identifica la acción.

Un `DEDO` es un movimiento, no un estado. Si el dedo ya estaba en ese lugar,
o ya iba para ahí, es un **movimiento en falso**: el dedo se mueve igual, con
su tránsito, y cuenta como una **torpeza**. Para que se pueda reenviar sin
miedo lo que se perdió, el instrumento **ignora un `seq` que ya procesó** para
esa mano: lo contesta, pero no mueve nada. O sea: una acción nueva lleva un
`seq` nuevo, y un reenvío lleva el mismo `seq`.

El instrumento contesta cada `DEDO`, y además cada 200 ms a cada mano que
conoce, con el estado real de esa mano:

```
ECO <mano> <seq> <dedo>=<lugar>,<dedo>=<lugar>,...
```

Un lugar con `~` adelante (`3=~abajo`) es un dedo en movimiento hacia ahí: todavía
no llegó. En los ecos espontáneos `seq` es `0`.

### 5.2 La energía

```
ENERGIA <valor> <cuerda> <seq>
```

`valor` va de 0 a 100: con 0 el instrumento no suena, con más suena más fuerte.
`cuerda` es `-` en los vientos, y en las cuerdas la que se frota o se pulsa:
una letra, o varias separadas por coma para un acorde (`E,A,D` en la guitarra)
o un doble cuerda (`D,A` en el violín). Con el arco solo se pueden tocar dos
cuerdas vecinas a la vez; con la púa, las que quieran. El instrumento contesta
cada `ENERGIA`, y cada 200 ms, con lo que tiene:

```
ECO energia <seq> <valor> <cuerda>
```

### 5.3 Las reglas físicas

Son tres, y son las únicas:

1. **Un dedo tarda 50 ms en llegar a su lugar.** Mientras algún dedo de una
   mano que digita está en movimiento, la digitación de esa mano no vale.
2. **Si hay energía y la digitación no vale, suena sucio.** No vale cuando hay
   un dedo en movimiento, o cuando el estado de los dedos no coincide con
   ninguna fila de la tabla (vientos), o cuando la cuerda que se frota no está
   en la tabla (cuerdas). El sucio se escucha y se cuenta.
3. **La energía caduca.** Si no llega un `ENERGIA` en 500 ms, cae a 0.

Qué suena: en los vientos, la fila de la tabla cuyos dedos abajo son exactamente
los que están abajo. En las cuerdas, cada cuerda que se frota o se pulsa suena
con la posición más alta de los dedos apoyados sobre ella, o al aire si no hay
ninguno; cada cuerda es una voz, y los dedos sobre cuerdas que no suenan no
molestan. Una cuerda con un dedo en viaje suena sucia; con el arco sobre más
de dos cuerdas, o sobre dos que no son vecinas, suenan sucias todas. En las
dos familias, con energía 0 no suena nada, limpio ni sucio.

### 5.4 Caos

El instrumento se puede levantar con `--perdida p`, `--duplicados p` y
`--desorden p`, con `p` entre 0 y 1. Pierde, duplica o retiene y suelta
después datagramas que entran, y pierde ecos que salen, con esa probabilidad.
Lo usa la cátedra para medir, y ustedes para probar.

## 6. Los instrumentos y sus tablas

Cada instrumento es un archivo en `tablas/`. Un músico tiene que poder tocar
cualquiera de ellos leyendo la tabla: el instrumento con el que tocan se sortea.

| tipo | familia | partes del cuerpo |
|---|---|---|
| `flauta`, `clarinete`, `trompeta` | viento | `izq` y `der` digitan; `pulmones` dan la energía |
| `violin`, `viola`, `cello`, `contrabajo`, `guitarra` | cuerda | `izq` digita; `der` es el arco o la púa y da la energía |
| `piano` | teclado | `izq` y `der` aprietan teclas, cinco dedos cada una; `pie` es el pedal. Es el bonus, ver §8 |

Formato de la tabla. Líneas que empiezan con `#` son comentarios.

```
FAMILIA viento
MANOS izq:3 der:4
# pitch  dedos abajo de izq  dedos abajo de der   ('-' = ninguno)
72 1,2,3 1
74 1,2,3 -
```

```
FAMILIA cuerda
MANOS izq:4
MODO arco          # o pua
CUERDAS G:55 D:62 A:69 E:76
# pitch cuerda dedo posicion   (posicion = semitonos sobre la cuerda al aire; dedo 0 = al aire)
62 D 0 0
64 D 1 2
```

En las cuerdas, el lugar de un dedo en `DEDO` se escribe `D:2`. Si una nota
está en más de una cuerda, como pasa en la guitarra, hay varias filas: la
**primera es la que se usa**. Las tablas son inventadas: alcanza con que sean
consistentes, y lo son.

La tabla de la guitarra tiene además **formas de acorde**: las notas que suenan,
dónde van los dedos (los que no figuran van arriba) y qué cuerdas se pulsan:

```
ACORDE 52,55,60,64 2=D:2,1=B:1 D,G,B,e
```

Con eso, digitar es siempre buscar en la tabla:

- las notas que empiezan en el mismo beat son un conjunto; si el conjunto está
  en una fila `ACORDE`, se usa esa forma; si no, cada nota usa su primera fila;
- lo que suena a la vez, por ejemplo un bajo que sigue y un acorde que entra,
  es la **unión** de sus digitaciones, y la energía lleva la unión de sus
  cuerdas. Si en la unión un dedo queda pedido en dos lugares, va al primer
  dedo libre: el número de dedo de la tabla es una sugerencia;
- las obras están armadas para que esas uniones nunca pidan la misma cuerda
  para dos notas distintas, ni más de cuatro dedos, ni más de dos cuerdas
  vecinas bajo el arco.

```
FAMILIA teclado
MANOS izq:5 der:5
RANGO 36 96     # teclas, en pitch MIDI
ANCHO 12        # lo más lejos que pueden estar dos dedos de la misma mano, en semitonos
```

## 7. Lo que mide el teatro

Para cada músico, al final:

- **a tiempo**: notas de la parte que sonaron con el pitch correcto a menos de
  0,2 beats de su beat;
- **tarde**: con el pitch correcto, entre 0,2 y 1 beat;
- **faltantes**: no sonaron;
- **sucios**: cuántas veces sonó sucio;
- **extrañas**: notas que sonaron y no estaban en la parte;
- **torpezas**: movimientos en falso de los dedos;
- **reacción**: cuánto tardó en callarse después de `PARAR`, y cuánto en
  cambiar la dinámica después de `DINAMICA`;
- **partes**: cuántos sockets distintos vio el instrumento.

## 8. El piano (bonus)

El piano es polifónico por naturaleza: cada dedo es una voz, y no hay tabla
que diga qué mano y qué dedo van a cada tecla: repartirlas es el problema, y
por eso es el bonus. Las reglas que cambian respecto de las otras familias:

- El lugar de un dedo es `<tecla>:<fuerza>`, por ejemplo `60:80`, o `arriba`.
  Un dedo que llega a una tecla la hace sonar con esa fuerza; un dedo que se
  levanta la apaga. Mover un dedo de una tecla a otra es un solo movimiento.
- Las teclas apretadas de una misma mano tienen que entrar en el `ANCHO` de la
  tabla. Si no entran, la mano no da, y todo lo que toca esa mano suena sucio
  hasta que vuelva a entrar.
- La energía es el pedal, y la manda `pie`: con `ENERGIA 0 -` el pedal está
  arriba; con cualquier valor mayor está abajo, y las teclas que se sueltan
  siguen sonando hasta que el pedal suba. El pedal caduca como la energía.
- La parte del piano puede tener notas superpuestas. Repartirlas entre las
  manos y los dedos es el problema.
- El instrumento manda un `SUENA` por voz, con el nombre del dedo al final
  (ver apéndice).

## Apéndice: lo que el instrumento le dice al teatro

No lo implementan ustedes, pero conviene saberlo. Cada vez que cambia lo que
suena, el instrumento le manda al puerto UDP del teatro:

```
SUENA <nombre> <pitch> <valor> <sucio> <partes> <torpezas> <voz>
```

`pitch` es `-1` si no hay nota, `sucio` es `0` o `1`, `partes` es la cantidad
de direcciones distintas desde las que le hablaron, `torpezas` el total de
movimientos en falso hasta ahí, y `voz` es `-` en los vientos, la cuerda (`D`)
en las cuerdas y el dedo (`der2`) en el piano. El teatro le pone a cada
`SUENA` el beat en el que llegó.

Y para que la sala dibuje las manos, cada vez que algo cambia (y no más de
veinte veces por segundo) el instrumento manda también:

```
ESTADO <nombre> <familia> <energia> <cuerda> <torpezas> izq=<dedo>=<lugar>,... der=... <extra>
```

con `~` adelante de un lugar si el dedo está en viaje. Nada de esto afecta a
la nota: es solo para mirar.
