// Ejemplo UDP, cliente: manda PING n cada 500 ms y espera el PONG con poll y
// un timeout de 200 ms. Si no llega, lo cuenta como perdido.
//   ./ping [host] [puerto]
#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>

static double now_ms() {
    using namespace std::chrono;
    return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}

int main(int argc, char** argv) {
    setvbuf(stdout, nullptr, _IOLBF, 0);   // salida línea por línea aunque vaya a un archivo
    const char* host = argc > 1 ? argv[1] : "127.0.0.1";
    int port = argc > 2 ? atoi(argv[2]) : 7000;
    int fd = socket(AF_INET, SOCK_DGRAM, 0);   // sin bind: el sistema elige el puerto
    sockaddr_in to{};
    to.sin_family = AF_INET;
    to.sin_port = htons(port);
    inet_pton(AF_INET, host, &to.sin_addr);

    int sent = 0, lost = 0;
    for (int n = 1;; n++) {
        std::string msg = "PING " + std::to_string(n);
        double t0 = now_ms();
        sendto(fd, msg.data(), msg.size(), 0, (sockaddr*)&to, sizeof to);
        sent++;
        pollfd p = {fd, POLLIN, 0};
        int ready = poll(&p, 1, 200);
        if (ready > 0 && (p.revents & POLLIN)) {
            char buf[2048];
            ssize_t len = recv(fd, buf, sizeof buf - 1, 0);
            if (len > 0) { buf[len] = 0; printf("%s en %.1f ms\n", buf, now_ms() - t0); }
        } else {
            lost++;
            printf("PING %d sin respuesta (%d de %d perdidos)\n", n, lost, sent);
        }
        usleep(500000);
    }
}
