/* Full working DC1 (drop-copy) subscriber example (C).
 *
 * Goes beyond printing raw lines: connects to pm-dc-gwy for one
 * participant's gateway ID, then puts the received DC_FILL lines to use the
 * way a risk or back-office system would -- a running per-symbol tally of
 * fills, executed quantity, VWAP and the MAKER/TAKER split, a check of the
 * drop-copy SEQ for gaps and restarts, and a clean SIGINT shutdown that
 * prints the final tally before exiting.
 *
 * DC1 has no SUB step: the ID in HELLO is the whole subscription, and fills
 * start arriving straight after WELCOME.
 *
 * See docs/books/operator-guide/part-5-gateways/060-drop-copy-gateway.md for
 * the wire contract this client follows. The session rules it relies on are
 * the same in all three line gateways (pm-ralf-gwy, pm-md-gwy, pm-dc-gwy):
 * send HELLO straight after connecting (no HELLO within 5 s ends in
 * EXIT|REASON=auth_timeout); an ERR in reply to HELLO ends the session; a
 * gateway-initiated close is announced with a final ERR or EXIT|REASON=...;
 * a client that keeps reading needs no PING, since heartbeats count as
 * traffic; and a client may end its own session with a bare EXIT.
 */

#define _POSIX_C_SOURCE 200809L

#include "dc_parser.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#define MAX_SYMBOLS 16 /* bounded per-symbol tally table */

#define POLL_TIMEOUT_MS 200 /* worst-case delay before a Ctrl-C is noticed */

/* SIGINT sets this instead of taking the default terminate action;
 * recv_line() checks it after every poll() wake-up (see the comment
 * there and the sigaction() call in main()), so the client can print its
 * final tally and close the socket instead of being killed mid-syscall.
 */
static volatile sig_atomic_t g_running = 1;

static void handle_sigint(int signum) {
    (void)signum;
    g_running = 0;
}

/* ------------------------------------------------------------------ */
/* SEQ gap and restart check.
 *
 * SEQ is a separate counter for each gateway ID, so this session's fills are
 * numbered 1, 2, 3, ... A SEQ that skips ahead means fills were lost. A SEQ
 * at or below the last one seen is not a duplicate -- DC1 has no replay --
 * but an engine restart, which starts the counter again from 1.
 * ------------------------------------------------------------------ */

static long g_last_seq = -1; /* -1: nothing seen yet */

static void check_sequence(const char *seq_str) {
    if (!seq_str || !seq_str[0]) {
        return;
    }
    char *end = NULL;
    long seq = strtol(seq_str, &end, 10);
    if (*end != '\0') {
        return;
    }
    if (g_last_seq >= 0 && seq > g_last_seq + 1) {
        fprintf(stderr, "!! SEQ gap: %ld fill(s) missing between %ld and %ld\n", seq - g_last_seq - 1,
                g_last_seq, seq);
    } else if (g_last_seq >= 0 && seq <= g_last_seq) {
        fprintf(stderr, "!! SEQ went backwards: %ld after %ld (engine restarted?); re-baselining\n", seq,
                g_last_seq);
    }
    g_last_seq = seq;
}

/* ------------------------------------------------------------------ */
/* Per-symbol fill tally.
 *
 * DC_FILL carries no SIDE, so this is an activity tally -- volume, VWAP,
 * MAKER/TAKER split -- not a net position.
 * ------------------------------------------------------------------ */

typedef struct {
    char symbol[DC_MAX_VAL_LEN];
    long fills;
    long total_qty;
    double notional;
    long maker_qty;
    long taker_qty;
    int used;
} symbol_tally_t;

static symbol_tally_t g_tallies[MAX_SYMBOLS];

static symbol_tally_t *get_tally(const char *symbol) {
    for (int i = 0; i < MAX_SYMBOLS; i++) {
        if (g_tallies[i].used && strcmp(g_tallies[i].symbol, symbol) == 0) {
            return &g_tallies[i];
        }
    }
    for (int i = 0; i < MAX_SYMBOLS; i++) {
        if (!g_tallies[i].used) {
            g_tallies[i].used = 1;
            snprintf(g_tallies[i].symbol, sizeof(g_tallies[i].symbol), "%s", symbol);
            return &g_tallies[i];
        }
    }
    return NULL; /* table full: MAX_SYMBOLS comfortably covers this demo */
}

