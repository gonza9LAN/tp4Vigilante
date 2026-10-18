# Ejemplo UDP, servidor: contesta PONG n a cada PING n. Con --perdida p descarta
# esa fracción de los pings.
#   python3 pong.py [puerto] [--perdida 0.3]
import random
import socket
import sys

args = sys.argv[1:]
port = int(args[0]) if args and not args[0].startswith("-") else 7000
loss = float(args[args.index("--perdida") + 1]) if "--perdida" in args else 0.0

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", port))
print(f"pong escuchando en UDP {port}, pérdida {loss:.0%}", flush=True)

while True:
    data, sender = sock.recvfrom(2048)
    text = data.decode()
    if random.random() < loss:
        print(f"  (perdí: {text})", flush=True)
        continue
    reply = "PONG" + text[4:]             # "PING 17" -> "PONG 17"
    sock.sendto(reply.encode(), sender)
    print(f"{text} -> {reply}", flush=True)
