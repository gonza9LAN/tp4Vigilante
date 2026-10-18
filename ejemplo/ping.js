// Ejemplo UDP, cliente: manda PING n cada 500 ms y espera el PONG con un timer
// de 200 ms. Si no llega, lo cuenta como perdido. No hay poll: el socket y los
// timers quedan registrados en el event loop.
//   node ping.js [host] [puerto]
const dgram = require('node:dgram');
const { performance } = require('node:perf_hooks');

const host = process.argv[2] || '127.0.0.1';
const port = Number(process.argv[3] || 7000);
const sock = dgram.createSocket('udp4');   // sin bind: el sistema elige el puerto
sock.on('error', (err) => console.log('error:', err.message));   // sin handler, un error mata el proceso

let n = 0, sent = 0, lost = 0;
let waiting = null;   // { n, t0, timer } del PING que espera respuesta

sock.on('message', (msg) => {
    const text = msg.toString();
    if (!waiting || text !== `PONG ${waiting.n}`) {
        console.log(`  (llegó tarde: ${text})`);
        return;
    }
    clearTimeout(waiting.timer);
    console.log(`${text} en ${(performance.now() - waiting.t0).toFixed(1)} ms`);
    waiting = null;
});

function ping() {
    n++;
    sent++;
    const me = { n, t0: performance.now(), timer: null };
    me.timer = setTimeout(() => {
        lost++;
        console.log(`PING ${me.n} sin respuesta (${lost} de ${sent} perdidos)`);
        waiting = null;
    }, 200);
    waiting = me;
    sock.send(`PING ${n}`, port, host);
}

ping();
setInterval(ping, 500);
