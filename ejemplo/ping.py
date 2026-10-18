# Ejemplo UDP, cliente: manda PING n cada 500 ms y espera el PONG con selectors
# y un timeout de 200 ms. Si no llega, lo cuenta como perdido. Un PONG que llega
# tarde no se confunde con la respuesta al PING siguiente.
#   python3 ping.py [host] [puerto]
import selectors
import socket
import sys
import time

host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 7000
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # sin bind: el sistema elige el puerto
sel = selectors.DefaultSelector()
sel.register(sock, selectors.EVENT_READ)

sent = lost = 0
n = 0
while True:
    n += 1
    t0 = time.monotonic()
    sock.sendto(f"PING {n}".encode(), (host, port))
    sent += 1
    deadline = t0 + 0.2
    answered = False
    while not answered:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not sel.select(remaining):
            break
        data, _ = sock.recvfrom(2048)
        text = data.decode()
        if text == f"PONG {n}":
            print(f"{text} en {(time.monotonic() - t0) * 1000:.1f} ms", flush=True)
            answered = True
        else:
            print(f"  (llegó tarde: {text})", flush=True)
    if not answered:
        lost += 1
        print(f"PING {n} sin respuesta ({lost} de {sent} perdidos)", flush=True)
    time.sleep(0.5)
