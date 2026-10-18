# Cheatsheet: UDP y selectors en Python

El mismo contenido que `cheatsheet.md`, en Python. Las explicaciones están
allá; acá está el código y lo que cambia en Python. Todo es de la biblioteca
estándar y anda con el Python de Ubuntu 24.04 (3.12) o cualquiera desde 3.8.

## UDP

```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# bind a un puerto fijo, para recibir (como el instrumento). Un cliente no
# necesita bind: el sistema le asigna un puerto en el primer sendto.
sock.bind(("0.0.0.0", 6000))

# mandar: los sockets mandan bytes, no str
sock.sendto("DEDO izq 2 abajo 17".encode(), ("127.0.0.1", 6000))

# recibir: sender es la tupla (ip, puerto) de quien mandó
data, sender = sock.recvfrom(2048)
texto = data.decode()
sock.sendto(b"...", sender)   # contestarle
```

Un `sendto` a un puerto donde no hay nadie no da error: el datagrama se
pierde. Si el socket UDP está conectado con `connect`, el `recv` siguiente
tira `ConnectionRefusedError`.

## selectors

`selectors` es `poll` con otra interfaz, y usa lo mejor que tenga el sistema
(en Linux, `epoll`). Al registrar un socket se le puede asociar un dato, por
ejemplo la función que lo atiende:

```python
import selectors

sel = selectors.DefaultSelector()
sel.register(tcp_sock, selectors.EVENT_READ, data=atender_teatro)
sel.register(udp_sock, selectors.EVENT_READ, data=atender_reloj)
sel.register(unix_sock, selectors.EVENT_READ, data=atender_mano)

while True:
    timeout = 0.020                    # en segundos; None: sin límite
    eventos = sel.select(timeout)      # lista vacía si venció el timeout
    for key, mask in eventos:
        key.data(key.fileobj)          # llama a la función registrada con ese socket
    # lo que haya que hacer a esta hora
```

Como en C++, el timeout sirve para agendar: se calcula cuánto falta para el
próximo evento y se le pasa a `select`. No usen `time.sleep` en un proceso que
además tiene que escuchar.

Otras formas de esperar, cada una con su modelo: `select.poll()` es el `poll`
de C (con el timeout en milisegundos), `asyncio` es un loop de selectors con
corrutinas, y `threading`, con un thread bloqueado en cada socket, es el
modelo de threads. Con `strace` se ve la diferencia.

## Tiempo

```python
import time

ahora = time.monotonic()   # segundos, con decimales; no salta si el sistema ajusta la hora
```

`time.time()` sí puede saltar: no lo usen para medir intervalos. Un beat dura
`60 / tempo` segundos.

## TCP por líneas

Un `recv` en TCP devuelve lo que haya llegado. Hay que acumular en un buffer,
uno por conexión, y sacar las líneas completas:

```python
chunk = sock.recv(4096)
if not chunk:
    ...                    # el otro cerró
buf += chunk
while b"\n" in buf:
    linea, buf = buf.split(b"\n", 1)
    procesar(linea.decode())
```

Para mandar, `sock.sendall(...)`, que repite el `send` hasta que sale todo.

Cuidado con `sock.makefile()`: `readline` es cómodo, pero el archivo guarda en
su buffer lo que ya leyó del socket y `select` no lo ve, así que el loop se
queda esperando una línea que ya llegó. Con selectors, usen el buffer a mano.

## Sockets UNIX

```python
import os
import socket

ruta = f"/tmp/{nombre}-cerebro.sock"   # con el nombre: el verificador levanta dos músicos a la vez
if os.path.exists(ruta):
    os.unlink(ruta)
sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)   # o SOCK_STREAM
sock.bind(ruta)
```

Con `SOCK_DGRAM`, el que espera respuestas también tiene que hacer `bind` a una
ruta propia: un socket UNIX de datagramas sin ruta puede mandar, pero no se le
puede contestar.

## Lo que cambia en Python

- **Excepciones**: lo que en C++ es un -1 con `errno`, en Python es una
  excepción que, si nadie la atrapa, termina el proceso.
  `ConnectionRefusedError` aparece al conectarse al teatro antes de que esté, o
  en un UDP con `connect`; `BrokenPipeError` y `ConnectionResetError`, con un
  TCP que el otro cerró; `BlockingIOError`, en un socket no bloqueante sin
  nada para leer. Atrapen cada una donde la esperan; un `except Exception:
  pass` alrededor de todo esconde los errores.
- **SIGPIPE**: Python ya lo ignora; en su lugar aparece `BrokenPipeError`.
- **bytes y str**: los sockets mandan y reciben `bytes`. `.encode()` al mandar
  y `.decode()` al recibir.
- **Salida con buffer**: cuando `print` escribe a un archivo, como en los logs
  del verificador, Python junta la salida y la escribe tarde, o nunca si el
  proceso muere. Usen `python3 -u` o `print(..., flush=True)`.
- **Puerto ocupado** al reiniciar un servidor TCP:
  `sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)` antes de `bind`.
- **multiprocessing**: `Pipe` y `Queue` usan pipes o sockets que arma la
  biblioteca, no ustedes, así que no cuentan como transporte interno. Lancen
  los procesos desde `correr.sh` o con `subprocess` y conéctenlos con sus
  sockets.
- **Procesos huérfanos**: si el cerebro lanza las partes con `subprocess.Popen`,
  tiene que terminarlas al salir (`p.terminate()` y `p.wait()`), también
  cuando sale por una excepción.

## Ejemplo

`ejemplo/ping.py` y `ejemplo/pong.py`: el ping-pong UDP con `selectors`. Usan
el mismo protocolo que los de C++ y JavaScript, así que se pueden combinar.
