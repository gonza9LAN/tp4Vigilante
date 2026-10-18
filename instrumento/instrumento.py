#!/usr/bin/env python3
"""Instrumento del TP4. Corre en la máquina del músico, uno por músico.

Recibe DEDO y ENERGIA por UDP, contesta ECO, resuelve con la tabla qué suena y
le manda SUENA y ESTADO al teatro. Las reglas están en el contrato (§5 a §8).

Caos: --perdida p, --duplicados p y --desorden p sobre lo que entra; la
pérdida también se aplica a los ECO que salen.
"""
from __future__ import annotations

import argparse
import os
import random
import selectors
import socket
import time
from dataclasses import dataclass, field
from typing import Any

TRANSIT_MS = 50       # lo que tarda un dedo en llegar
ENERGY_TIMEOUT = 0.5  # sin ENERGIA en este tiempo, la energía cae a 0
ECO_PERIOD = 0.2
ARRIBA = "arriba"

Mano = tuple[str, int]         # (mano, dedo)
Sonido = tuple[int, int, int]  # pitch, valor, sucio


@dataclass
class Tabla:
    familia: str = ""
    manos: dict[str, int] = field(default_factory=lambda: {})
    cuerdas: dict[str, int] = field(default_factory=lambda: {})   # cuerda -> pitch al aire
    filas: list[list[str]] = field(default_factory=lambda: [])
    rango: tuple[int, int] = (0, 127)
    ancho: int = 12
    modo: str = "arco"


@dataclass
class Dedo:
    place: str = ARRIBA
    target: str = ARRIBA
    until: float = 0.0   # en viaje mientras now < until


@dataclass
class Voz:
    pitch: int = -1
    force: int = 0
    sucio: int = 0


@dataclass
class Opciones:
    tipo: str
    tabla: str
    musico: str
    puerto: int
    teatro: str
    perdida: float
    duplicados: float
    desorden: float


def load_table(path: str) -> Tabla:
    t = Tabla()
    for raw in open(path):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        f = line.split()
        if f[0] == "FAMILIA":
            t.familia = f[1]
        elif f[0] == "MANOS":
            for spec in f[1:]:
                hand, n = spec.split(":")
                t.manos[hand] = int(n)
        elif f[0] == "CUERDAS":
            for spec in f[1:]:
                s, p = spec.split(":")
                t.cuerdas[s] = int(p)
        elif f[0] == "RANGO":
            t.rango = (int(f[1]), int(f[2]))
        elif f[0] == "MODO":
            t.modo = f[1]
        elif f[0] == "ANCHO":
            t.ancho = int(f[1])
        else:
            t.filas.append(f)
    return t


def wind_state_for_row(row: list[str]) -> frozenset[Mano]:
    """Fila 'pitch izq der' -> los dedos que están abajo."""
    down: set[Mano] = set()
    for hand, spec in (("izq", row[1]), ("der", row[2])):
        if spec != "-":
            for d in spec.split(","):
                down.add((hand, int(d)))
    return frozenset(down)


