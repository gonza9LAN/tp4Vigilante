# Cheatsheet: UDP y poll en C++

Lo que no llegamos a practicar en el taller. Las explicaciones de este archivo
valen para cualquier lenguaje; `cheatsheet_python.md` y `cheatsheet_js.md`
tienen el mismo código en Python y en JavaScript, con lo que cambia en cada
uno.

## UDP

Un socket UDP no se conecta: cada `sendto` dice adónde va y cada `recvfrom`
dice de dónde vino. Un datagrama llega entero o no llega, nunca partido, y
puede llegar dos veces o en otro orden.

```cpp
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

int fd = socket(AF_INET, SOCK_DGRAM, 0);

// bind a un puerto fijo, para recibir (como el instrumento). Un cliente no
// necesita bind: el sistema le asigna un puerto en el primer sendto.
sockaddr_in me{};
me.sin_family = AF_INET;
me.sin_addr.s_addr = INADDR_ANY;
me.sin_port = htons(6000);
bind(fd, (sockaddr*)&me, sizeof me);

// mandar
sockaddr_in to{};
to.sin_family = AF_INET;
to.sin_port = htons(6000);
inet_pton(AF_INET, "127.0.0.1", &to.sin_addr);
std::string msg = "DEDO izq 2 abajo 17";
sendto(fd, msg.data(), msg.size(), 0, (sockaddr*)&to, sizeof to);

// recibir: from queda con la dirección de quien mandó
char buf[2048];
sockaddr_in from{};
socklen_t fromlen = sizeof from;
ssize_t n = recvfrom(fd, buf, sizeof buf, 0, (sockaddr*)&from, &fromlen);
```

Para tener en cuenta:

- El instrumento contesta a la dirección de la que le llegó el datagrama. Por
  eso cada parte del cuerpo necesita **su propio socket**: si dos partes
  comparten uno, el eco de una le llega a la otra.
- `recv` sin `from` también funciona en UDP, si no importa quién mandó.
- Un `sendto` a un puerto donde no hay nadie no da error: el datagrama se
  pierde. Si el socket UDP está conectado (`connect` también se puede usar en
  UDP, y fija el destino), el `recv` siguiente devuelve `ECONNREFUSED`; se
  puede ignorar y seguir.
- Mantengan los datagramas por debajo de unos 1400 bytes. Los del contrato son
  mucho más chicos.

## poll

`poll` espera hasta que alguno de los descriptores tenga algo para leer o
hasta que vence el timeout. Sirve para sockets TCP, UDP y UNIX, y para
`stdin`.

```cpp
#include <poll.h>

pollfd fds[3] = {
    {tcp_fd, POLLIN, 0},
    {udp_fd, POLLIN, 0},
    {unix_fd, POLLIN, 0},
};
int timeout_ms = 20;                  // -1: sin límite
int ready = poll(fds, 3, timeout_ms); // 0 si venció el timeout, -1 si hubo error
for (auto& p : fds) {
    if (p.revents & POLLIN) { /* hay algo para leer en p.fd */ }
    if (p.revents & (POLLHUP | POLLERR)) { /* el otro lado cerró o hubo error */ }
}
```

Con el timeout se agenda dentro del mismo loop: se calcula cuánto falta para
el próximo evento (mover un dedo, mandar el latido) y se le pasa a `poll`. Si
devuelve 0, llegó la hora. No usen `sleep` en un proceso que además tiene que
escuchar: mientras duerme no atiende nada.

`select` hace lo mismo con otra interfaz, y `epoll` rinde mejor con miles de
descriptores. Para este trabajo alcanza con `poll`. Los tres están en los
ejemplos de la teórica 11.

## Tiempo

```cpp
#include <chrono>
double now_ms() {
    using namespace std::chrono;
    return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}
```

`steady_clock` no salta cuando el sistema ajusta la hora. Un beat dura
`60000.0 / tempo` milisegundos.

## TCP por líneas

Un `recv` en TCP devuelve lo que haya llegado: media línea, una y media, tres.
Hay que acumular en un buffer y sacar las líneas completas:

```cpp
std::string buf;
char tmp[4096];
ssize_t n = recv(fd, tmp, sizeof tmp, 0);
if (n <= 0) { /* cerró o error */ }
buf.append(tmp, n);
size_t pos;
while ((pos = buf.find('\n')) != std::string::npos) {
    std::string line = buf.substr(0, pos);
    buf.erase(0, pos + 1);
    // procesar line
}
```

`send` puede mandar menos de lo pedido: hay que repetirlo hasta que salga todo.

## Sockets UNIX

Como en el taller 4: `AF_UNIX` con `SOCK_STREAM` o `SOCK_DGRAM`, y la
dirección es una ruta en el disco. `unlink` antes del `bind` y al salir. Pongan
el nombre del músico en la ruta, porque el verificador levanta dos músicos a
la vez. En la práctica, los datagramas UNIX no se pierden ni se desordenan;
tengan eso en cuenta al elegir el transporte interno.

Con `SOCK_DGRAM`, el que espera respuestas también tiene que hacer `bind` a una
ruta propia: un socket UNIX de datagramas sin ruta puede mandar, pero no se le
puede contestar.

## Errores comunes

- **SIGPIPE**: escribir en un socket TCP que el otro cerró mata el proceso.
  Pongan `signal(SIGPIPE, SIG_IGN)` al arrancar.
- **Puerto ocupado** al reiniciar un servidor TCP: `setsockopt(fd, SOL_SOCKET,
  SO_REUSEADDR, &one, sizeof one)` antes de `bind`.
- **EINTR**: una señal puede interrumpir `poll` o `recv`; hay que reintentar.
- **Procesos huérfanos**: si el cerebro muere, las manos se enteran porque el
  socket devuelve 0 o `POLLHUP`, y tienen que salir. Después de `FIN` no puede
  quedar nada vivo; el verificador lo revisa.
- **Orden de arranque**: el instrumento o el teatro pueden no estar listos
  cuando arranca su músico. Reintenten la conexión.

## strace: en qué syscall espera un proceso

```bash
strace -f -tt -o traza.txt ./correr.sh flauta1 flauta 127.0.0.1:5100 127.0.0.1:6000
# en otra terminal, con el teatro y el instrumento andando; cuando haya tocado un rato:
awk '{print $1, $3}' traza.txt | sed 's/(.*//' | sort | uniq -c | sort -rn | head
```

`-f` sigue a los hijos y a los threads, y la primera columna es el pid. La
última syscall que empezó cada thread es donde está esperando. Si
multiplexan, van a ver `poll`, `ppoll`, `select`, `pselect6`, `epoll_wait` o
`epoll_pwait`; si bloquean con un thread por socket, `recvfrom` y `accept`; y
`futex` en los threads que esperan a otro thread. En Java y en Node hay muchos
threads en `futex`: busquen el que está en otra syscall.
