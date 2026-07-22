/* Full working RALF subscriber example (C).
 *
 * Goes beyond a single trivial subscription: subscribes to every channel
 * the given role is actually entitled to (protocol reference §7) in one
 * combined SUB, then puts the received EXEC/EOD data to use -- a running
 * per-symbol executed-volume tally that de-duplicates EXEC lines by
 * EXEC_ID (an AUDIT client subscribed to more than one channel receives
 * the *same* trade once per channel, by design, see §6), plus a
 * per-channel sequence-gap check and a clean SIGINT shutdown that prints
 * the final tally before exiting.
 *
 * See docs/user-guide/930-app-ralf-protocol.md for the normative wire
 * contract this client follows.
 */

#define _POSIX_C_SOURCE 200809L

#include "ralf_parser.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#define MAX_CHANNELS 3   /* CLEARING, DROP_COPY, AUDIT */
#define MAX_SYMBOLS 16   /* bounded per-symbol tally table */
#define MAX_EXEC_IDS 256 /* bounded de-dup window for this demo session */

/* SIGINT sets this instead of taking the default terminate action, so the
 * blocking read() in recv_line() can be interrupted cleanly (see the
 * sigaction() call in main(), which deliberately omits SA_RESTART) and
 * the client can print its final tally and close the socket instead of
 * being killed mid-syscall.
 */
static volatile sig_atomic_t g_running = 1;

static void handle_sigint(int signum) {
    (void)signum;
    g_running = 0;
}

/* ------------------------------------------------------------------ */
/* Role -> entitled channel list (protocol reference §7). AUDIT is the
 * only role entitled to more than its own name.
 * ------------------------------------------------------------------ */

static const char *entitled_channels(const char *role) {
    if (strcmp(role, "AUDIT") == 0) {
        return "CLEARING,DROP_COPY,AUDIT";
    }
    return role; /* CLEARING -> "CLEARING", DROP_COPY -> "DROP_COPY" */
}

/* ------------------------------------------------------------------ */
/* Per-channel sequence-gap detection. Unlike CALF, RALF sequences are
 * per-*channel*, not per-(channel,symbol) -- protocol reference §8.
 * ------------------------------------------------------------------ */

typedef struct {
    char channel[RALF_MAX_KEY_LEN];
    long seq;
} channel_seq_t;

static channel_seq_t g_channel_seq[MAX_CHANNELS];
static int g_channel_seq_count = 0;

static void check_sequence(const char *channel, const char *seq_str) {
    if (!channel[0] || !seq_str) {
        return;
    }
    long seq = strtol(seq_str, NULL, 10);

    for (int i = 0; i < g_channel_seq_count; i++) {
        if (strcmp(g_channel_seq[i].channel, channel) == 0) {
            if (seq != g_channel_seq[i].seq + 1) {
                fprintf(stderr, "!! sequence gap on channel %s: expected %ld, got %ld\n", channel,
                        g_channel_seq[i].seq + 1, seq);
            }
            g_channel_seq[i].seq = seq;
            return;
        }
    }
    if (g_channel_seq_count < MAX_CHANNELS) {
        channel_seq_t *entry = &g_channel_seq[g_channel_seq_count++];
        snprintf(entry->channel, sizeof(entry->channel), "%s", channel);
        entry->seq = seq;
    }
}

/* ------------------------------------------------------------------ */
/* Per-symbol executed-volume tally, de-duplicated by EXEC_ID.
 *
 * A single executed trade is delivered once *per subscribed channel*: a
 * role subscribed to more than one channel (only AUDIT can be) sees the
 * same EXEC_ID repeated, once per channel. Counting raw lines would
 * overstate volume by up to 3x for an AUDIT client subscribed to
 * everything, so this tracks seen EXEC_IDs and only tallies each once.
 * ------------------------------------------------------------------ */

typedef struct {
    char symbol[RALF_MAX_VAL_LEN];
    long unique_trades;
    long total_qty;
    int used;
} symbol_tally_t;

static symbol_tally_t g_tallies[MAX_SYMBOLS];

static char g_seen_exec_ids[MAX_EXEC_IDS][RALF_MAX_VAL_LEN];
static int g_seen_exec_id_count = 0;

/* Returns 1 if exec_id was newly recorded, 0 if it was already seen (or
 * the de-dup table is full, in which case it is conservatively treated
 * as a duplicate rather than risk double-counting).
 */
static int record_exec_id(const char *exec_id) {
    for (int i = 0; i < g_seen_exec_id_count; i++) {
        if (strcmp(g_seen_exec_ids[i], exec_id) == 0) {
            return 0;
        }
    }
    if (g_seen_exec_id_count >= MAX_EXEC_IDS) {
        return 0;
    }
    snprintf(g_seen_exec_ids[g_seen_exec_id_count], sizeof(g_seen_exec_ids[0]), "%s", exec_id);
    g_seen_exec_id_count++;
    return 1;
}

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

static void print_summary(void) {
    printf("\nExecution summary: %d unique trade(s)\n", g_seen_exec_id_count);
    for (int i = 0; i < MAX_SYMBOLS; i++) {
        if (g_tallies[i].used) {
            printf("  %-8s %ld unique trade(s), %ld total qty\n", g_tallies[i].symbol, g_tallies[i].unique_trades,
                   g_tallies[i].total_qty);
        }
    }
}

/* ------------------------------------------------------------------ */
/* Line-level socket helpers (identical pattern to calf_subscriber.c). */

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
 * by SIGINT (see g_running) with no line pending.
 */
