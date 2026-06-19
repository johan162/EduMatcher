#include "ralf_parser.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

static int send_line(int fd, const char *line) {
    size_t len = strlen(line);
    if (write(fd, line, len) != (ssize_t)len) return -1;
    if (write(fd, "\n", 1) != 1) return -1;
    return 0;
}

static int recv_line(int fd, char *buf, size_t cap) {
    size_t n = 0;
    while (n + 1 < cap) {
        char c;
        ssize_t r = read(fd, &c, 1);
        if (r <= 0) return -1;
        if (c == '\n') break;
        buf[n++] = c;
    }
    buf[n] = '\0';
    return 0;
}

static int connect_gateway(const char *host, int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);

    if (inet_pton(AF_INET, host, &addr.sin_addr) != 1) {
        close(fd);
        return -1;
    }

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        close(fd);
        return -1;
    }

    return fd;
}

int main(int argc, char **argv) {
    const char *host = "127.0.0.1";
    int port = 5580;
    const char *role = "CLEARING";

    if (argc > 1) host = argv[1];
    if (argc > 2) port = atoi(argv[2]);
    if (argc > 3) role = argv[3];

    int fd = connect_gateway(host, port);
    if (fd < 0) {
        perror("connect_gateway");
        return 1;
    }

    char hello[256];
    snprintf(
        hello,
        sizeof(hello),
        "HELLO|CLIENT=ext-c-01|PROTO=RALF1|ROLE=%s|LASTSEQ=0",
        role
    );

    if (send_line(fd, hello) != 0) {
        perror("send HELLO");
        close(fd);
        return 1;
    }

    char line[4096];
    if (recv_line(fd, line, sizeof(line)) != 0) {
        perror("recv WELCOME");
        close(fd);
        return 1;
    }

    ralf_message_t welcome;
    if (ralf_parse_line(line, &welcome) != 0) {
        fprintf(stderr, "failed to parse WELCOME\n");
        close(fd);
        return 1;
    }

    printf("WELCOME type=%s GW=%s ROLE=%s\n",
           welcome.msg_type,
           ralf_get_field(&welcome, "GW") ? ralf_get_field(&welcome, "GW") : "?",
           ralf_get_field(&welcome, "ROLE") ? ralf_get_field(&welcome, "ROLE") : "?");

    /* Subscribe to all major channels for demonstration. */
    if (send_line(fd, "SUB|ROLE=CLEARING|CH=CLEARING|SYM=*") != 0 ||
        send_line(fd, "SUB|ROLE=DROP_COPY|CH=DROP_COPY|SYM=AAPL,MSFT") != 0 ||
        send_line(fd, "SUB|ROLE=AUDIT|CH=AUDIT|SYM=*") != 0) {
        perror("send SUB");
        close(fd);
        return 1;
    }

    printf("Subscribed as %s\n", role);

    while (recv_line(fd, line, sizeof(line)) == 0) {
        ralf_message_t msg;
        if (ralf_parse_line(line, &msg) != 0) {
            fprintf(stderr, "parse error: %s\n", line);
            continue;
        }
        printf("MSG type=%s CH=%s SEQ=%s SYM=%s\n",
               msg.msg_type,
               ralf_get_field(&msg, "CH") ? ralf_get_field(&msg, "CH") : "-",
               ralf_get_field(&msg, "SEQ") ? ralf_get_field(&msg, "SEQ") : "-",
               ralf_get_field(&msg, "SYM") ? ralf_get_field(&msg, "SYM") : "-");
    }

    close(fd);
    return 0;
}
