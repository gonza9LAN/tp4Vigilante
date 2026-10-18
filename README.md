# TP4: la orquesta de autómatas

Lean primero `consigna.pdf` y después `contrato.md`.

## Qué hay

- `contrato.md`: los mensajes entre el músico, el teatro y el instrumento.
- `teatro/teatro.py`: el teatro, para correr en su máquina mientras desarrollan.
- `instrumento/instrumento.py`: el instrumento, uno por músico.
- `tablas/`: las tablas de digitación de los ocho instrumentos y la del piano
  (bonus).
- `obras/`: la escala y las obras. Ver `obras/README.md`.
- `probar.py`: el verificador, el mismo que usa la cátedra.
- `cheatsheet.md`, `cheatsheet_python.md`, `cheatsheet_js.md`: UDP y
  multiplexación en C++, Python y JavaScript.
- `ejemplo/`: un ping-pong UDP en los tres lenguajes.
- `correr.sh`: el lanzador de su músico. Es lo único de su código que conoce
  el verificador.

El músico lo escriben ustedes desde cero.

## Teatro e instrumento

En tres terminales, desde esta carpeta:

```bash
python3 teatro/teatro.py                                   # TCP 5100, UDP 5101, sala en http://localhost:5102/
python3 instrumento/instrumento.py --tipo flauta --musico flauta1 --puerto 6000
./correr.sh flauta1 flauta 127.0.0.1:5100 127.0.0.1:6000  # su músico
```

En la consola del teatro, `empezar` arranca la obra. Los otros comandos son
`parar`, `desde N`, `tempo N`, `dinamica N`, `estado`, `informe` y `salir`.
Por defecto toca `obras/fray_santiago.txt`; con `--obra obras/escala.txt` se
prueba nota por nota.

La sala (http://localhost:5102/) muestra la partitura y el instrumento de cada
músico. Para escuchar hay que apretar el botón del parlante. En la partitura,
las notas esperadas están huecas y las que sonaron van en verde (a tiempo),
ocre (tarde), violeta (extraña) o con una cruz roja (sucia). En los
instrumentos, los dedos de la mano izquierda van en azul y los de la derecha
en terracota: llenos si están abajo, huecos si están arriba y punteados
mientras se mueven. Un click en un instrumento lo agranda.

El instrumento acepta `--perdida p`, `--duplicados p` y `--desorden p`.
Conviene probar con caos desde el principio.

## Verificador

```bash
python3 probar.py                        # su correr.sh, flauta y violín, todos los niveles
python3 probar.py --tipos clarinete,cello
python3 probar.py --nivel 0
python3 probar.py --intentos 1           # sin repetir
```

Toca la obra entera en cada nivel, muestra lo que midió el teatro y si pasa
los umbrales (están al principio de `probar.py`), y deja
`informe_verificador.json` y los logs en `verificador_logs/`. El nivel 3 es la
guitarra con acordes, sin caos. Si un nivel no pasa, se repite hasta tres
veces y vale el mejor intento.

El verificador levanta dos músicos a la vez con el mismo `correr.sh`. Si el
script compila al arrancar, las dos compilaciones se pisan: compilen antes o
usen un lock.

## Puertos

El teatro usa 5100 (TCP), 5101 (UDP) y 5102 (la sala); los instrumentos, del
6000 en adelante. El teatro y el instrumento aceptan `--puerto`; el
verificador usa siempre esos.