static int recv_line(int fd, char *buf, size_t cap) {
    size_t n = 0;
    while (n + 1 < cap) {
        char c;
        ssize_t r = read(fd, &c, 1);
        if (r < 0) {
            if (errno == EINTR) {
                if (!g_running) {
                    return -2;
                }
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

static void handle_message(const ralf_message_t *msg) {
    const char *channel = ralf_get_field(msg, "CH");
    const char *symbol = ralf_get_field(msg, "SYM");
    channel = channel ? channel : "";
    symbol = symbol ? symbol : "";
    check_sequence(channel, ralf_get_field(msg, "SEQ"));

    if (strcmp(msg->msg_type, "SNAP") == 0) {
        printf("SNAP  CH=%s SYM=%s SEQ=%s\n", channel, symbol, ralf_get_field(msg, "SEQ"));
    } else if (strcmp(msg->msg_type, "EXEC") == 0) {
        const char *exec_id = ralf_get_field(msg, "EXEC_ID");
        const char *qty_str = ralf_get_field(msg, "QTY");
        const char *px = ralf_get_field(msg, "PX");
        const char *side = ralf_get_field(msg, "SIDE");
        int is_new = exec_id && record_exec_id(exec_id);
        if (is_new) {
            symbol_tally_t *tally = get_tally(symbol);
            if (tally) {
                tally->unique_trades++;
                tally->total_qty += qty_str ? strtol(qty_str, NULL, 10) : 0;
            }
        }
        printf("EXEC  %-8s %6s @ %10s %-4s ch=%s%s\n", symbol, qty_str ? qty_str : "?", px ? px : "?",
               side ? side : "?", channel, is_new ? "" : "  (duplicate copy of an already-counted trade)");
    } else if (strcmp(msg->msg_type, "EOD") == 0) {
        symbol_tally_t *tally = get_tally(symbol);
        const char *trade_count = ralf_get_field(msg, "TRADE_COUNT");
        printf("EOD   %-8s gateway TRADE_COUNT=%s (client tallied %ld unique trade(s), %ld total qty)\n", symbol,
               trade_count ? trade_count : "?", tally ? tally->unique_trades : 0, tally ? tally->total_qty : 0);
    } else if (strcmp(msg->msg_type, "HB") == 0) {
        printf("HB    (gateway heartbeat)\n");
    } else if (strcmp(msg->msg_type, "PONG") == 0) {
        printf("PONG  (liveness reply)\n");
    } else if (strcmp(msg->msg_type, "EXIT") == 0) {
        const char *reason = ralf_get_field(msg, "REASON");
        fprintf(stderr, "EXIT  gateway is closing the session (reason=%s)\n", reason ? reason : "?");
    } else if (strcmp(msg->msg_type, "ERR") == 0) {
        /* RALF's error field is DETAIL, not MSG (CALF's error field name)
         * -- see protocol reference §10.
         */
        const char *code = ralf_get_field(msg, "CODE");
        const char *detail = ralf_get_field(msg, "DETAIL");
        fprintf(stderr, "ERR   %s: %s\n", code ? code : "?", detail ? detail : "");
    } else {
        printf("%s (unhandled, %d field(s))\n", msg->msg_type, msg->field_count);
    }
}

int main(int argc, char **argv) {
    const char *host = "127.0.0.1";
    int port = 5580;
    const char *role = "CLEARING";

    if (argc > 1) {
        host = argv[1];
    }
    if (argc > 2) {
        port = atoi(argv[2]);
    }
    if (argc > 3) {
        role = argv[3];
    }
    if (strcmp(role, "CLEARING") != 0 && strcmp(role, "DROP_COPY") != 0 && strcmp(role, "AUDIT") != 0) {
        fprintf(stderr, "unknown role %s (expected CLEARING, DROP_COPY, or AUDIT)\n", role);
        return 1;
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handle_sigint;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0; /* no SA_RESTART: interrupt the blocking read() in recv_line() */
    sigaction(SIGINT, &sa, NULL);

    int fd = connect_gateway(host, port);
    if (fd < 0) {
        perror("connect_gateway");
        return 1;
    }

    char hello[256];
    snprintf(hello, sizeof(hello), "HELLO|CLIENT=ext-c-01|PROTO=RALF1|ROLE=%s|LASTSEQ=0", role);
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
    printf("WELCOME type=%s GW=%s ROLE=%s\n", welcome.msg_type,
           ralf_get_field(&welcome, "GW") ? ralf_get_field(&welcome, "GW") : "?",
           ralf_get_field(&welcome, "ROLE") ? ralf_get_field(&welcome, "ROLE") : "?");

    /* One combined SUB covering every channel the role is entitled to --
     * CH accepts a comma-separated list, so this is one round trip and
     * one SNAP, not one per channel. No ROLE field on SUB: the protocol
     * only defines CH and SYM here (role was already established by
     * HELLO); a gateway would just ignore an extra field, but a "best
     * practice" client should not send fields the wire contract doesn't
     * define.
     */
    char sub_line[128];
    snprintf(sub_line, sizeof(sub_line), "SUB|CH=%s|SYM=*", entitled_channels(role));
    if (send_line(fd, sub_line) != 0) {
        perror("send SUB");
        close(fd);
        return 1;
    }
    printf("Subscribed %s as role=%s\n", sub_line, role);

    for (;;) {
        int rc = recv_line(fd, line, sizeof(line));
        if (rc == -2) {
            printf("\ninterrupted, closing connection\n");
            break;
        }
        if (rc != 0) {
            break; /* disconnected */
        }
        ralf_message_t msg;
        if (ralf_parse_line(line, &msg) != 0) {
            fprintf(stderr, "parse error: %s\n", line);
            continue;
        }
        handle_message(&msg);
    }

    print_summary();
    close(fd);
    return 0;
}
