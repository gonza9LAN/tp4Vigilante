# Cheatsheet: UDP y el event loop en JavaScript

El mismo contenido que `cheatsheet.md`, en Node. Las explicaciones están allá;
acá está el código y lo que cambia en Node. Todo es de la biblioteca estándar
y anda con el Node de Ubuntu 24.04 (18) o uno más nuevo. TypeScript, al final.

## UDP

```js
const dgram = require('node:dgram');

const sock = dgram.createSocket('udp4');
sock.on('error', (err) => console.error('udp:', err.message));   // ver "Lo que cambia en Node"

// bind a un puerto fijo, para recibir (como el instrumento). Un cliente no
// necesita bind: el sistema le asigna un puerto en el primer send.
sock.bind(6000);

// mandar
sock.send('DEDO izq 2 abajo 17', 6000, '127.0.0.1');

// recibir: rinfo tiene address y port de quien mandó
sock.on('message', (msg, rinfo) => {
    const texto = msg.toString();
    sock.send('...', rinfo.port, rinfo.address);   // contestarle
});
```

Un `send` a un puerto donde no hay nadie no da error: el datagrama se pierde.
Si el socket UDP está conectado con `connect`, llega un evento `'error'` con
`ECONNREFUSED`.

## El event loop

En Node no se llama a `poll`. Cada socket y cada timer registran sus
callbacks, y el event loop espera todo junto (en Linux, con `epoll`). La
multiplexación ya está hecha; lo que hay que cuidar es no bloquear el loop.

```js
teatro.on('data', ...);         // TCP
reloj.on('message', ...);       // UDP
mano.on('message', ...);        // otro socket
setTimeout(moverDedo, ms);      // un timer es un evento más del mismo loop
```

Mientras corre un callback no se atiende nada más. Un
`while (performance.now() < t) {}` para esperar, o una cuenta larga, frena
todos los sockets a la vez. Para esperar, siempre un timer.

`setTimeout` dispara a los `ms` o un poco después, nunca antes, y
`setInterval` va acumulando ese atraso. Para un evento a una hora fija,
calculen cuánto falta cada vez:

```js
function agendar(cuando, fn) {   // cuando: un valor futuro de performance.now()
    return setTimeout(fn, Math.max(0, cuando - performance.now()));
}
```

## Tiempo

`performance.now()` da milisegundos con decimales y no salta si el sistema
ajusta la hora; `Date.now()` sí puede saltar. Un beat dura `60000 / tempo`
milisegundos.

## TCP por líneas

`readline` arma las líneas sobre el socket:

```js
const net = require('node:net');
const readline = require('node:readline');

const teatro = net.createConnection({ host: '127.0.0.1', port: 5100 });
teatro.on('connect', () => teatro.write('HOLA flauta1 flauta\n'));
teatro.on('error', (err) => { /* ECONNREFUSED: el teatro todavía no está, reintentar */ });
teatro.on('close', () => { /* el teatro cerró */ });
readline.createInterface({ input: teatro }).on('line', (linea) => {
    // una línea entera, sin el \n
});
```

`write` no manda a medias: lo que no sale en el momento, Node lo guarda y lo
manda después.

## Sockets UNIX

```js
const fs = require('node:fs');
const net = require('node:net');

const ruta = `/tmp/${nombre}-cerebro.sock`;   // con el nombre: el verificador levanta dos músicos a la vez
try { fs.unlinkSync(ruta); } catch {}
const server = net.createServer((conn) => { /* se conectó una parte */ });
server.listen(ruta);
// del otro lado: net.createConnection(ruta)
```

`dgram` no tiene `AF_UNIX`: en Node, los sockets UNIX son solo stream. Para
datagramas entre sus procesos, la opción es UDP sobre `127.0.0.1`.

## Lo que cambia en Node

- **Un `'error'` sin handler termina el proceso.** Todo socket necesita su
  `.on('error', ...)`. Pasa al conectarse al teatro antes de que esté
  (`ECONNREFUSED`), con un UDP conectado a un puerto donde no hay nadie, y al
  escribir en un TCP que el otro cerró (`EPIPE`, `ECONNRESET`).
- **SIGPIPE**: Node ya lo ignora; en su lugar aparece un `'error'` con `EPIPE`.
- **Buffer y string**: `'message'` y `'data'` entregan un `Buffer`; con
  `.toString()` se obtiene el texto.
- **El proceso no termina solo** mientras quede un socket abierto o un timer
  pendiente. Cuando llega `FIN`, cierren todo o llamen a `process.exit(0)`.
- **child_process**: la entrada y la salida de un hijo son pipes, y el canal de
  `fork` (`process.send`) lo arma Node, no ustedes, así que no cuentan como
  transporte interno. Lancen los procesos desde `correr.sh` o con `spawn` y
  conéctenlos con sus sockets. Si el cerebro lanza las partes, tiene que
  terminarlas al salir (`hijo.kill()`).

## TypeScript

Todo lo anterior vale igual, con tipos. Node 22.18 o más nuevo corre un `.ts`
directamente (`node cerebro.ts`): borra los tipos sin chequearlos y no acepta
sintaxis que no se pueda borrar, como `enum`. Para chequear los tipos, `npx
tsc --noEmit`. El Node de apt en Ubuntu 24.04 es el 18, que no corre `.ts`:
instalen uno más nuevo (por ejemplo con `nvm`) o compilen con `tsc` y corran
el `.js`.

## Ejemplo

`ejemplo/ping.js` y `ejemplo/pong.js`: el ping-pong UDP con el event loop.
Usan el mismo protocolo que los de C++ y Python, así que se pueden combinar.
