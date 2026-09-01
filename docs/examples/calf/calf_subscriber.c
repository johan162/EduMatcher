/* Full working CALF subscriber example (C).
 *
 * Goes beyond a single trivial subscription: top-of-book (TOP), trade
 * prints (TRADE), session/symbol state (STATE, including the SYM=*
 * wildcard), and a Level 2 depth-of-book ladder (DEPTH) -- one client,
 * several channels, with a small top-of-book cache and a formatted depth
 * ladder rather than raw fields dumped to the terminal. Also demonstrates
 * per-(CH,SYM) sequence-gap detection *and repair* via RESUME, and a clean
 * SIGINT shutdown.
 *
 * Prices are printed exactly as they arrived on the wire, so this client
 * needs no WELCOME|REF= handling: reformatting a decimal is what creates
 * the opportunity to reformat it wrongly. A client that parses prices into
 * numbers and renders them itself does need REF -- tick_decimals is
 * per-symbol, and assuming 2 is right only for the instruments that happen
 * to quote that way. calf_subscriber.py shows that path.
 *
 * See docs/user-guide/920-app-calf-protocol.md for the normative wire
 * contract this client follows.
 */

#define _POSIX_C_SOURCE 200809L

#include "calf_parser.h"
#include "calf_recovery.h"
#include "edumatcher_trade.h"

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

#define MAX_SYMBOLS 16 /* bounded top-of-book cache */
#define FIELD_LEN 32

/* SIGINT sets this instead of taking the default terminate action, so the
 * blocking read() in recv_line() can be interrupted cleanly (see the
 * sigaction() call in main(), which deliberately omits SA_RESTART) and the
 * client can close its socket and exit normally instead of being killed
 * mid-syscall.
 */
static volatile sig_atomic_t g_running = 1;

static void handle_sigint(int signum) {
    (void)signum;
    g_running = 0;
}

/* ------------------------------------------------------------------ */
/* Sequence tracking lives in calf_recovery.c, which owns the three rules
 * that make gap handling correct (replay overlaps live traffic; a SNAP
 * re-baselines; a sequence only moves backward across connections). This
 * file keeps the I/O and the display.
 * ------------------------------------------------------------------ */

static calf_recovery_t g_recovery;

/* ------------------------------------------------------------------ */
/* Top-of-book cache: MD updates omit sides that did not change, so they
 * must be merged into persistent per-symbol state rather than printed in
 * isolation, or an unchanged side would show up blank.
 * ------------------------------------------------------------------ */

typedef struct {
    char symbol[CALF_MAX_VAL_LEN];
    char bid[FIELD_LEN];
    char bid_sz[FIELD_LEN];
    char ask[FIELD_LEN];
    char ask_sz[FIELD_LEN];
    char last[FIELD_LEN];
    int used;
} top_of_book_t;

static top_of_book_t g_books[MAX_SYMBOLS];

static void set_field(char *dst, size_t cap, const calf_message_t *msg, const char *key) {
    const char *value = calf_get_field(msg, key);
    if (value) {
        snprintf(dst, cap, "%s", value);
    }
}

static top_of_book_t *get_book(const char *symbol) {
    for (int i = 0; i < MAX_SYMBOLS; i++) {
        if (g_books[i].used && strcmp(g_books[i].symbol, symbol) == 0) {
            return &g_books[i];
        }
    }
    for (int i = 0; i < MAX_SYMBOLS; i++) {
        if (!g_books[i].used) {
            g_books[i].used = 1;
            snprintf(g_books[i].symbol, sizeof(g_books[i].symbol), "%s", symbol);
            snprintf(g_books[i].bid, sizeof(g_books[i].bid), "-");
            snprintf(g_books[i].bid_sz, sizeof(g_books[i].bid_sz), "-");
            snprintf(g_books[i].ask, sizeof(g_books[i].ask), "-");
            snprintf(g_books[i].ask_sz, sizeof(g_books[i].ask_sz), "-");
            snprintf(g_books[i].last, sizeof(g_books[i].last), "-");
            return &g_books[i];
        }
    }
    return NULL; /* table full: MAX_SYMBOLS comfortably covers this demo */
}

static void print_top(const top_of_book_t *book) {
    printf("TOP   %-8s bid %10s x%-6s ask %10s x%-6s last %s\n", book->symbol, book->bid, book->bid_sz, book->ask,
           book->ask_sz, book->last);
}

