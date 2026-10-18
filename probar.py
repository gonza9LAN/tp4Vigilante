#!/usr/bin/env python3
"""Verificador del TP4. Es el mismo que usa la cátedra para corregir.

Por cada nivel levanta el teatro, un instrumento por músico y el correr.sh del
grupo, deja tocar la obra entera y compara lo que midió el teatro con los
umbrales. Si un nivel no pasa se repite, hasta INTENTOS veces, y vale el mejor.
Escribe informe_verificador.json y deja los logs en verificador_logs/.

  python3 probar.py                              # ./correr.sh con flauta y violín, todos los niveles
  python3 probar.py --tipos clarinete,cello
  python3 probar.py --nivel 1
  python3 probar.py --intentos 1                 # sin repetir
  python3 probar.py --correr ../otro/correr.sh
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import IO, Any

HERE = os.path.dirname(os.path.abspath(__file__))
PUERTO = 5100
PUERTO_INSTRUMENTO = 6000


@dataclass
class Nivel:
    nivel: int
    nombre: str
    caos: list[str] = field(default_factory=lambda: [])
    guion: str = ""
    tipos: list[str] | None = None   # si no, los de --tipos
    obra: str | None = None          # si no, la de --obra


@dataclass
class Umbral:
    a_tiempo_min: float   # fracción de las notas esperadas
    faltantes_max: int
    sucios_max: int
    torpezas_max: int
    reaccion_max_ms: float | None = None   # solo en los niveles con señas


NIVELES = [
    Nivel(0, "sin caos, con señas", guion="10.5:dinamica 50,18.5:parar,0:desde 18"),
    Nivel(1, "pérdida 10 %", caos=["--perdida", "0.1"]),
    Nivel(2, "pérdida 20 %, desorden 20 %, duplicados 20 %",
          caos=["--perdida", "0.2", "--desorden", "0.2", "--duplicados", "0.2"]),
    Nivel(3, "acordes en la guitarra, sin caos", tipos=["guitarra"], obra="bossa_del_relojero.txt"),
]

UMBRALES = {
    0: Umbral(a_tiempo_min=1.00, faltantes_max=0, sucios_max=0, torpezas_max=0, reaccion_max_ms=500),
    1: Umbral(a_tiempo_min=0.90, faltantes_max=0, sucios_max=6, torpezas_max=2),
    2: Umbral(a_tiempo_min=0.65, faltantes_max=2, sucios_max=12, torpezas_max=4),
    3: Umbral(a_tiempo_min=0.95, faltantes_max=2, sucios_max=4, torpezas_max=2),
}

INTENTOS = 3

Fila = tuple[str, str, bool]   # músico, resumen, pasa


@dataclass
class Medicion:
    """Lo que midió el teatro para un músico (ver su --informe-json)."""
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

    @staticmethod
    def de_json(d: dict[str, Any]) -> Medicion:
        return Medicion(d["esperadas"], d["a_tiempo"], d["tarde"], d["faltantes"], d["sucios"], d["extranas"],
                        d["torpezas"], d["partes"], d["reaccion_parar_ms"], d["reaccion_dinamica_ms"])


@dataclass
class Intento:
    numero: int
    error: str | None
    datos: dict[str, Any] | None   # el JSON del teatro, tal cual
    ok: bool = False
    filas: list[Fila] = field(default_factory=lambda: [])


def familia(tipo: str) -> str:
    for raw in open(os.path.join(HERE, "tablas", tipo + ".txt")):
        f = raw.split("#")[0].split()
        if f and f[0] == "FAMILIA":
            return f[1]
    raise SystemExit("tabla sin FAMILIA: " + tipo)


def nombres(tipos: list[str]) -> list[tuple[str, str]]:
    """flauta,violin,flauta -> flauta1, violin1, flauta2."""
    visto: dict[str, int] = {}
    out: list[tuple[str, str]] = []
    for t in tipos:
        visto[t] = visto.get(t, 0) + 1
        out.append(("%s%d" % (t, visto[t]), t))
    return out


def partes_esperadas(tipo: str) -> int:
    return 2 if familia(tipo) == "cuerda" else 3


def duracion_obra(path: str) -> float:
    end = 0.0
    for raw in open(path):
        f = raw.split()
        if f and f[0] == "NOTA":
            end = max(end, float(f[1]) + float(f[2]))
    return end


def matar(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def correr_nivel(nivel: Nivel, tipos: list[str], obra: str, correr: str, logs: str,
                 intento: int) -> tuple[dict[str, Any] | None, str | None]:
    obra = os.path.join(HERE, "obras", obra)
    prefijo = "nivel%d_intento%d_" % (nivel.nivel, intento)
    informe = os.path.join(logs, prefijo + "teatro.json")
    if os.path.exists(informe):
        os.remove(informe)
    procs: list[subprocess.Popen[bytes]] = []
    lanzadores: list[subprocess.Popen[bytes]] = []
    abiertos: list[IO[str]] = []

    def lanzar(nombre: str, cmd: list[str], cwd: str | None = None) -> subprocess.Popen[bytes]:
        f = open(os.path.join(logs, prefijo + nombre + ".log"), "w")
        abiertos.append(f)
        p = subprocess.Popen(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        procs.append(p)
        return p

    teatro_cmd = [sys.executable, "-u", os.path.join(HERE, "teatro", "teatro.py"), "--obra", obra,
                  "--esperar", str(len(tipos)), "--salir-al-final", "--sin-consola", "--puerto", str(PUERTO),
                  "--informe-json", informe]
    if nivel.guion:
        teatro_cmd += ["--guion", nivel.guion]
    teatro = lanzar("teatro", teatro_cmd)
    time.sleep(0.5)
    if teatro.poll() is not None:
        return None, "el teatro no arrancó (¿puerto %d ocupado?)" % PUERTO
    for i, (nombre, tipo) in enumerate(nombres(tipos)):
        puerto = PUERTO_INSTRUMENTO + i
        lanzar("instrumento_" + nombre, [sys.executable, "-u", os.path.join(HERE, "instrumento", "instrumento.py"),
                                         "--tipo", tipo, "--musico", nombre, "--puerto", str(puerto),
                                         "--teatro", "127.0.0.1:%d" % (PUERTO + 1)] + nivel.caos)
        lanzadores.append(lanzar("musico_" + nombre, ["bash", os.path.abspath(correr), nombre, tipo,
                                                      "127.0.0.1:%d" % PUERTO, "127.0.0.1:%d" % puerto],
                                 cwd=os.path.dirname(os.path.abspath(correr))))
    limite = time.time() + duracion_obra(obra) / 2.0 + 60   # la obra a 120 bpm, más un minuto
    error = None
    while teatro.poll() is None and time.time() < limite:
        time.sleep(0.5)
        if all(p.poll() is not None for p in lanzadores):
            # si el teatro ya mandó FIN, los músicos pueden terminar antes que él
            try:
                teatro.wait(timeout=3)
            except subprocess.TimeoutExpired:
                codigos = ", ".join(str(p.returncode) for p in lanzadores)
                error = "correr.sh terminó antes del FIN (código %s): el músico tiene que quedarse hasta que el teatro lo despida" % codigos
            break
    if error is None and teatro.poll() is None:
        error = "el teatro no terminó a tiempo: ¿el músico nunca mandó LISTO o nunca pidió ticks?"
    # después de FIN, el músico tiene 3 s para cerrarse solo
    espera = time.time() + 3.0
    while any(p.poll() is None for p in lanzadores) and time.time() < espera:
        time.sleep(0.2)
    vivos = [p for p in lanzadores if p.poll() is None]
    for p in procs:
        matar(p)
    for f in abiertos:
        f.close()
    if error:
        return None, error
    if not os.path.exists(informe):
        return None, "el teatro no escribió el informe"
    with open(informe) as f:
        datos: dict[str, Any] = json.load(f)
    datos["procesos_vivos_tras_fin"] = len(vivos) > 0
    return datos, None


def evaluar(nivel: Nivel, datos: dict[str, Any], tipos: list[str]) -> tuple[bool, list[Fila]]:
    u = UMBRALES[nivel.nivel]
    filas: list[Fila] = []
    ok_nivel = True
    for nombre, tipo in nombres(tipos):
        if nombre not in datos["musicos"]:
            filas.append((nombre, "no se registró", False))
            ok_nivel = False
            continue
        r = Medicion.de_json(datos["musicos"][nombre])
        fallas: list[str] = []
        if r.a_tiempo < u.a_tiempo_min * r.esperadas:
            fallas.append("a tiempo %d de %d" % (r.a_tiempo, r.esperadas))
        if r.faltantes > u.faltantes_max:
            fallas.append("faltantes %d" % r.faltantes)
        if r.sucios > u.sucios_max:
            fallas.append("sucios %d" % r.sucios)
        if r.torpezas > u.torpezas_max:
            fallas.append("torpezas %d" % r.torpezas)
        if r.partes < partes_esperadas(tipo):
            fallas.append("partes %d, se esperaban %d sockets distintos" % (r.partes, partes_esperadas(tipo)))
        if u.reaccion_max_ms is not None:
            for ms, sena in ((r.reaccion_parar_ms, "parar"), (r.reaccion_dinamica_ms, "dinámica")):
                if ms is None:
                    fallas.append("no se pudo medir la reacción a %s" % sena)
                elif ms > u.reaccion_max_ms:
                    fallas.append("reacción a %s %.0f ms" % (sena, ms))
        ok = not fallas
        ok_nivel = ok_nivel and ok
        resumen = "a tiempo %d/%d, tarde %d, faltantes %d, sucios %d, extrañas %d, torpezas %d, partes %d" % (
            r.a_tiempo, r.esperadas, r.tarde, r.faltantes, r.sucios, r.extranas, r.torpezas, r.partes)
        if r.reaccion_parar_ms is not None:
            resumen += ", parar %.0f ms" % r.reaccion_parar_ms
        if r.reaccion_dinamica_ms is not None:
            resumen += ", dinámica %.0f ms" % r.reaccion_dinamica_ms
        filas.append((nombre, resumen + ("" if ok else "  <- " + "; ".join(fallas)), ok))
    if datos.get("procesos_vivos_tras_fin"):
        filas.append(("(procesos)", "quedaron procesos del músico vivos después de FIN", False))
        ok_nivel = False
    return ok_nivel, filas


def puntaje(intento: Intento) -> tuple[bool, int, int, int]:
    """El mejor intento: el que pasa, después más músicos bien, más notas a tiempo, menos sucios y torpezas."""
    if intento.error or intento.datos is None:
        return (False, -1, 0, 0)
    musicos = [Medicion.de_json(d) for d in intento.datos["musicos"].values()]
    return (intento.ok,
            sum(1 for _, _, ok in intento.filas if ok),
            sum(r.a_tiempo for r in musicos),
            -sum(r.sucios + r.torpezas for r in musicos))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--correr", default=os.path.join(HERE, "correr.sh"), help="el lanzador del músico")
    ap.add_argument("--tipos", default="flauta,violin", help="instrumentos a probar, separados por coma")
    ap.add_argument("--nivel", type=int, default=-1, help="correr solo este nivel (0 a 3)")
    ap.add_argument("--obra", default="fray_santiago.txt")
    ap.add_argument("--logs", default=os.path.join(HERE, "verificador_logs"))
    ap.add_argument("--intentos", type=int, default=INTENTOS, help="intentos por nivel; vale el mejor")
    args = ap.parse_args()
    correr: str = args.correr
    logs: str = args.logs
    n_intentos: int = args.intentos
    if not os.path.exists(correr):
        raise SystemExit("no existe %s" % correr)
    os.makedirs(logs, exist_ok=True)
    tipos: list[str] = args.tipos.split(",")
    niveles: list[dict[str, Any]] = []
    resultado: dict[str, Any] = {"correr": os.path.abspath(correr), "tipos": tipos, "niveles": niveles}
    todo_ok = True
    for nivel in NIVELES:
        if args.nivel >= 0 and nivel.nivel != args.nivel:
            continue
        print("=== nivel %d: %s ===" % (nivel.nivel, nivel.nombre))
        for viejo in os.listdir(logs):   # los logs de una corrida anterior confunden
            if viejo.startswith("nivel%d_" % nivel.nivel):
                os.remove(os.path.join(logs, viejo))
        tipos_nivel = nivel.tipos or tipos
        intentos: list[Intento] = []
        for i in range(1, n_intentos + 1):
            datos, error = correr_nivel(nivel, tipos_nivel, nivel.obra or args.obra, correr, logs, i)
            intento = Intento(i, error, datos)
            if datos is not None and not error:
                intento.ok, intento.filas = evaluar(nivel, datos, tipos_nivel)
            intentos.append(intento)
            if intento.ok:
                break
            if i < n_intentos:
                print("   intento %d de %d: no pasa, se repite" % (i, n_intentos))
        mejor = max(intentos, key=puntaje)
        de = "intento %d de %d" % (mejor.numero, len(intentos))
        if mejor.error or mejor.datos is None:
            print("   ERROR: %s" % mejor.error)
            niveles.append({"nivel": nivel.nivel, "ok": False, "error": mejor.error,
                            "intento": mejor.numero, "intentos": len(intentos)})
            todo_ok = False
            continue
        for nombre, texto, fila_ok in mejor.filas:
            print("   %s %-12s %s" % ("ok " if fila_ok else "MAL", nombre, texto))
        print("   nivel %d: %s (%s)" % (nivel.nivel, "PASA" if mejor.ok else "NO PASA", de))
        niveles.append({"nivel": nivel.nivel, "ok": mejor.ok, "musicos": mejor.datos["musicos"],
                        "intento": mejor.numero, "intentos": len(intentos)})
        todo_ok = todo_ok and mejor.ok
    with open(os.path.join(HERE, "informe_verificador.json"), "w") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
    print("informe en informe_verificador.json, logs en %s" % logs)
    sys.exit(0 if todo_ok else 1)


if __name__ == "__main__":
    main()
