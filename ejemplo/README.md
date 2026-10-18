# Ejemplo: ping-pong UDP

El mismo ping-pong en C++, Python y JavaScript. `ping` manda `PING n` cada
medio segundo y espera `PONG n` con un timeout; `pong` contesta, y con
`--perdida p` descarta esa fracción de los pings. Los seis usan el mismo
protocolo, así que se pueden combinar: `ping.py` contra el `pong` de C++, por
ejemplo.

En dos terminales, desde esta carpeta:

```bash
python3 pong.py --perdida 0.3     # o node pong.js, o ./build/pong
python3 ping.py                   # o node ping.js, o ./build/ping
```

Los de C++ se compilan con:

```bash
cmake -S . -B build && cmake --build build
```