/* ------------------------------------------------------------------ */
/* DEPTH ladder rendering: levels are encoded "PRICE:QTY:COUNT,..." -- see
 * the "Level encoding grammar" in the protocol reference. `line` is
 * modified in place (strtok_r), matching calf_parse_line()'s convention.
 * ------------------------------------------------------------------ */

static void print_depth_side(const char *label, char *levels) {
    if (!levels || !*levels) {
        printf("        %s: (none)\n", label);
        return;
    }
    printf("        %s:\n", label);
    /* Two independent saveptrs: the outer split (by ',') and the inner
     * split of each level (by ':') must not share one, or the inner
     * strtok_r() calls clobber the outer loop's resume position and
     * silently truncate iteration after the first level.
     */
    char *outer_save = NULL;
    for (char *entry = strtok_r(levels, ",", &outer_save); entry != NULL;
         entry = strtok_r(NULL, ",", &outer_save)) {
        char *inner_save = NULL;
        char *price = strtok_r(entry, ":", &inner_save);
        char *qty = price ? strtok_r(NULL, ":", &inner_save) : NULL;
        char *count = qty ? strtok_r(NULL, ":", &inner_save) : NULL;
        if (price && qty && count) {
            printf("          %10s x%-8s (%s orders)\n", price, qty, count);
        }
    }
}

/* ------------------------------------------------------------------ */
/* Line-level socket helpers. */

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

/* Exact-token membership test for a comma-separated list, e.g. checking
 * whether "DEPTH" is one of the entries in CH_SUPPORTED=TOP,TRADE,DEPTH
 * -- a plain strstr() would also (wrongly) match a hypothetical channel
 * name that merely contains "DEPTH" as a substring.
 */