class Instrumento:
    def __init__(self, args: Opciones) -> None:
        self.args = args
        self.table = load_table(args.tabla)
        self.familia = self.table.familia
        self.fingers: dict[Mano, Dedo] = {}
        for hand, n in self.table.manos.items():
            for d in range(1, n + 1):
                self.fingers[(hand, d)] = Dedo()
        self.by_state: dict[frozenset[Mano], int] = {}
        if self.familia == "viento":
            self.by_state = {wind_state_for_row(r): int(r[0]) for r in self.table.filas}
        self.part_addr: dict[str, Any] = {}   # izq, der o energia -> última dirección
        self.seen: dict[str, list[str]] = {}  # mano -> últimos seq procesados
        self.torpezas = 0
        self.energy = 0
        self.string = "-"
        self.energy_time = 0.0
        self.sound: Sonido = (-1, 0, 0)       # vientos: último SUENA
        self.last_torpezas = 0
        self.voices = {k: Voz() for k in self.fingers}   # piano: una voz por dedo
        self.voice_sent: dict[Mano, Sonido] = {k: (-1, 0, 0) for k in self.fingers}
        self.string_sent: dict[str, Sonido] = {s: (-1, 0, 0) for s in self.table.cuerdas}   # cuerdas: una voz por cuerda
        self.last_vel_sent = 0.0
        self.held: tuple[str, Any] | None = None   # datagrama retenido por --desorden
        self.last_state = ""
        self.last_state_time = 0.0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", args.puerto))
        host, port = args.teatro.split(":")
        self.teatro = (host, int(port))
        self.last_eco = 0.0

    def on_datagram(self) -> None:
        data, addr = self.sock.recvfrom(2048)
        msg = data.decode(errors="replace").strip()
        r = random.random
        if r() < self.args.perdida:
            print("[caos] perdido: %s" % msg)
            return
        copies = 2 if r() < self.args.duplicados else 1
        if copies == 2:
            print("[caos] duplicado: %s" % msg)
        for _ in range(copies):
            if self.held is None and r() < self.args.desorden:
                print("[caos] retenido: %s" % msg)
                self.held = (msg, addr)
                continue
            self.handle(msg, addr)
            if self.held is not None:
                hm, ha = self.held
                self.held = None
                print("[caos] soltado: %s" % hm)
                self.handle(hm, ha)

    def handle(self, msg: str, addr: Any) -> None:
        f = msg.split()
        if not f:
            return
        now = time.monotonic()
        if f[0] == "DEDO" and len(f) >= 5:
            hand, dedo, place, seq = f[1], int(f[2]), f[3], f[4]
            self.part_addr[hand] = addr
            fg = self.fingers.get((hand, dedo))
            if fg is None:
                print("[instrumento] dedo inexistente: %s %d" % (hand, dedo))
                return
            seen = self.seen.setdefault(hand, [])
            if seq in seen:   # reenvío: se contesta sin mover nada
                self.send_eco_hand(hand, seq, addr)
                return
            seen.append(seq)
            del seen[:-64]
            if place == fg.target:   # movimiento en falso: se mueve igual
                self.torpezas += 1
                print("[instrumento] torpeza %d: %s %d ya estaba en %s" % (self.torpezas, hand, dedo, place))
            fg.target = place
            fg.until = now + TRANSIT_MS / 1000.0
            self.send_eco_hand(hand, seq, addr)
        elif f[0] == "ECO?" and len(f) >= 2:
            self.part_addr[f[1]] = addr
            if f[1] == "energia":
                self.send_eco_energy("0", addr)
            else:
                self.send_eco_hand(f[1], "0", addr)
        elif f[0] == "ENERGIA" and len(f) >= 4:
            self.energy = max(0, min(100, int(float(f[1]))))
            self.string = f[2]
            self.energy_time = now
            self.part_addr["energia"] = addr
            self.send_eco_energy(f[3], addr)
        else:
            print("[instrumento] mensaje raro: %s" % msg)

    def send(self, msg: str, addr: Any) -> None:
        if random.random() < self.args.perdida:
            print("[caos] eco perdido: %s" % msg)
            return
        self.sock.sendto(msg.encode(), addr)

    def send_eco_hand(self, hand: str, seq: str, addr: Any) -> None:
        parts: list[str] = []
        now = time.monotonic()
        for (h, d), fg in sorted(self.fingers.items()):
            if h != hand:
                continue
            if now < fg.until:
                parts.append("%d=~%s" % (d, fg.target))
            else:
                parts.append("%d=%s" % (d, fg.place))
        self.send("ECO %s %s %s" % (hand, seq, ",".join(parts)), addr)

    def send_eco_energy(self, seq: str, addr: Any) -> None:
        self.send("ECO energia %s %d %s" % (seq, self.energy, self.string), addr)

    def settle(self, now: float) -> None:
        for fg in self.fingers.values():
            if fg.place != fg.target and now >= fg.until:
                fg.place = fg.target

    def resolve_wind(self, now: float) -> tuple[int | None, bool]:
        """(pitch o None, sucio) según los dedos."""
        if any(now < fg.until for fg in self.fingers.values()):
            return None, True
        state = frozenset(k for k, fg in self.fingers.items() if fg.place != ARRIBA)
        pitch = self.by_state.get(state)
        return pitch, pitch is None

    def emit(self, pitch: int, valor: int, sucio: int, voz: str) -> None:
        partes = len(set(self.part_addr.values()))
        msg = "SUENA %s %d %d %d %d %d %s" % (self.args.musico, pitch, valor, sucio, partes, self.torpezas, voz)
        self.sock.sendto(msg.encode(), self.teatro)
        print("[%.3f] %s" % (time.monotonic(), msg))

    def step_strings(self, now: float) -> None:
        # una voz por cuerda, con la posición más alta de los dedos apoyados;
        # con arco, más de dos cuerdas o dos que no son vecinas suenan sucias todas
        names = list(self.table.cuerdas)
        wanted = [s for s in self.string.split(",") if s in names] if self.energy > 0 else []
        bad_bow = False
        if self.table.modo == "arco" and wanted:
            idx = sorted(names.index(s) for s in wanted)
            bad_bow = len(idx) > 2 or (len(idx) == 2 and idx[1] - idx[0] != 1)
        changed_any = False
        for s in names:
            if s not in wanted:
                state: Sonido = (-1, 0, 0)
            else:
                lugar, moving = 0, False
                for fg in self.fingers.values():
                    en_viaje = now < fg.until
                    # un dedo en viaje ensucia la cuerda de la que sale y a la que va
                    for place in ((fg.place, fg.target) if en_viaje else (fg.place,)):
                        if place == ARRIBA or ":" not in place or place.split(":")[0] != s:
                            continue
                        if en_viaje:
                            moving = True
                        else:
                            lugar = max(lugar, int(place.split(":")[1]))
                sucio = 1 if (moving or bad_bow) else 0
                state = (self.table.cuerdas[s] + lugar if not sucio else -1, self.energy, sucio)
            if state != self.string_sent[s]:
                self.string_sent[s] = state
                self.emit(state[0], state[1], state[2], s)
                changed_any = True
        if self.torpezas != self.last_torpezas and not changed_any:
            self.emit(*self.string_sent[names[0]], names[0])
        self.last_torpezas = self.torpezas

    def step_keyboard(self, now: float) -> None:
        # una voz por dedo; con el pedal abajo la tecla sigue sonando aunque el dedo se levante;
        # si las teclas de una mano no entran en ANCHO, esa mano suena sucia
        pedal = self.energy > 0
        lo, hi = self.table.rango
        pressed: dict[str, list[int]] = {}
        for (h, _), fg in self.fingers.items():
            if now >= fg.until and fg.place != ARRIBA:
                pressed.setdefault(h, []).append(int(fg.place.split(":")[0]))
        cramped = {h: (max(ks) - min(ks) > self.table.ancho) for h, ks in pressed.items()}
        changed_any = False
        for (h, d), fg in self.fingers.items():
            v = self.voices[(h, d)]
            settled = now >= fg.until
            if settled and fg.place != ARRIBA:
                key, force = fg.place.split(":")
                v.pitch, v.force = int(key), max(1, min(100, int(force)))
                v.sucio = 1 if (cramped.get(h) or not lo <= v.pitch <= hi) else 0
            elif not pedal:
                v.pitch, v.force, v.sucio = -1, 0, 0
            state = (v.pitch, v.force, v.sucio)
            if state != self.voice_sent[(h, d)]:
                self.voice_sent[(h, d)] = state
                self.emit(v.pitch, v.force, v.sucio, "%s%d" % (h, d))
                changed_any = True
        if self.torpezas != self.last_torpezas and not changed_any:
            k = next(iter(self.fingers))
            self.emit(*self.voice_sent[k], "%s%d" % k)
        self.last_torpezas = self.torpezas

    def step(self, now: float) -> None:
        self.settle(now)
        if self.energy > 0 and now - self.energy_time > ENERGY_TIMEOUT:
            print("[instrumento] energía sin refrescar, cae a 0")
            self.energy = 0
        if self.familia == "teclado":
            self.step_keyboard(now)
            self.send_periodic_ecos(now)
            return
        if self.familia == "cuerda":
            self.step_strings(now)
            self.send_periodic_ecos(now)
            return
        if self.energy == 0:
            new: Sonido = (-1, 0, 0)
        else:
            pitch, sucio = self.resolve_wind(now)
            new = (pitch if pitch is not None else -1, self.energy, 1 if sucio else 0)
        changed = (new[0], new[2], new[1] > 0) != (self.sound[0], self.sound[2], self.sound[1] > 0) \
            or self.torpezas != self.last_torpezas
        vel_changed = new[1] > 0 and abs(new[1] - self.sound[1]) >= 5 and now - self.last_vel_sent > 0.05
        if changed or vel_changed:
            self.sound = new
            self.last_vel_sent = now
            self.last_torpezas = self.torpezas
            self.emit(new[0], new[1], new[2], "-")
        self.send_periodic_ecos(now)

    def send_state(self, now: float) -> None:
        """ESTADO para la sala: solo si cambió, y no más de 20 por segundo."""
        hands: list[str] = []
        for hand in sorted(self.table.manos):
            parts: list[str] = []
            for (h, d), fg in sorted(self.fingers.items()):
                if h != hand:
                    continue
                parts.append("%d=%s%s" % (d, "~" if now < fg.until else "", fg.target))
            hands.append("%s=%s" % (hand, ",".join(parts)))
        if self.familia == "cuerda":
            extra = "cuerdas=" + ",".join("%s:%d" % kv for kv in self.table.cuerdas.items())
        elif self.familia == "teclado":
            extra = "rango=%d-%d;ancho=%d" % (self.table.rango[0], self.table.rango[1], self.table.ancho)
        else:
            extra = "-"
        state = "ESTADO %s %s %d %s %d %s %s" % (self.args.musico, self.familia, self.energy, self.string,
                                                self.torpezas, " ".join(hands), extra)
        if state != self.last_state and now - self.last_state_time > 0.05:
            self.last_state, self.last_state_time = state, now
            self.sock.sendto(state.encode(), self.teatro)

    def send_periodic_ecos(self, now: float) -> None:
        self.send_state(now)
        if now - self.last_eco > ECO_PERIOD:
            self.last_eco = now
            for part, addr in self.part_addr.items():
                if part == "energia":
                    self.send_eco_energy("0", addr)
                else:
                    self.send_eco_hand(part, "0", addr)

    def run(self) -> None:
        print("[instrumento] %s (%s) para %s en UDP %d, teatro %s:%d" % (
            self.args.tipo, self.familia, self.args.musico, self.args.puerto, *self.teatro))
        sel = selectors.DefaultSelector()
        sel.register(self.sock, selectors.EVENT_READ)
        while True:
            for _ in sel.select(timeout=0.01):
                self.on_datagram()
            self.step(time.monotonic())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tipo", required=True)
    ap.add_argument("--tabla", help="por defecto <carpeta de tablas>/<tipo>.txt")
    ap.add_argument("--tablas", help="carpeta de tablas; por defecto ../tablas respecto de este script")
    ap.add_argument("--musico", required=True, help="nombre con el que el cerebro se registró")
    ap.add_argument("--puerto", type=int, default=6000)
    ap.add_argument("--teatro", default="127.0.0.1:5101")
    ap.add_argument("--perdida", type=float, default=0.0)
    ap.add_argument("--duplicados", type=float, default=0.0)
    ap.add_argument("--desorden", type=float, default=0.0)
    args = ap.parse_args()
    tabla: str = args.tabla
    if not tabla:
        tablas: str = args.tablas or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tablas")
        tabla = os.path.join(tablas, args.tipo + ".txt")
    opciones = Opciones(args.tipo, tabla, args.musico, args.puerto, args.teatro,
                        args.perdida, args.duplicados, args.desorden)
    try:
        Instrumento(opciones).run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