static double vwap(const symbol_tally_t *tally) {
    return tally->total_qty ? tally->notional / (double)tally->total_qty : 0.0;
}

static void print_summary(void) {
    long total_fills = 0;
    for (int i = 0; i < MAX_SYMBOLS; i++) {
        total_fills += g_tallies[i].used ? g_tallies[i].fills : 0;
    }
    printf("\nFill summary: %ld fill(s)\n", total_fills);
    for (int i = 0; i < MAX_SYMBOLS; i++) {
        if (g_tallies[i].used) {
            printf("  %-8s %ld fill(s), %ld qty, VWAP %.4f (maker %ld / taker %ld)\n", g_tallies[i].symbol,
                   g_tallies[i].fills, g_tallies[i].total_qty, vwap(&g_tallies[i]), g_tallies[i].maker_qty,
                   g_tallies[i].taker_qty);
        }
    }
}

/* ------------------------------------------------------------------ */
/* Line-level socket helpers (identical pattern to ralf_subscriber.c). */

static int send_line(int fd, const char *line) {
    size_t len = strlen(line);
    if (write(fd, line, len) != (ssize_t)len) {
        return -1;
    }
    if (write(fd, "\n", 1) != 1) {
        return -1;
    }
    return 0;
}

/* Returns 0 on a complete line, -1 on disconnect/error, -2 if interrupted
 * by SIGINT (see g_running).
 *
 * Waits in poll() with a short timeout instead of blocking in read(), so
 * g_running is re-checked at least every POLL_TIMEOUT_MS. A SIGINT that
 * arrives while the client is busy (printing, parsing) rather than waiting
 * in a system call interrupts nothing; with a plain blocking read() that
 * Ctrl-C would be lost until the next message happened to arrive.
 */