static int csv_contains(const char *csv, const char *needle) {
    if (!csv) {
        return 0;
    }
    size_t needle_len = strlen(needle);
    const char *p = csv;
    while (*p) {
        const char *comma = strchr(p, ',');
        size_t token_len = comma ? (size_t)(comma - p) : strlen(p);
        if (token_len == needle_len && strncmp(p, needle, needle_len) == 0) {
            return 1;
        }
        if (!comma) {
            break;
        }
        p = comma + 1;
    }
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

static void handle_message(int fd, const calf_message_t *msg) {
    const char *channel = calf_get_field(msg, "CH");
    const char *symbol = calf_get_field(msg, "SYM");
    channel = channel ? channel : "";
    symbol = symbol ? symbol : "";

    /* A replayed duplicate is dropped here, before it can be applied a
     * second time; a detected gap is answered on the spot. */
    const char *seq_str = calf_get_field(msg, "SEQ");
    long seq = seq_str ? strtol(seq_str, NULL, 10) : 0;
    calf_gap_t gap;
    calf_action_t action =
        calf_recovery_observe(&g_recovery, msg->msg_type, channel, symbol, seq, &gap);

    if (action == CALF_DROP) {
        return;
    }
    if (action == CALF_RESUME) {
        char line[CALF_RESUME_LINE_LEN];
        fprintf(stderr, "!! sequence gap on (%s,%s): %ld..%ld missing -- resuming\n",
                gap.channel, gap.symbol, gap.first_seq, gap.last_seq);
        if (calf_recovery_build_resume(line, sizeof(line), &gap) > 0 &&
            send_line(fd, line) != 0) {
            perror("send RESUME");
        }
    } else if (action == CALF_GAP_UNREPAIRABLE) {
        fprintf(stderr, "!! gap on (%s,%s): %ld..%ld missing and unrecoverable\n",
                gap.channel, gap.symbol, gap.first_seq, gap.last_seq);
    }

    /* A SNAP on TRADE or AUCTION carries an envelope and no payload -- an
     * older gateway sends one after REPLAY_MISS. Decoded by CH like any
     * other line it reads as a print of zero shares at zero price, so
     * drop it rather than show a trade that never happened. */
    if (strcmp(msg->msg_type, "SNAP") == 0 && channel[0] && !calf_channel_has_snapshot(channel)) {
        return;
    }

    if (strcmp(channel, "TOP") == 0 && (strcmp(msg->msg_type, "SNAP") == 0 || strcmp(msg->msg_type, "MD") == 0)) {
        top_of_book_t *book = get_book(symbol);
        if (book) {
            set_field(book->bid, sizeof(book->bid), msg, "BID");
            set_field(book->bid_sz, sizeof(book->bid_sz), msg, "BIDSZ");
            set_field(book->ask, sizeof(book->ask), msg, "ASK");
            set_field(book->ask_sz, sizeof(book->ask_sz), msg, "ASKSZ");
            set_field(book->last, sizeof(book->last), msg, "LAST");
            print_top(book);
        }
    } else if (strcmp(msg->msg_type, EDU_TRADE_EXECUTED_CALF_MSGTYPE) == 0) {
        /* Generated binding, from spec/messages/trade.yaml. Every other
         * handler in this file re-derives its field names as string literals
         * and converts each value by hand -- which is why a field rename on
         * the publisher side never reaches a C client. Here the field names,
         * their types and their constraints all come from the specification,
         * so a rename is a compile error rather than a silent "?" on screen.
         *
         * Note the two-step: _parse coerces, _validate enforces the declared
         * rules (price > 0, quantity > 0, SIDE one of BUY/SELL/AUCTION). A
         * client that would rather display a questionable print than drop it
         * can simply skip the second call -- see docs/developer/06-msgen.md. */
        edu_trade_executed_calf_t trade;
        char err[128];
        int rc = edu_trade_executed_calf_parse(msg, &trade);
        if (rc != EDU_MSG_OK) {
            printf("TRADE %-8s <unparseable: %s>\n", symbol, edu_msg_strerror(rc));
        } else if (edu_trade_executed_calf_validate(&trade, err, sizeof(err)) != EDU_MSG_OK) {
            printf("TRADE %-8s <invalid: %s>\n", symbol, err);
        } else {
            /* Quantity and side are printed from the struct: an integer and an
             * enum have exact representations, so nothing can be lost.
             *
             * PX is still printed as the raw wire string, deliberately. The
             * struct does hold it as a double, and using that would mean
             * choosing a decimal count to render it with -- which is the
             * per-symbol REF= problem this client avoids by design (see the
             * note at the top of this file). A typed binding removes the
             * guesswork about field *names* and *types*; it does not remove the
             * need to know an instrument's tick scale before reformatting its
             * price. calf_subscriber.py shows the path that does parse prices. */
            const char *px = calf_get_field(msg, "PX");
                 printf("TRADE %-8s %-16s %6lld @ %10s (%s)\n",
                   symbol,
                     trade.id,
                   (long long)trade.quantity,
                   px ? px : "?",
                   edu_trade_executed_aggressor_side_to_str(trade.aggressor_side));
        }
    } else if (strcmp(channel, "STATE") == 0 &&
               (strcmp(msg->msg_type, "SNAP") == 0 || strcmp(msg->msg_type, "STATE") == 0)) {
        const char *session = calf_get_field(msg, "SESSION");
        const char *prev = calf_get_field(msg, "PREV");
        const char *scope = strcmp(symbol, "*") == 0 ? "session" : symbol;
        if (prev) {
            printf("STATE %-8s -> %s (was %s)\n", scope, session ? session : "?", prev);
        } else {
            printf("STATE %-8s -> %s\n", scope, session ? session : "?");
        }
    } else if (strcmp(channel, "DEPTH") == 0 &&
               (strcmp(msg->msg_type, "SNAP") == 0 || strcmp(msg->msg_type, "DEPTH") == 0)) {
        const char *levels = calf_get_field(msg, "LEVELS");
        printf("DEPTH %s (levels=%s):\n", symbol, levels ? levels : "?");
        /* calf_get_field() returns pointers into msg's own storage, which
         * this call owns for the duration of handle_message() -- copy
         * before strtok_r() mutates it in print_depth_side().
         */
        char bids[CALF_MAX_VAL_LEN];
        char asks[CALF_MAX_VAL_LEN];
        set_field(bids, sizeof(bids), msg, "BIDS");
        set_field(asks, sizeof(asks), msg, "ASKS");
        print_depth_side("BIDS", bids[0] ? bids : NULL);
        print_depth_side("ASKS", asks[0] ? asks : NULL);
    } else if (strcmp(msg->msg_type, "HB") == 0) {
        printf("HB    (gateway heartbeat)\n");
    } else if (strcmp(msg->msg_type, "ERR") == 0) {
        const char *code = calf_get_field(msg, "CODE");
        const char *detail = calf_get_field(msg, "MSG");
        fprintf(stderr, "ERR   %s: %s\n", code ? code : "?", detail ? detail : "");
    } else {
        printf("%s (unhandled, %d field(s))\n", msg->msg_type, msg->field_count);
    }
}

int main(int argc, char **argv) {
    const char *host = "127.0.0.1";
    int port = 5570;
    const char *symbols = "AAPL";
    const char *index_id = NULL;

    if (argc > 1) {
        host = argv[1];
    }
    if (argc > 2) {
        port = atoi(argv[2]);
    }
    if (argc > 3) {
        symbols = argv[3];
    }
    if (argc > 4) {
        index_id = argv[4];
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handle_sigint;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0; /* no SA_RESTART: interrupt the blocking read() in recv_line() */
    sigaction(SIGINT, &sa, NULL);

    calf_recovery_init(&g_recovery);

    int fd = connect_gateway(host, port);
    if (fd < 0) {
        perror("connect_gateway");
        return 1;
    }
    /* Once per connection. This example does not reconnect, but a client
     * that does must call it after every connect so a restarted gateway's
     * renumbering is not mistaken for a stream of duplicates. */
    calf_recovery_new_connection(&g_recovery);

    if (send_line(fd, "HELLO|CLIENT=ext-c-01|PROTO=CALF1") != 0) {
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

    calf_message_t welcome;
    if (calf_parse_line(line, &welcome) != 0) {
        fprintf(stderr, "failed to parse WELCOME\n");
        close(fd);
        return 1;
    }
    const char *ch_supported = calf_get_field(&welcome, "CH_SUPPORTED");
    printf("WELCOME type=%s GW=%s CH_SUPPORTED=%s\n", welcome.msg_type,
           calf_get_field(&welcome, "GW") ? calf_get_field(&welcome, "GW") : "?", ch_supported ? ch_supported : "?");

    /* A gateway build that predates WELCOME|CH_SUPPORTED= omits the field
     * entirely; treat that as "DEPTH/INDEX unknown" rather than risk an
     * ERR|CODE=INVALID_CHANNEL by assuming support that may not be there.
     */
    int depth_supported = csv_contains(ch_supported, "DEPTH");
    int index_supported = csv_contains(ch_supported, "INDEX");

    char sub_line[512];
    snprintf(sub_line, sizeof(sub_line), "SUB|CH=TOP,TRADE,STATE%s|SYM=%s", depth_supported ? ",DEPTH" : "",
             symbols);
    if (send_line(fd, sub_line) != 0) {
        perror("send SUB");
        close(fd);
        return 1;
    }
    printf("Subscribed %s\n", sub_line);

    /* STATE|SYM=* is a *different* stream from the per-symbol STATE
     * subscription above: SYM=* only carries session-wide transitions,
     * while SYM=AAPL carries that symbol's own HALT/resume events.
     */
    if (send_line(fd, "SUB|CH=STATE|SYM=*") != 0) {
        perror("send SUB (STATE wildcard)");
        close(fd);
        return 1;
    }
    printf("Subscribed STATE|SYM=* (session-wide state)\n");

    /* INDEX lives in a separate id namespace from instrument symbols and
     * never accepts SYM=*, so it is always its own SUB call.
     */
    if (index_id && index_supported) {
        char index_sub[128];
        snprintf(index_sub, sizeof(index_sub), "SUB|CH=INDEX|SYM=%s", index_id);
        if (send_line(fd, index_sub) != 0) {
            perror("send SUB (INDEX)");
            close(fd);
            return 1;
        }
        printf("Subscribed %s\n", index_sub);
    } else if (index_id) {
        fprintf(stderr, "INDEX channel not advertised by this gateway build; skipping\n");
    }

    for (;;) {
        int rc = recv_line(fd, line, sizeof(line));
        if (rc == -2) {
            printf("\ninterrupted, closing connection\n");
            break;
        }
        if (rc != 0) {
            break; /* disconnected */
        }
        calf_message_t msg;
        if (calf_parse_line(line, &msg) != 0) {
            fprintf(stderr, "parse error: %s\n", line);
            continue;
        }
        handle_message(fd, &msg);
    }

    close(fd);
    return 0;
}
