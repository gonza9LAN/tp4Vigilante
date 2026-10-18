// Ejemplo UDP, servidor: contesta PONG n a cada PING n. Con --perdida p descarta
// esa fracción de los pings.
//   node pong.js [puerto] [--perdida 0.3]
const dgram = require('node:dgram');

const args = process.argv.slice(2);
const port = args[0] && !args[0].startsWith('-') ? Number(args[0]) : 7000;
const i = args.indexOf('--perdida');
const loss = i >= 0 ? Number(args[i + 1]) : 0;

const sock = dgram.createSocket('udp4');
sock.on('error', (err) => { console.error('pong:', err.message); process.exit(1); });
sock.on('message', (msg, rinfo) => {
    const text = msg.toString();
    if (Math.random() < loss) {
        console.log(`  (perdí: ${text})`);
        return;
    }
    const reply = 'PONG' + text.slice(4);   // "PING 17" -> "PONG 17"
    sock.send(reply, rinfo.port, rinfo.address);
    console.log(`${text} -> ${reply}`);
});
sock.bind(port, () => console.log(`pong escuchando en UDP ${port}, pérdida ${Math.round(loss * 100)}%`));
