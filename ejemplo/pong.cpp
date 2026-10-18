// Ejemplo UDP, servidor: contesta PONG n a cada PING n. Con --perdida p descarta
// esa fracción de los pings.
//   ./pong [puerto] [--perdida 0.3]
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>

int main(int argc, char** argv) {
    setvbuf(stdout, nullptr, _IOLBF, 0);   // salida línea por línea aunque vaya a un archivo
    int port = argc > 1 && argv[1][0] != '-' ? atoi(argv[1]) : 7000;
    double loss = 0;
    for (int i = 1; i + 1 < argc; i++)
        if (!strcmp(argv[i], "--perdida")) loss = atof(argv[i + 1]);

    srand48(time(nullptr));
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    sockaddr_in me{};
    me.sin_family = AF_INET;
    me.sin_addr.s_addr = INADDR_ANY;
    me.sin_port = htons(port);
    if (bind(fd, (sockaddr*)&me, sizeof me) < 0) { perror("bind"); return 1; }
    printf("pong escuchando en UDP %d, pérdida %.0f%%\n", port, loss * 100);

    char buf[2048];
    while (true) {
        sockaddr_in from{};
        socklen_t fromlen = sizeof from;
        ssize_t n = recvfrom(fd, buf, sizeof buf - 1, 0, (sockaddr*)&from, &fromlen);
        if (n <= 0) continue;
        buf[n] = 0;
        if (drand48() < loss) { printf("  (perdí: %s)\n", buf); continue; }
        std::string reply = std::string("PONG") + (buf + 4);   // "PING 17" -> "PONG 17"
        sendto(fd, reply.data(), reply.size(), 0, (sockaddr*)&from, fromlen);
        printf("%s -> %s\n", buf, reply.c_str());
    }
}