static int recv_line(int fd, char *buf, size_t cap) {
    size_t n = 0;
    while (n + 1 < cap) {
        struct pollfd pfd = {.fd = fd, .events = POLLIN};
        int ready = poll(&pfd, 1, POLL_TIMEOUT_MS);
        if (!g_running) {
            return -2;
        }
        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (ready == 0) {
            continue; /* timeout: loop round to re-check g_running */
        }
        char c;
        ssize_t r = read(fd, &c, 1);
        if (r < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (r == 0) {
            return -1; /* peer closed */
        }
        if (c == '\n') {
            break;
        }
        buf[n++] = c;
    }
    buf[n] = '\0';
    return 0;
}

static int connect_gateway(const char *host, int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        return -1;
    }

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

/* ------------------------------------------------------------------ */

static void handle_message(const dc_message_t *msg) {
    if (strcmp(msg->msg_type, "DC_FILL") == 0) {
        const char *seq = dc_get_field(msg, "SEQ");
        const char *symbol = dc_get_field(msg, "SYMBOL");
        const char *qty_str = dc_get_field(msg, "FILL_QTY");
        const char *px_str = dc_get_field(msg, "FILL_PRICE");
        const char *liquidity = dc_get_field(msg, "LIQUIDITY");
        const char *order_id = dc_get_field(msg, "ORDER_ID");
        symbol = symbol ? symbol : "";
        check_sequence(seq);

        symbol_tally_t *tally = get_tally(symbol);
        char *qty_end = NULL;
        char *px_end = NULL;
        long qty = qty_str ? strtol(qty_str, &qty_end, 10) : 0;
        double px = px_str ? strtod(px_str, &px_end) : 0.0;
        if (!qty_str || !px_str || qty_end == qty_str || *qty_end != '\0' || px_end == px_str ||
            *px_end != '\0') {
            fprintf(stderr, "!! malformed DC_FILL for %s, not tallied\n", symbol);
        } else if (tally) {
            tally->fills++;
            tally->total_qty += qty;
            tally->notional += (double)qty * px;
            if (liquidity && strcmp(liquidity, "MAKER") == 0) {
                tally->maker_qty += qty;
            } else if (liquidity && strcmp(liquidity, "TAKER") == 0) {
                tally->taker_qty += qty;
            }
        }
        printf("FILL  %-8s %6s @ %10s %-5s order=%s seq=%s  [%s: %ld qty, VWAP %.4f]\n", symbol,
               qty_str ? qty_str : "?", px_str ? px_str : "?", liquidity ? liquidity : "?",
               order_id ? order_id : "?", seq ? seq : "?", symbol, tally ? tally->total_qty : 0L,
               tally ? vwap(tally) : 0.0);
    } else if (strcmp(msg->msg_type, "HB") == 0) {
        printf("HB    (gateway heartbeat)\n");
    } else if (strcmp(msg->msg_type, "PONG") == 0) {
        printf("PONG  (liveness reply)\n");
    } else if (strcmp(msg->msg_type, "EXIT") == 0) {
        const char *reason = dc_get_field(msg, "REASON");
        fprintf(stderr, "EXIT  gateway is closing the session (reason=%s)\n", reason ? reason : "?");
    } else if (strcmp(msg->msg_type, "ERR") == 0) {
        /* ERR|CODE=..|DETAIL=.. -- the same shape in every line gateway. A
         * terminal code (SLOW_CLIENT, an oversized line) is followed by the
         * gateway closing the connection.
         */
        const char *code = dc_get_field(msg, "CODE");
        const char *detail = dc_get_field(msg, "DETAIL");
        fprintf(stderr, "ERR   %s: %s\n", code ? code : "?", detail ? detail : "");
    } else {
        printf("%s (unhandled, %d field(s))\n", msg->msg_type, msg->field_count);
    }
}

int main(int argc, char **argv) {
    const char *host = "127.0.0.1";
    int port = 5590;
    const char *gateway_id = "TRADER01";

    if (argc > 1) {
        host = argv[1];
    }
    if (argc > 2) {
        port = atoi(argv[2]);
    }
    if (argc > 3) {
        gateway_id = argv[3];
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handle_sigint;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0; /* no SA_RESTART: wake the poll() in recv_line() at once */
    sigaction(SIGINT, &sa, NULL);

    int fd = connect_gateway(host, port);
    if (fd < 0) {
        perror("connect_gateway");
        return 1;
    }

    char hello[256];
    snprintf(hello, sizeof(hello), "HELLO|CLIENT=ext-c-01|PROTO=DC1|ID=%s", gateway_id);
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

    dc_message_t welcome;
    if (dc_parse_line(line, &welcome) != 0) {
        fprintf(stderr, "failed to parse WELCOME\n");
        close(fd);
        return 1;
    }
    if (strcmp(welcome.msg_type, "WELCOME") != 0) {
        /* AUTH_REQUIRED (missing CLIENT/ID or PROTO not DC1): the gateway
         * closes the session, so there is nothing to receive. */
        const char *code = dc_get_field(&welcome, "CODE");
        const char *detail = dc_get_field(&welcome, "DETAIL");
        fprintf(stderr, "handshake refused: %s %s: %s\n", welcome.msg_type, code ? code : "",
                detail ? detail : "");
        close(fd);
        return 1;
    }
    printf("WELCOME type=%s GW=%s ID=%s HBINT=%s\n", welcome.msg_type,
           dc_get_field(&welcome, "GW") ? dc_get_field(&welcome, "GW") : "?",
           dc_get_field(&welcome, "ID") ? dc_get_field(&welcome, "ID") : "?",
           dc_get_field(&welcome, "HBINT") ? dc_get_field(&welcome, "HBINT") : "?");
    printf("Receiving fills for ID=%s\n", gateway_id);

    int status = 0;
    for (;;) {
        int rc = recv_line(fd, line, sizeof(line));
        if (rc == -2) {
            printf("\ninterrupted, closing connection\n");
            /* EXIT works in both directions: the gateway flushes, then closes. */
            send_line(fd, "EXIT");
            break;
        }
        if (rc != 0) {
            fprintf(stderr, "connection lost\n");
            status = 1;
            break;
        }
        dc_message_t msg;
        if (dc_parse_line(line, &msg) != 0) {
            fprintf(stderr, "parse error: %s\n", line);
            continue;
        }
        handle_message(&msg);
        if (strcmp(msg.msg_type, "EXIT") == 0) {
            status = 1; /* the gateway ended the session; it closes next */
            break;
        }
    }

    print_summary();
    close(fd);
    return status;
}
