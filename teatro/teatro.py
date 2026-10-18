#!/usr/bin/env python3
"""Teatro del TP4: el director y la sala.

Un solo proceso que atiende:
  - TCP 5100: los cerebros se registran (HOLA), reciben su parte y las señas.
  - UDP 5101: los cerebros piden ticks (TIC?); los instrumentos mandan SUENA y ESTADO.
  - HTTP 5102: la sala (sala.html), que recibe los eventos por SSE.

Consola: empezar [beat], parar, desde N, tempo N, dinamica N, estado, informe, salir.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import selectors
import socket
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
TICK_PERIOD = 0.25   # segundos entre ticks UDP
COUNT_IN = -2.0      # dos beats de cuenta antes del 0

Nota = tuple[float, float, int, int]        # beat, duración, pitch, dinámica
Sonido = tuple[float, int, int, int, str]   # beat, pitch, fuerza, sucio, voz


@dataclass
class Obra:
    nombre: str = "?"
    tempo: float = 120.0
    partes: dict[str, list[Nota]] = field(default_factory=lambda: {})


def load_obra(path: str) -> Obra:
    obra = Obra()
    parte: list[Nota] | None = None
    for raw in open(path):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        f = line.split()
        if f[0] == "OBRA":
            obra.nombre = f[1]
        elif f[0] == "TEMPO":
            obra.tempo = float(f[1])
        elif f[0] == "PARTE":
            parte = []
            for tipo in f[1:]:
                obra.partes[tipo] = parte
        elif f[0] == "NOTA":
            if parte is None:
                raise ValueError("%s: NOTA antes de PARTE" % path)
            parte.append((float(f[1]), float(f[2]), int(f[3]), int(f[4])))
    return obra


@dataclass
class Opciones:
    puerto: int
    esperar: int
    salir_al_final: bool
    sin_consola: bool
    ver: bool
    guion: str
    informe_json: str
    tolerancia: float


@dataclass
class Musico:
    instrumento: str
    conn: socket.socket | None
    part: list[Nota]
    tick_addr: Any = None   # de dónde pide ticks
    heard: list[Sonido] = field(default_factory=lambda: [])
    listo: bool = False
    tic_time: float = 0.0
    partes: int = 0
    torpezas: int = 0
    sounding: bool = False
    voces: dict[str, int] = field(default_factory=lambda: {})
    pending: tuple[str, float] | None = None   # seña que espera reacción, y cuándo se mandó
    react: dict[str, list[float]] = field(default_factory=lambda: {"PARAR": [], "DINAMICA": []})


@dataclass
class Medicion:
    instrumento: str
    esperadas: int
    a_tiempo: int
    tarde: int
    faltantes: int
    sucios: int
    extranas: int
    torpezas: int
    partes: int
    reaccion_parar_ms: float | None
    reaccion_dinamica_ms: float | None


class Clock:
    """Reloj en beats, extrapolado desde el último cambio."""

    def __init__(self, tempo: float) -> None:
        self.tempo = tempo
        self.running = False
        self.base_beat = 0.0
        self.base_time = time.monotonic()

    def beat(self) -> float:
        if not self.running:
            return self.base_beat
        return self.base_beat + (time.monotonic() - self.base_time) * self.tempo / 60.0

    def start(self, beat: float) -> None:
        self.base_beat = beat
        self.base_time = time.monotonic()
        self.running = True

    def stop(self) -> None:
        self.base_beat = self.beat()
        self.running = False

    def set_tempo(self, tempo: float) -> None:
        self.base_beat = self.beat()
        self.base_time = time.monotonic()
        self.tempo = tempo


sse_clients: list[queue.Queue[str]] = []
sse_replay: list[str] = []   # musico, parte y obra: se repiten a las salas que se conectan tarde
sse_lock = threading.Lock()


def broadcast(kind: str, payload: str) -> None:
    msg = "event: %s\ndata: %s\n\n" % (kind, payload)
    with sse_lock:
        if kind in ("musico", "parte", "obra"):
            sse_replay.append(msg)
        for q in sse_clients:
            q.put(msg)


class SalaHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/eventos":
            q: queue.Queue[str] = queue.Queue()
            for msg in list(sse_replay):
                q.put(msg)
            with sse_lock:
                sse_clients.append(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    try:
                        msg = q.get(timeout=15)
                    except queue.Empty:
                        msg = ": latido\n\n"
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with sse_lock:
                    sse_clients.remove(q)
        else:
            body = open(os.path.join(HERE, "sala.html"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


class Teatro:
    def __init__(self, obra: Obra, args: Opciones) -> None:
        self.obra = obra
        self.args = args
        self.clock = Clock(obra.tempo)
        self.musicians: dict[str, Musico] = {}
        self.conn_owner: dict[socket.socket, str | None] = {}
        self.buffers: dict[socket.socket, bytes] = {}
        self.console_buf = b""
        self.sel = selectors.DefaultSelector()
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind(("0.0.0.0", args.puerto))
        self.tcp.listen(16)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("0.0.0.0", args.puerto + 1))
        self.sel.register(self.tcp, selectors.EVENT_READ, self.on_accept)
        self.sel.register(self.udp, selectors.EVENT_READ, self.on_udp)
        if not args.sin_consola:
            self.sel.register(sys.stdin, selectors.EVENT_READ, self.on_console)
        self.last_tick = 0.0
        self.started_once = False
        self.listos = 0
        self.end_beat = max((b + d for p in obra.partes.values() for (b, d, _, _) in p), default=0)
        self.quit = False
        self.stopped_at = 0.0
        self.guion: list[tuple[float, str]] = []
        for item in (args.guion.split(",") if args.guion else []):
            beat, cmd = item.split(":", 1)
            self.guion.append((float(beat), cmd.strip()))

    def on_accept(self, sock: socket.socket) -> None:
        conn, _ = sock.accept()
        self.sel.register(conn, selectors.EVENT_READ, self.on_tcp)
        self.conn_owner[conn] = None
        self.buffers[conn] = b""

    def on_tcp(self, conn: socket.socket) -> None:
        try:
            data = conn.recv(4096)
        except ConnectionResetError:
            data = b""
        if not data:
            name = self.conn_owner.pop(conn, None)
            self.sel.unregister(conn)
            conn.close()
            if name:
                print("[teatro] se fue %s" % name)
                self.musicians[name].conn = None
            return
        self.buffers[conn] += data
        while b"\n" in self.buffers[conn]:
            line, self.buffers[conn] = self.buffers[conn].split(b"\n", 1)
            self.handle_line(conn, line.decode().strip())

    def handle_line(self, conn: socket.socket, line: str) -> None:
        f = line.split()
        if not f:
            return
        if f[0] == "HOLA" and len(f) >= 3:
            name, instr = f[1], f[2]
            part = self.obra.partes.get(instr)
            if part is None:
                conn.sendall(("ERROR no hay parte para %s\n" % instr).encode())
                return
            self.conn_owner[conn] = name
            self.musicians[name] = Musico(instr, conn, part)
            out = ["PARTE %s %g %d" % (instr, self.obra.tempo, len(part))]
            out += ["NOTA %g %g %d %d" % n for n in part]
            out.append("FIN_PARTE")
            conn.sendall(("\n".join(out) + "\n").encode())
            print("[teatro] se registró %s (%s), %d notas" % (name, instr, len(part)))
            broadcast("musico", "%s %s" % (name, instr))
            broadcast("parte", json.dumps({"nombre": name, "tipo": instr, "tempo": self.obra.tempo, "notas": part}))
        elif f[0] == "LISTO":
            name = self.conn_owner.get(conn)
            if name and not self.musicians[name].listo:
                self.musicians[name].listo = True
                self.listos += 1
                print("[teatro] %s está listo (%d/%s)" % (name, self.listos, self.args.esperar or "-"))
        else:
            print("[teatro] línea rara de %s: %s" % (self.conn_owner.get(conn), line))

    def send_all(self, line: str) -> None:
        broadcast("sena", line)
        for m in self.musicians.values():
            if m.conn:
                try:
                    m.conn.sendall((line + "\n").encode())
                except OSError:
                    pass

    def on_udp(self, sock: socket.socket) -> None:
        data, addr = sock.recvfrom(2048)
        f = data.decode(errors="replace").split()
        if not f:
            return
        if f[0] == "TIC?":
            name = f[1] if len(f) > 1 else "?"
            if name in self.musicians:
                self.musicians[name].tick_addr = addr
                self.musicians[name].tic_time = time.monotonic()
            self.udp.sendto(self.tick_msg().encode(), addr)
        elif f[0] == "ESTADO" and len(f) >= 6:
            broadcast("estado", " ".join(f[1:]))
        elif f[0] == "SUENA" and len(f) >= 5:
            name, pitch, vel, sucio = f[1], int(f[2]), int(f[3]), int(f[4])
            partes = int(f[5]) if len(f) > 5 else 0
            torpezas = int(f[6]) if len(f) > 6 else 0
            voz = f[7] if len(f) > 7 else "-"
            m = self.musicians.get(name)
            beat = self.clock.beat()
            if m is not None:
                m.heard.append((beat, pitch, vel, sucio, voz))
                m.partes = max(m.partes, partes)
                m.torpezas = max(m.torpezas, torpezas)
                last_vel = m.voces.get(voz, 0)
                m.voces[voz] = vel
                if m.pending:
                    kind, t0 = m.pending
                    if (kind == "PARAR" and not any(m.voces.values())) or (kind == "DINAMICA" and vel != last_vel):
                        m.react[kind].append((time.monotonic() - t0) * 1000)
                        m.pending = None
                m.sounding = any(m.voces.values())
            if self.args.ver:
                print("[%7.2f] %-10s %s" % (beat, name, describe(pitch, vel, sucio)))
            broadcast("suena", "%s %d %d %d %.2f %s" % (name, pitch, vel, sucio, beat, voz))

    def tick_msg(self) -> str:
        return "TIC %.3f %g %d" % (self.clock.beat(), self.clock.tempo, 1 if self.clock.running else 0)

    def send_ticks(self) -> None:
        msg = self.tick_msg().encode()
        now = time.monotonic()
        for m in self.musicians.values():
            if m.tick_addr and now - m.tic_time < 15:
                self.udp.sendto(msg, m.tick_addr)
        broadcast("tic", self.tick_msg())

    def on_console(self, _: Any) -> None:
        # os.read y no readline: lo que readline deja en su buffer, el selector no lo ve
        data = os.read(sys.stdin.fileno(), 4096)
        if not data:
            self.sel.unregister(sys.stdin)
            return
        self.console_buf += data
        while b"\n" in self.console_buf:
            line, self.console_buf = self.console_buf.split(b"\n", 1)
            self.command(line.decode().strip())

    def command(self, line: str) -> None:
        f = line.split()
        if not f:
            return
        cmd = f[0]
        if cmd == "empezar":
            beat = float(f[1]) if len(f) > 1 else COUNT_IN
            self.clock.start(beat)
            self.started_once = True
            self.send_all("EMPIEZA")
            self.send_ticks()
            if beat == COUNT_IN:
                print("[teatro] empezamos: dos beats de cuenta y arranca el beat 0, a %g" % self.clock.tempo)
            else:
                print("[teatro] empezamos en el beat %g, a %g" % (beat, self.clock.tempo))
        elif cmd == "parar":
            self.clock.stop()
            self.stopped_at = time.monotonic()
            self.expect_reaction("PARAR")
            self.send_all("PARAR")
            self.send_ticks()
            print("[teatro] parado en el beat %.2f" % self.clock.beat())
        elif cmd == "desde" and len(f) > 1:
            beat = float(f[1])
            for m in self.musicians.values():   # lo que se repite no se cuenta dos veces
                m.heard = [h for h in m.heard if h[0] < beat]
            self.clock.start(beat + COUNT_IN)
            self.started_once = True
            self.send_all("DESDE %g" % beat)
            self.send_ticks()
            print("[teatro] desde el beat %g, con dos de cuenta" % beat)
        elif cmd == "tempo" and len(f) > 1:
            self.clock.set_tempo(float(f[1]))
            self.send_all("TEMPO %g" % self.clock.tempo)
            self.send_ticks()
            print("[teatro] tempo %g" % self.clock.tempo)
        elif cmd == "dinamica" and len(f) > 1:
            self.expect_reaction("DINAMICA")
            self.send_all("DINAMICA %s" % f[1])
            print("[teatro] dinámica %s" % f[1])
        elif cmd == "estado":
            print("[teatro] beat %.2f tempo %g corriendo %s" % (self.clock.beat(), self.clock.tempo, self.clock.running))
            for name, m in self.musicians.items():
                print("   %-10s %-8s ticks:%s listo:%s eventos:%d" % (
                    name, m.instrumento, "sí" if m.tick_addr else "no", m.listo, len(m.heard)))
        elif cmd == "informe":
            self.informe()
        elif cmd in ("salir", "fin"):
            self.send_all("FIN")
            self.quit = True
        else:
            print("[teatro] comandos: empezar [beat], parar, desde N, tempo N, dinamica N, estado, informe, salir")

    def expect_reaction(self, kind: str) -> None:
        for m in self.musicians.values():
            if m.sounding:
                m.pending = (kind, time.monotonic())

    def metricas(self) -> dict[str, Medicion]:
        tol = self.args.tolerancia
        out: dict[str, Medicion] = {}
        for name, m in self.musicians.items():
            ons, sucios = note_ons(m.heard)
            used = [False] * len(ons)
            on_time = late = missing = 0
            for (beat, _, pitch, _) in m.part:
                best: tuple[float, int] | None = None
                for i, (hb, hp) in enumerate(ons):
                    if used[i] or hp != pitch:
                        continue
                    delta = abs(hb - beat)
                    if delta <= 1.0 and (best is None or delta < best[0]):
                        best = (delta, i)
                if best is None:
                    missing += 1
                else:
                    used[best[1]] = True
                    if best[0] <= tol:
                        on_time += 1
                    else:
                        late += 1
            out[name] = Medicion(
                m.instrumento, len(m.part), on_time, late, missing, sucios, used.count(False), m.torpezas, m.partes,
                max(m.react["PARAR"]) if m.react["PARAR"] else None,
                max(m.react["DINAMICA"]) if m.react["DINAMICA"] else None)
        return out

    def informe(self) -> None:
        met = self.metricas()
        print("\n=== informe de %s (tolerancia %.2f beats) ===" % (self.obra.nombre, self.args.tolerancia))
        print("%-10s %-10s %9s %9s %6s %9s %7s %8s %8s %11s %11s %6s" % (
            "músico", "instr", "esperadas", "a tiempo", "tarde", "faltantes", "sucios", "extrañas", "torpezas", "parar(ms)", "dinam.(ms)", "partes"))

        def fmt(v: float | None) -> str:
            return "%.1f" % v if v is not None else "-"

        for name, r in met.items():
            print("%-10s %-10s %9d %9d %6d %9d %7d %8d %8d %11s %11s %6d" % (
                name, r.instrumento, r.esperadas, r.a_tiempo, r.tarde, r.faltantes, r.sucios,
                r.extranas, r.torpezas, fmt(r.reaccion_parar_ms), fmt(r.reaccion_dinamica_ms), r.partes))
        print()
        if self.args.informe_json:
            musicos = {name: asdict(r) for name, r in met.items()}
            with open(self.args.informe_json, "w") as f:
                json.dump({"obra": self.obra.nombre, "tolerancia": self.args.tolerancia, "musicos": musicos}, f, indent=2)

    def run(self) -> None:
        print("[teatro] obra %s, tempo %g, partes: %s" % (
            self.obra.nombre, self.obra.tempo, ", ".join(self.obra.partes)))
        print("[teatro] TCP %d, UDP %d, sala en http://localhost:%d/" % (
            self.args.puerto, self.args.puerto + 1, self.args.puerto + 2))
        broadcast("obra", json.dumps({"nombre": self.obra.nombre, "tempo": self.obra.tempo,
                                      "fin": self.end_beat, "partes": list(self.obra.partes)}))
        auto_start_at = None
        while not self.quit:
            for key, _ in self.sel.select(timeout=0.05):
                key.data(key.fileobj)
            now = time.monotonic()
            if now - self.last_tick >= TICK_PERIOD:
                self.last_tick = now
                self.send_ticks()
            # --esperar N: arranca un segundo después de que haya N músicos listos
            if self.args.esperar and not self.started_once and self.listos >= self.args.esperar:
                if auto_start_at is None:
                    auto_start_at = now + 1.0
                elif now >= auto_start_at:
                    self.command("empezar")
            # guion: si el reloj está parado, el comando siguiente sale un segundo después
            if self.guion and self.started_once:
                due = self.clock.running and self.clock.beat() >= self.guion[0][0]
                stopped = not self.clock.running and now - self.stopped_at > 1.0
                if due or stopped:
                    _, cmd = self.guion.pop(0)
                    print("[teatro] guion: %s" % cmd)
                    self.command(cmd)
            if self.started_once and self.clock.running and self.clock.beat() > self.end_beat + 2:
                self.command("parar")
                print("[teatro] fin de la obra, en el beat %g" % self.end_beat)
                broadcast("sena", "TERMINO")
                if self.args.salir_al_final:
                    self.informe()
                    self.command("salir")


def describe(pitch: int, vel: int, sucio: int) -> str:
    if vel == 0 or pitch < 0 and not sucio:
        return "silencio"
    if sucio:
        return "SUCIO (vel %d)" % vel
    return "suena %d vel %d" % (pitch, vel)


def note_ons(heard: list[Sonido]) -> tuple[list[tuple[float, int]], int]:
    """Ataques limpios (beat, pitch) y cantidad de sucios. Cada voz se sigue por separado."""
    ons: list[tuple[float, int]] = []
    sucios = 0
    prev: dict[str, tuple[int, bool, bool]] = {}   # voz -> pitch, suena, sucio
    for (beat, pitch, vel, sucio, voz) in heard:
        prev_pitch, prev_on, prev_sucio = prev.get(voz, (-1, False, False))
        on = vel > 0 and (pitch >= 0 or bool(sucio))
        if on and sucio and not prev_sucio:
            sucios += 1
        if on and not sucio and (not prev_on or prev_sucio or pitch != prev_pitch):
            ons.append((beat, pitch))
        prev[voz] = (pitch, on, on and bool(sucio))
    return sorted(ons), sucios


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--obra", default=os.path.join(HERE, "..", "obras", "fray_santiago.txt"))
    ap.add_argument("--puerto", type=int, default=5100, help="TCP; UDP es +1 y la sala +2")
    ap.add_argument("--esperar", type=int, default=0, help="empezar solo cuando haya N músicos listos")
    ap.add_argument("--salir-al-final", action="store_true", help="al terminar la obra, imprimir el informe y salir")
    ap.add_argument("--sin-consola", action="store_true")
    ap.add_argument("--ver", action="store_true", help="imprimir cada SUENA")
    ap.add_argument("--guion", default="", help="comandos en beats, ej: '10:tempo 90,20:dinamica 40'")
    ap.add_argument("--informe-json", default="", help="además de imprimirlo, escribir el informe acá")
    ap.add_argument("--tolerancia", type=float, default=0.2, help="beats de tolerancia para 'a tiempo'")
    args = ap.parse_args()
    opciones = Opciones(args.puerto, args.esperar, args.salir_al_final, args.sin_consola, args.ver,
                        args.guion, args.informe_json, args.tolerancia)
    teatro = Teatro(load_obra(args.obra), opciones)
    httpd = ThreadingHTTPServer(("0.0.0.0", args.puerto + 2), SalaHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        teatro.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
