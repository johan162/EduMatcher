/*
 * alf_client.c — interactive ALF client for pm-alf-gwy
 *
 * Mimics pm-alf-console over TCP: connects to the ALF gateway, sends a
 * HELLO/WELCOME handshake, then presents a readline REPL that accepts the
 * same ALF commands as the interactive console.
 *
 * Compile and run:
 *   make
 *   ./alf_client --host 127.0.0.1 --port 5565 --id TRADER01
 *
 * Features:
 *   - Tab-completion for commands and common fields
 *   - Command history (persisted to ~/.alf_client_history)
 *   - select()-based I/O multiplexing: events arrive while you type
 *   - Coloured event display (ANSI codes)
 *   - Position/P&L tracking updated on every FILL
 *   - Multi-line responses: SYMBOLS, ORDERS, QBOOT
 */

#define _POSIX_C_SOURCE 200809L
#define _GNU_SOURCE

#include "alf_parser.h"

/* stdio.h must appear before readline headers so that FILE is defined. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <readline/history.h>
#include <readline/readline.h>
#include <signal.h>
#include <stdarg.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

/* --------------------------------------------------------------------------
 * ANSI colour codes
 * -------------------------------------------------------------------------- */

static int use_color = 1;

#define ANSI(code) (use_color ? "\033[" code "m" : "")

#define COL_RESET   ANSI("0")
#define COL_GREEN   ANSI("32")
#define COL_YELLOW  ANSI("33")
#define COL_CYAN    ANSI("36")
#define COL_RED     ANSI("31")
#define COL_MAGENTA ANSI("35")
#define COL_DIM     ANSI("2")
#define COL_BOLD    ANSI("1")

/* --------------------------------------------------------------------------
 * Global state
 * -------------------------------------------------------------------------- */

#define MAX_SYMBOLS    256
#define MAX_POSITIONS   64
#define MAX_LINE_BUF  8192  /* receive buffer */

static int  g_sockfd   = -1;
static int  g_running  = 1;

static char g_gateway_id[64]    = "TRADER01";
static char g_prompt    [128]   = "[TRADER01]> ";
static char g_session_state[64] = "UNKNOWN";

/* Receive buffer for line framing */
static char g_recvbuf[MAX_LINE_BUF * 2];
static int  g_recvlen = 0;

/* Known symbols (for tab completion) */
static char  g_symbols[MAX_SYMBOLS][32];
static int   g_nsymbols = 0;

/* Position tracking */
typedef struct {
    char   symbol [32];
    int    net_qty;
    double avg_cost;
    double realized_pnl;
} Position;

static Position g_positions[MAX_POSITIONS];
static int      g_npositions = 0;

/* Multi-line response state */
typedef enum { COL_NONE, COL_SYMBOLS, COL_ORDERS, COL_QBOOT } CollectMode;
static CollectMode g_collecting = COL_NONE;
#define MAX_COLLECT_ROWS 512
static alf_message_t g_collect_rows[MAX_COLLECT_ROWS];
static int           g_collect_count = 0;
static char          g_collect_gw[64] = "";

/* Order cache (for symbol/side lookup on fills) */
typedef struct { char id[48]; char symbol[16]; char side[8]; char status[16]; } OrderEntry;
#define MAX_ORDERS 256
static OrderEntry g_orders[MAX_ORDERS];
static int        g_norders = 0;

/* --------------------------------------------------------------------------
 * Helpers
 * -------------------------------------------------------------------------- */

static const char *nowts(void)
{
    static char buf[32];
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm *tm = localtime(&ts.tv_sec);
    snprintf(buf, sizeof(buf), "%02d:%02d:%02d.%03ld",
             tm->tm_hour, tm->tm_min, tm->tm_sec, ts.tv_nsec / 1000000L);
    return buf;
}

/* Print an event line without corrupting the readline prompt. */
static void event_print(const char *fmt, ...)
{
    char msg[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof(msg), fmt, ap);
    va_end(ap);

    /* Save current readline state, print, redraw prompt. */
    char *saved = rl_copy_text(0, rl_end);
    rl_save_prompt();
    rl_message("");
    fprintf(stdout, "\r\033[K%s\n", msg);  /* CR + erase-line + event + newline */
    rl_restore_prompt();
    rl_replace_line(saved ? saved : "", 0);
    rl_redisplay();
    if (saved) free(saved);
    fflush(stdout);
}

/* Send a raw NUL-terminated string to the gateway. */
static int gwy_send(const char *line)
{
    size_t len = strlen(line);
    if (write(g_sockfd, line, len) != (ssize_t)len) {
        perror("write");
        return -1;
    }
    return 0;
}

/* Convenience wrapper: build and send one ALF line. */
static int gwy_send_kv(const char *msg_type, const char * const *kv)
{
    char buf[ALF_MAX_LINE_LEN];
    if (alf_build_line(buf, sizeof(buf), msg_type, kv) < 0) {
        fprintf(stderr, "alf_build_line overflow\n");
        return -1;
    }
    return gwy_send(buf);
}

/* --------------------------------------------------------------------------
 * Position tracking
 * -------------------------------------------------------------------------- */

static Position *find_or_create_position(const char *symbol)
{
    int i;
    for (i = 0; i < g_npositions; i++) {
        if (strcmp(g_positions[i].symbol, symbol) == 0)
            return &g_positions[i];
    }
    if (g_npositions >= MAX_POSITIONS) return NULL;
    Position *p = &g_positions[g_npositions++];
    snprintf(p->symbol, sizeof(p->symbol), "%s", symbol);
    p->net_qty     = 0;
    p->avg_cost    = 0.0;
    p->realized_pnl = 0.0;
    return p;
}

static void update_position(const char *symbol, const char *side, int fill_qty, double fill_price)
{
    Position *p = find_or_create_position(symbol);
    if (!p) return;

    int is_buy    = (strcmp(side, "BUY") == 0);
    int signed_qty = is_buy ? fill_qty : -fill_qty;
    int old_qty    = p->net_qty;
    int new_qty    = old_qty + signed_qty;

    /* Realize P&L when reducing or flipping */
    if (old_qty != 0 &&
        ((old_qty > 0 && signed_qty < 0) || (old_qty < 0 && signed_qty > 0))) {
        int close_qty = abs(signed_qty) < abs(old_qty) ? abs(signed_qty) : abs(old_qty);
        double pnl_per = (old_qty > 0)
            ? (fill_price - p->avg_cost)
            : (p->avg_cost - fill_price);
        p->realized_pnl += pnl_per * close_qty;
    }

    /* Update average cost */
    if (new_qty == 0) {
        p->avg_cost = 0.0;
    } else if ((old_qty >= 0 && signed_qty > 0) || (old_qty <= 0 && signed_qty < 0)) {
        double total = p->avg_cost * (double)abs(old_qty) + fill_price * (double)abs(signed_qty);
        p->avg_cost  = total / (double)abs(new_qty);
    } else if (abs(new_qty) > abs(old_qty)) {
        p->avg_cost = fill_price;
    }

    p->net_qty = new_qty;
}

/* --------------------------------------------------------------------------
 * Order cache
 * -------------------------------------------------------------------------- */

static OrderEntry *find_order(const char *id)
{
    int i;
    for (i = 0; i < g_norders; i++) {
        if (strcmp(g_orders[i].id, id) == 0) return &g_orders[i];
    }
    return NULL;
}

static void cache_order(const char *id, const char *symbol, const char *side, const char *status)
{
    OrderEntry *e = find_order(id);
    if (!e) {
        if (g_norders >= MAX_ORDERS) return;
        e = &g_orders[g_norders++];
        snprintf(e->id, sizeof(e->id), "%s", id);
    }
    if (symbol) snprintf(e->symbol, sizeof(e->symbol), "%s", symbol);
    if (side)   snprintf(e->side,   sizeof(e->side),   "%s", side);
    if (status) snprintf(e->status, sizeof(e->status), "%s", status);
}

/* --------------------------------------------------------------------------
 * Multi-line response rendering
 * -------------------------------------------------------------------------- */

static void flush_collected(void)
{
    int i;
    switch (g_collecting) {
    case COL_SYMBOLS:
        event_print("%sSymbols (%d)%s", COL_BOLD, g_collect_count, COL_RESET);
        event_print("  %-10s  TICK", "SYM");
        /* Update global symbol list for tab-completion */
        g_nsymbols = 0;
        for (i = 0; i < g_collect_count && i < MAX_COLLECT_ROWS; i++) {
            const char *sym  = alf_get_field(&g_collect_rows[i], "SYM");
            const char *tick = alf_get_field(&g_collect_rows[i], "TICK");
            if (!sym) continue;
            event_print("  %-10s  %s", sym, tick ? tick : "-");
            if (g_nsymbols < MAX_SYMBOLS)
                snprintf(g_symbols[g_nsymbols++], 32, "%s", sym);
        }
        break;

    case COL_ORDERS:
        event_print("%sOrders — %s%s", COL_BOLD, g_collect_gw, COL_RESET);
        event_print("  %-8s  %-6s %-5s %-11s %6s %6s %8s  %s",
                    "ID", "SYM", "SIDE", "TYPE", "QTY", "REM", "PRICE", "STATUS");
        event_print("  %s", "----------------------------------------------------------------------");
        for (i = 0; i < g_collect_count && i < MAX_COLLECT_ROWS; i++) {
            const alf_message_t *r = &g_collect_rows[i];
            const char *id  = alf_get_field(r, "ID");
            const char *sym = alf_get_field(r, "SYM");
            const char *sid = alf_get_field(r, "SIDE");
            const char *typ = alf_get_field(r, "TYPE");
            const char *qty = alf_get_field(r, "QTY");
            const char *rem = alf_get_field(r, "REMAINING");
            const char *prc = alf_get_field(r, "PRICE");
            const char *st  = alf_get_field(r, "STATUS");
            char short_id[9] = "?";
            if (id) snprintf(short_id, sizeof(short_id), "%s", id);
            event_print("  %-8s  %-6s %-5s %-11s %6s %6s %8s  %s",
                        short_id,
                        sym ? sym : "?",
                        sid ? sid : "?",
                        typ ? typ : "?",
                        qty ? qty : "?",
                        rem ? rem : "?",
                        prc ? prc : "-",
                        st  ? st  : "?");
            if (id && sym && sid)
                cache_order(id, sym, sid, st);
        }
        if (g_collect_count == 0)
            event_print("  (no resting orders)");
        break;

    case COL_QBOOT:
        event_print("%sQuote Bootstrap%s", COL_BOLD, COL_RESET);
        event_print("  %-20s %-6s %8s %8s %6s %6s  %s",
                    "QUOTE_ID", "SYM", "BID", "ASK", "B_QTY", "A_QTY", "STATUS");
        for (i = 0; i < g_collect_count && i < MAX_COLLECT_ROWS; i++) {
            const alf_message_t *r = &g_collect_rows[i];
            event_print("  %-20s %-6s %8s %8s %6s %6s  %s",
                        alf_get_field(r, "QUOTE_ID") ? alf_get_field(r, "QUOTE_ID") : "?",
                        alf_get_field(r, "SYM")      ? alf_get_field(r, "SYM")      : "?",
                        alf_get_field(r, "BID")      ? alf_get_field(r, "BID")      : "-",
                        alf_get_field(r, "ASK")      ? alf_get_field(r, "ASK")      : "-",
                        alf_get_field(r, "BID_QTY")  ? alf_get_field(r, "BID_QTY")  : "-",
                        alf_get_field(r, "ASK_QTY")  ? alf_get_field(r, "ASK_QTY")  : "-",
                        alf_get_field(r, "STATUS")   ? alf_get_field(r, "STATUS")   : "?");
        }
        if (g_collect_count == 0)
            event_print("  (no active quotes)");
        break;

    default:
        break;
    }

    g_collecting   = COL_NONE;
    g_collect_count = 0;
    g_collect_gw[0] = '\0';
}

/* --------------------------------------------------------------------------
 * Event handler
 * -------------------------------------------------------------------------- */

static void handle_event(const alf_message_t *msg)  /* NOLINT(readability-function-cognitive-complexity) */
{
    const char *t  = msg->msg_type;
    const char *ts = nowts();

    /* Heartbeat — silently discard */
    if (strcmp(t, "HB") == 0) return;

    if (strcmp(t, "PONG") == 0) {
        event_print("[%s] %sPONG%s  %s", ts, COL_DIM, COL_RESET,
                    alf_get_field(msg, "TS") ? alf_get_field(msg, "TS") : "");
        return;
    }

    if (strcmp(t, "SESSION") == 0) {
        const char *st   = alf_get_field(msg, "STATE");
        const char *prev = alf_get_field(msg, "PREV_STATE");
        if (st) snprintf(g_session_state, sizeof(g_session_state), "%s", st);
        event_print("[%s] %sSESSION%s  %s → %s",
                    ts, COL_YELLOW, COL_RESET,
                    prev ? prev : "?", st ? st : "?");
        return;
    }

    if (strcmp(t, "HALT") == 0) {
        event_print("[%s] %sHALT%s    %s  level=%s",
                    ts, COL_RED, COL_RESET,
                    alf_get_field(msg, "SYMBOL") ? alf_get_field(msg, "SYMBOL") : "?",
                    alf_get_field(msg, "LEVEL")  ? alf_get_field(msg, "LEVEL")  : "-");
        return;
    }

    if (strcmp(t, "RESUME") == 0) {
        event_print("[%s] %sRESUME%s  %s  mode=%s",
                    ts, COL_GREEN, COL_RESET,
                    alf_get_field(msg, "SYMBOL") ? alf_get_field(msg, "SYMBOL") : "?",
                    alf_get_field(msg, "MODE")   ? alf_get_field(msg, "MODE")   : "-");
        return;
    }

    if (strcmp(t, "TRADE") == 0) {
        event_print("[%s] %sTRADE%s   %s  %s %s @%s",
                    ts, COL_DIM, COL_RESET,
                    alf_get_field(msg, "SYMBOL") ? alf_get_field(msg, "SYMBOL") : "?",
                    alf_get_field(msg, "SIDE")   ? alf_get_field(msg, "SIDE")   : "?",
                    alf_get_field(msg, "QTY")    ? alf_get_field(msg, "QTY")    : "?",
                    alf_get_field(msg, "PRICE")  ? alf_get_field(msg, "PRICE")  : "?");
        return;
    }

    if (strcmp(t, "ERR") == 0) {
        event_print("[%s] %sERR%s  [%s]  %s",
                    ts, COL_RED, COL_RESET,
                    alf_get_field(msg, "CODE")   ? alf_get_field(msg, "CODE")   : "?",
                    alf_get_field(msg, "DETAIL") ? alf_get_field(msg, "DETAIL") : "");
        return;
    }

    if (strcmp(t, "ACK") == 0) {
        const char *oid      = alf_get_field(msg, "ORDER_ID");
        const char *accepted = alf_get_field(msg, "ACCEPTED");
        char short_id[9] = "?";
        if (oid) snprintf(short_id, sizeof(short_id), "%s", oid);
        if (accepted && strcmp(accepted, "TRUE") == 0) {
            event_print("[%s] %sACK%s      %s  order accepted", ts, COL_GREEN, COL_RESET, short_id);
            if (oid)
                cache_order(oid, alf_get_field(msg, "SYMBOL"),
                            alf_get_field(msg, "SIDE"), "NEW");
        } else {
            event_print("[%s] %sREJECTED%s %s  %s",
                        ts, COL_RED, COL_RESET, short_id,
                        alf_get_field(msg, "REASON") ? alf_get_field(msg, "REASON") : "");
        }
        return;
    }

    if (strcmp(t, "FILL") == 0) {
        const char *oid  = alf_get_field(msg, "ORDER_ID");
        const char *qty  = alf_get_field(msg, "FILL_QTY");
        const char *px   = alf_get_field(msg, "FILL_PRICE");
        const char *rem  = alf_get_field(msg, "REMAINING");
        const char *st   = alf_get_field(msg, "STATUS");
        char short_id[9] = "?";
        if (oid) snprintf(short_id, sizeof(short_id), "%s", oid);
        event_print("[%s] %sFILL%s     %s  qty=%s @%s  remaining=%s  [%s]",
                    ts, COL_CYAN, COL_RESET,
                    short_id,
                    qty ? qty : "?",
                    px  ? px  : "?",
                    rem ? rem : "?",
                    st  ? st  : "?");
        /* Update position */
        if (oid && qty && px) {
            OrderEntry *e = find_order(oid);
            const char *sym  = e ? e->symbol : alf_get_field(msg, "SYMBOL");
            const char *side = e ? e->side   : alf_get_field(msg, "SIDE");
            if (sym && side && *sym && *side)
                update_position(sym, side, atoi(qty), atof(px));
        }
        return;
    }

    if (strcmp(t, "AMENDED") == 0) {
        const char *oid = alf_get_field(msg, "ORDER_ID");
        char short_id[9] = "?";
        if (oid) snprintf(short_id, sizeof(short_id), "%s", oid);
        event_print("[%s] %sAMENDED%s  %s  price=%s qty=%s remaining=%s priority_reset=%s",
                    ts, COL_MAGENTA, COL_RESET, short_id,
                    alf_get_field(msg, "PRICE")          ? alf_get_field(msg, "PRICE")          : "-",
                    alf_get_field(msg, "QTY")            ? alf_get_field(msg, "QTY")            : "-",
                    alf_get_field(msg, "REMAINING")      ? alf_get_field(msg, "REMAINING")      : "-",
                    alf_get_field(msg, "PRIORITY_RESET") ? alf_get_field(msg, "PRIORITY_RESET") : "-");
        return;
    }

    if (strcmp(t, "CANCELLED") == 0) {
        const char *oid = alf_get_field(msg, "ORDER_ID");
        char short_id[9] = "?";
        if (oid) snprintf(short_id, sizeof(short_id), "%s", oid);
        event_print("[%s] %sCANCELLED%s %s", ts, COL_YELLOW, COL_RESET, short_id);
        return;
    }

    if (strcmp(t, "EXPIRED") == 0) {
        const char *oid = alf_get_field(msg, "ORDER_ID");
        char short_id[9] = "?";
        if (oid) snprintf(short_id, sizeof(short_id), "%s", oid);
        event_print("[%s] %sEXPIRED%s  %s", ts, COL_DIM, COL_RESET, short_id);
        return;
    }

    if (strcmp(t, "QUOTE_ACK") == 0) {
        const char *qid = alf_get_field(msg, "QUOTE_ID");
        const char *acc = alf_get_field(msg, "ACCEPTED");
        if (acc && strcmp(acc, "TRUE") == 0) {
            event_print("[%s] %sQUOTE ACK%s  %s  bid=%s ask=%s",
                        ts, COL_GREEN, COL_RESET,
                        qid ? qid : "?",
                        alf_get_field(msg, "BID_ID") ? alf_get_field(msg, "BID_ID") : "?",
                        alf_get_field(msg, "ASK_ID") ? alf_get_field(msg, "ASK_ID") : "?");
        } else {
            event_print("[%s] %sQUOTE REJ%s  %s  %s",
                        ts, COL_RED, COL_RESET,
                        qid ? qid : "?",
                        alf_get_field(msg, "REASON") ? alf_get_field(msg, "REASON") : "");
        }
        return;
    }

    if (strcmp(t, "QUOTE_STATUS") == 0) {
        event_print("[%s] %sQUOTE %s%s  %s  %s",
                    ts, COL_CYAN,
                    alf_get_field(msg, "STATUS") ? alf_get_field(msg, "STATUS") : "?",
                    COL_RESET,
                    alf_get_field(msg, "QUOTE_ID") ? alf_get_field(msg, "QUOTE_ID") : "?",
                    alf_get_field(msg, "REASON")   ? alf_get_field(msg, "REASON")   : "");
        return;
    }

    if (strcmp(t, "COMBO_ACK") == 0) {
        const char *cid = alf_get_field(msg, "COMBO_ID");
        const char *acc = alf_get_field(msg, "ACCEPTED");
        if (acc && strcmp(acc, "TRUE") == 0)
            event_print("[%s] %sCOMBO ACK%s  %s  combo accepted", ts, COL_GREEN, COL_RESET, cid ? cid : "?");
        else
            event_print("[%s] %sCOMBO REJ%s  %s  %s",
                        ts, COL_RED, COL_RESET,
                        cid ? cid : "?",
                        alf_get_field(msg, "REASON") ? alf_get_field(msg, "REASON") : "");
        return;
    }

    if (strcmp(t, "COMBO_STATUS") == 0) {
        event_print("[%s] COMBO %s  %s  %s",
                    ts,
                    alf_get_field(msg, "STATUS")   ? alf_get_field(msg, "STATUS")   : "?",
                    alf_get_field(msg, "COMBO_ID") ? alf_get_field(msg, "COMBO_ID") : "?",
                    alf_get_field(msg, "REASON")   ? alf_get_field(msg, "REASON")   : "");
        return;
    }

    if (strcmp(t, "OCO_ACK") == 0) {
        const char *oid = alf_get_field(msg, "OCO_ID");
        const char *acc = alf_get_field(msg, "ACCEPTED");
        if (acc && strcmp(acc, "TRUE") == 0)
            event_print("[%s] %sOCO ACK%s    %s  legs=%s/%s",
                        ts, COL_GREEN, COL_RESET,
                        oid ? oid : "?",
                        alf_get_field(msg, "LEG1_ID") ? alf_get_field(msg, "LEG1_ID") : "?",
                        alf_get_field(msg, "LEG2_ID") ? alf_get_field(msg, "LEG2_ID") : "?");
        else
            event_print("[%s] %sOCO REJ%s    %s  %s",
                        ts, COL_RED, COL_RESET,
                        oid ? oid : "?",
                        alf_get_field(msg, "REASON") ? alf_get_field(msg, "REASON") : "");
        return;
    }

    if (strcmp(t, "OCO_CANCELLED") == 0) {
        event_print("[%s] %sOCO CANCEL%s %s  sibling=%s  %s",
                    ts, COL_YELLOW, COL_RESET,
                    alf_get_field(msg, "OCO_ID")       ? alf_get_field(msg, "OCO_ID")       : "?",
                    alf_get_field(msg, "CANCELLED_ID") ? alf_get_field(msg, "CANCELLED_ID") : "?",
                    alf_get_field(msg, "REASON")       ? alf_get_field(msg, "REASON")       : "");
        return;
    }

    if (strcmp(t, "KILL_ACK") == 0) {
        const char *acc = alf_get_field(msg, "ACCEPTED");
        if (acc && strcmp(acc, "TRUE") == 0)
            event_print("[%s] %sKILL ACK%s  orders=%s  quotes=%s",
                        ts, COL_YELLOW, COL_RESET,
                        alf_get_field(msg, "ORDERS") ? alf_get_field(msg, "ORDERS") : "0",
                        alf_get_field(msg, "QUOTES") ? alf_get_field(msg, "QUOTES") : "0");
        else
            event_print("[%s] %sKILL REJ%s  %s",
                        ts, COL_RED, COL_RESET,
                        alf_get_field(msg, "REASON") ? alf_get_field(msg, "REASON") : "");
        return;
    }

    /* Unknown — show raw type */
    event_print("[%s] %s%s%s  (unhandled)", ts, COL_DIM, t, COL_RESET);
}

/* --------------------------------------------------------------------------
 * Gateway receive: read lines from socket, dispatch events
 * -------------------------------------------------------------------------- */

static void process_socket_data(void)
{
    /* Read available bytes into the buffer */
    ssize_t n = read(g_sockfd,
                     g_recvbuf + g_recvlen,
                     (size_t)(sizeof(g_recvbuf) - g_recvlen - 1));
    if (n <= 0) {
        event_print("%sGateway closed connection.%s", COL_RED, COL_RESET);
        g_running = 0;
        return;
    }
    g_recvlen += (int)n;
    g_recvbuf[g_recvlen] = '\0';

    /* Extract complete lines */
    char *start = g_recvbuf;
    char *nl;
    while ((nl = strchr(start, '\n')) != NULL) {
        *nl = '\0';

        char line_copy[ALF_MAX_LINE_LEN];
        snprintf(line_copy, sizeof(line_copy), "%s", start);

        alf_message_t msg;
        if (alf_parse_line(line_copy, &msg) != 0) {
            start = nl + 1;
            continue;
        }

        /* Multi-line accumulation */
        if (g_collecting != COL_NONE) {
            if (strcmp(msg.msg_type, "SYMBOL") == 0 && g_collecting == COL_SYMBOLS) {
                if (g_collect_count < MAX_COLLECT_ROWS)
                    g_collect_rows[g_collect_count++] = msg;
                start = nl + 1;
                continue;
            }
            if (strcmp(msg.msg_type, "ORDER") == 0 && g_collecting == COL_ORDERS) {
                if (g_collect_count < MAX_COLLECT_ROWS)
                    g_collect_rows[g_collect_count++] = msg;
                start = nl + 1;
                continue;
            }
            if (strcmp(msg.msg_type, "QUOTE") == 0 && g_collecting == COL_QBOOT) {
                if (g_collect_count < MAX_COLLECT_ROWS)
                    g_collect_rows[g_collect_count++] = msg;
                start = nl + 1;
                continue;
            }
            if (strcmp(msg.msg_type, "END") == 0) {
                flush_collected();
                start = nl + 1;
                continue;
            }
        }

        /* Start multi-line response */
        if (strcmp(msg.msg_type, "SYMBOLS") == 0) {
            g_collecting   = COL_SYMBOLS;
            g_collect_count = 0;
            start = nl + 1;
            continue;
        }
        if (strcmp(msg.msg_type, "ORDERS") == 0) {
            g_collecting   = COL_ORDERS;
            g_collect_count = 0;
            const char *gw = alf_get_field(&msg, "GW");
            snprintf(g_collect_gw, sizeof(g_collect_gw), "%s", gw ? gw : "");
            start = nl + 1;
            continue;
        }
        if (strcmp(msg.msg_type, "QBOOT") == 0) {
            g_collecting   = COL_QBOOT;
            g_collect_count = 0;
            start = nl + 1;
            continue;
        }

        handle_event(&msg);
        start = nl + 1;
    }

    /* Shift remaining partial line to front of buffer */
    int remaining = (int)(g_recvbuf + g_recvlen - start);
    if (remaining > 0 && start != g_recvbuf)
        memmove(g_recvbuf, start, (size_t)remaining);
    g_recvlen = remaining;
    g_recvbuf[g_recvlen] = '\0';
}

/* --------------------------------------------------------------------------
 * Tab completion
 * -------------------------------------------------------------------------- */

static const char *g_top_cmds[] = {
    "NEW", "AMEND", "CANCEL", "QUOTE", "QUOTE_CANCEL", "QBOOT",
    "KILL", "SYMBOLS", "ORDERS", "PING", "POS", "STATUS", "HELP", "EXIT", "QUIT",
    NULL
};

/* Returns a malloc'd copy of the n-th match for text, or NULL when done. */
static char *alf_completion_generator(const char *text, int state)
{
    static int    idx;
    static size_t text_len;

    if (!state) {
        idx      = 0;
        text_len = strlen(text);
    }

    const char *buf = rl_line_buffer;

    /* Count pipe separators to determine context */
    int n_pipes = 0;
    for (const char *p = buf; *p; p++)
        if (*p == '|') n_pipes++;

    if (n_pipes == 0) {
        /* Complete top-level command verb */
        while (g_top_cmds[idx]) {
            const char *cmd = g_top_cmds[idx++];
            if (strncasecmp(cmd, text, text_len) == 0)
                return strdup(cmd);
        }
        return NULL;
    }

    /* Determine command and whether we're completing a value (contains '=') */
    char cmd[32] = "";
    sscanf(buf, "%31[^|]", cmd);
    for (int i = 0; cmd[i]; i++) cmd[i] = (char)toupper((unsigned char)cmd[i]);

    int completing_value = (strchr(text, '=') != NULL);

    /* Value completion */
    if (completing_value) {
        const char *eq = strchr(text, '=');
        char key[64];
        size_t klen = (size_t)(eq - text);
        if (klen >= sizeof(key)) return NULL;
        strncpy(key, text, klen);
        key[klen] = '\0';
        for (int i = 0; key[i]; i++) key[i] = (char)toupper((unsigned char)key[i]);

        const char *partial = eq + 1;

        /* SYM= → gateway symbols */
        if (strcmp(key, "SYM") == 0) {
            while (idx < g_nsymbols) {
                const char *sym = g_symbols[idx++];
                if (strncasecmp(sym, partial, strlen(partial)) == 0) {
                    char *ret = malloc(strlen(sym) + 5);
                    if (ret) sprintf(ret, "SYM=%s", sym);
                    return ret;
                }
            }
            return NULL;
        }

        /* Enum values */
        static const char *side_vals[]  = {"BUY", "SELL", NULL};
        static const char *type_vals[]  = {"MARKET", "LIMIT", "STOP", "STOP_LIMIT",
                                           "FOK", "IOC", "ICEBERG", "TRAILING_STOP",
                                           "OCO", "COMBO", NULL};
        static const char *tif_vals[]   = {"DAY", "GTC", "ATO", "ATC", NULL};
        static const char *smp_vals[]   = {"NONE", "CANCEL_AGGRESSOR",
                                           "CANCEL_RESTING", "CANCEL_BOTH", NULL};

        const char **vals = NULL;
        if (strcmp(key, "SIDE") == 0)         vals = side_vals;
        else if (strcmp(key, "TYPE") == 0)    vals = type_vals;
        else if (strcmp(key, "TIF") == 0)     vals = tif_vals;
        else if (strcmp(key, "SMP") == 0)     vals = smp_vals;
        else if (strcmp(key, "COMBO_TYPE") == 0) {
            static const char *ct[] = {"AON", NULL};
            vals = ct;
        }

        if (vals) {
            while (vals[idx]) {
                const char *v = vals[idx++];
                if (strncasecmp(v, partial, strlen(partial)) == 0) {
                    char *ret = malloc(strlen(key) + strlen(v) + 2);
                    if (ret) sprintf(ret, "%s=%s", key, v);
                    return ret;
                }
            }
        }
        return NULL;
    }

    /* Field-name completion */
    static const char *new_fields[]    = {"SYM=", "SIDE=", "TYPE=", "QTY=", "PRICE=",
                                          "STOP=", "TRAIL=", "VISIBLE=", "TIF=", "SMP=", NULL};
    static const char *amend_fields[]  = {"ID=", "PRICE=", "QTY=", NULL};
    static const char *cancel_fields[] = {"ID=", "COMBO_ID=", "OCO_ID=", NULL};
    static const char *quote_fields[]  = {"SYM=", "BID=", "ASK=", "BID_QTY=",
                                          "ASK_QTY=", "TIF=", "QUOTE_ID=", NULL};
    static const char *sym_fields[]    = {"SYM=", NULL};

    const char **fields = NULL;
    if (strcmp(cmd, "NEW") == 0)          fields = new_fields;
    else if (strcmp(cmd, "AMEND") == 0)   fields = amend_fields;
    else if (strcmp(cmd, "CANCEL") == 0)  fields = cancel_fields;
    else if (strcmp(cmd, "QUOTE") == 0)   fields = quote_fields;
    else if (strcmp(cmd, "QUOTE_CANCEL") == 0 ||
             strcmp(cmd, "QBOOT") == 0 ||
             strcmp(cmd, "KILL") == 0)    fields = sym_fields;

    if (fields) {
        while (fields[idx]) {
            const char *f = fields[idx++];
            if (strncasecmp(f, text, text_len) == 0)
                return strdup(f);
        }
    }
    return NULL;
}

static char **alf_completion(const char *text, int start, int end)
{
    (void)start; (void)end;
    rl_attempted_completion_over = 1;
    return rl_completion_matches(text, alf_completion_generator);
}

/* --------------------------------------------------------------------------
 * POS and STATUS built-in commands
 * -------------------------------------------------------------------------- */

static void cmd_pos(void)
{
    int any = 0;
    int i;
    printf("\n%sPositions — %s%s\n", COL_BOLD, g_gateway_id, COL_RESET);
    for (i = 0; i < g_npositions; i++) {
        if (g_positions[i].net_qty != 0) {
            if (!any) {
                printf("  %-10s %8s %10s %14s\n", "SYMBOL", "NET_QTY", "AVG_COST", "REALIZED_PNL");
                printf("  %-10s %8s %10s %14s\n", "------", "-------", "--------", "------------");
                any = 1;
            }
            const char *c = (g_positions[i].net_qty > 0) ? COL_GREEN : COL_RED;
            printf("  %-10s %s%8d%s %10.2f %14.2f\n",
                   g_positions[i].symbol,
                   c, g_positions[i].net_qty, COL_RESET,
                   g_positions[i].avg_cost,
                   g_positions[i].realized_pnl);
        }
    }
    if (!any) printf("  (flat — no open positions)\n");
    printf("\n");
}

static void cmd_status(void)
{
    int open = 0;
    int i;
    for (i = 0; i < g_norders; i++) {
        const char *st = g_orders[i].status;
        if (strcmp(st, "CANCELLED") != 0 && strcmp(st, "FILLED") != 0 &&
            strcmp(st, "EXPIRED") != 0   && strcmp(st, "REJECTED") != 0)
            open++;
    }
    printf("\n%sSession Status%s\n", COL_BOLD, COL_RESET);
    printf("  Gateway:        %s\n", g_gateway_id);
    printf("  Session state:  %s\n", g_session_state);
    int nsym = g_nsymbols;
    if (nsym > 0) {
        printf("  Symbols:");
        for (i = 0; i < nsym && i < 8; i++) printf(" %s", g_symbols[i]);
        if (nsym > 8) printf(" … (%d total)", nsym);
        printf("\n");
    } else {
        printf("  Symbols:        (send SYMBOLS to load)\n");
    }
    printf("  Open orders:    %d\n\n", open);
}

static void cmd_help(void)
{
    printf("\n%sALF Gateway Client%s — commands\n\n", COL_BOLD, COL_RESET);
    puts("  NEW|SYM=<s>|SIDE=BUY|SELL|TYPE=<t>|QTY=<n>[|PRICE=<p>][|STOP=<p>]");
    puts("       [|TRAIL=<n>][|VISIBLE=<n>][|TIF=DAY|GTC|ATO|ATC][|SMP=...]");
    puts("  TYPES: MARKET LIMIT STOP STOP_LIMIT FOK IOC ICEBERG TRAILING_STOP OCO COMBO");
    puts("  AMEND|ID=<oid>[|PRICE=<p>][|QTY=<n>]");
    puts("  CANCEL|ID=<oid>  or  CANCEL|COMBO_ID=<id>  or  CANCEL|OCO_ID=<id>");
    puts("  QUOTE|SYM=<s>|BID=<p>|ASK=<p>|BID_QTY=<n>|ASK_QTY=<n>[|TIF=...|QUOTE_ID=...]");
    puts("  QUOTE_CANCEL|SYM=<s>");
    puts("  KILL[|SYM=<s>]    SYMBOLS    ORDERS    QBOOT[|SYM=<s>]");
    puts("  PING    POS    STATUS    HELP    EXIT / QUIT\n");
}

/* --------------------------------------------------------------------------
 * Readline line handler (called when user presses Enter)
 * -------------------------------------------------------------------------- */

static void line_handler(char *line)
{
    if (!line) {                        /* EOF / Ctrl-D */
        g_running = 0;
        rl_callback_handler_remove();
        printf("\n");
        return;
    }

    char trimmed[ALF_MAX_LINE_LEN];
    snprintf(trimmed, sizeof(trimmed), "%s", line);
    /* Strip leading whitespace */
    char *t = trimmed;
    while (*t == ' ' || *t == '\t') t++;
    /* Strip trailing whitespace */
    size_t tlen = strlen(t);
    while (tlen > 0 && (t[tlen-1] == ' ' || t[tlen-1] == '\t' || t[tlen-1] == '\r'))
        t[--tlen] = '\0';

    if (!*t) { free(line); return; }

    add_history(t);

    /* Parse first token */
    char cmd[32] = "";
    sscanf(t, "%31[^|]", cmd);
    for (int i = 0; cmd[i]; i++) cmd[i] = (char)toupper((unsigned char)cmd[i]);

    if (strcmp(cmd, "EXIT") == 0 || strcmp(cmd, "QUIT") == 0) {
        g_running = 0;
        rl_callback_handler_remove();
        free(line);
        return;
    }
    if (strcmp(cmd, "HELP") == 0)   { cmd_help();   free(line); return; }
    if (strcmp(cmd, "POS") == 0)    { cmd_pos();    free(line); return; }
    if (strcmp(cmd, "STATUS") == 0) { cmd_status(); free(line); return; }

    /* Send to gateway with uppercased verb */
    char sendline[ALF_MAX_LINE_LEN];
    const char *rest = strchr(t, '|');
    if (rest)
        snprintf(sendline, sizeof(sendline), "%s%s\n", cmd, rest);
    else
        snprintf(sendline, sizeof(sendline), "%s\n", cmd);

    if (gwy_send(sendline) < 0)
        g_running = 0;

    free(line);
}

/* --------------------------------------------------------------------------
 * Connect and handshake
 * -------------------------------------------------------------------------- */

static int connect_gateway(const char *host, int port)
{
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return -1; }

    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port   = htons((uint16_t)port);
    if (inet_pton(AF_INET, host, &addr.sin_addr) != 1) {
        fprintf(stderr, "Invalid host address: %s\n", host);
        close(fd);
        return -1;
    }
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        perror("connect");
        close(fd);
        return -1;
    }
    return fd;
}

static int do_handshake(int fd, const char *gateway_id, const char *client_name)
{
    (void)fd; /* fd is accessed via g_sockfd */
    const char *hello_kv[] = {
        "CLIENT", client_name,
        "PROTO",  "ALF1",
        "ID",     gateway_id,
        NULL
    };
    if (gwy_send_kv("HELLO", hello_kv) < 0) {
        return -1;
    }

    /* Read WELCOME (or ERR) */
    char line[ALF_MAX_LINE_LEN];
    int  n = 0;
    for (;;) {
        char c;
        if (read(fd, &c, 1) <= 0) return -1;
        if (c == '\n') break;
        if (n + 1 < (int)sizeof(line)) line[n++] = c;
    }
    line[n] = '\0';

    alf_message_t msg;
    char copy[ALF_MAX_LINE_LEN];
    snprintf(copy, sizeof(copy), "%s", line);
    if (alf_parse_line(copy, &msg) != 0) {
        fprintf(stderr, "Failed to parse handshake response: %s\n", line);
        return -1;
    }
    if (strcmp(msg.msg_type, "WELCOME") == 0) {
        const char *gw   = alf_get_field(&msg, "GW");
        const char *hb   = alf_get_field(&msg, "HBINT");
        const char *idle = alf_get_field(&msg, "IDLE");
        printf("%sGateway %s connected.%s  gw=%s  hb=%ss  idle=%ss\n",
               COL_GREEN, gateway_id, COL_RESET,
               gw   ? gw   : "alf-gwy",
               hb   ? hb   : "5",
               idle ? idle : "30");
        return 0;
    }
    if (strcmp(msg.msg_type, "ERR") == 0) {
        fprintf(stderr, "Authentication failed [%s]: %s\n",
                alf_get_field(&msg, "CODE")   ? alf_get_field(&msg, "CODE")   : "?",
                alf_get_field(&msg, "DETAIL") ? alf_get_field(&msg, "DETAIL") : "");
        return -1;
    }
    fprintf(stderr, "Unexpected handshake response: %s\n", msg.msg_type);
    return -1;
}

/* --------------------------------------------------------------------------
 * Signal handler
 * -------------------------------------------------------------------------- */

static void on_sigint(int sig)
{
    (void)sig;
    g_running = 0;
}

/* --------------------------------------------------------------------------
 * main
 * -------------------------------------------------------------------------- */

int main(int argc, char **argv)
{
    const char *host        = "127.0.0.1";
    int         port        = 5565;
    const char *gateway_id  = NULL;
    const char *client_name = "alf-c-client";

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--host")   == 0 && i + 1 < argc) host        = argv[++i];
        else if (strcmp(argv[i], "--port")   == 0 && i + 1 < argc) port   = atoi(argv[++i]);
        else if (strcmp(argv[i], "--id")     == 0 && i + 1 < argc) gateway_id = argv[++i];
        else if (strcmp(argv[i], "--client") == 0 && i + 1 < argc) client_name = argv[++i];
        else if (strcmp(argv[i], "--no-color") == 0) use_color = 0;
        else if (strcmp(argv[i], "--help") == 0) {
            printf("Usage: alf_client [--host H] [--port P] --id GW_ID [--client NAME] [--no-color]\n");
            return 0;
        }
    }

    if (!gateway_id) {
        fprintf(stderr, "Error: --id GW_ID is required\n");
        fprintf(stderr, "Usage: alf_client [--host H] [--port P] --id GW_ID [--client NAME]\n");
        return 1;
    }

    /* Uppercase the gateway ID */
    char gw_upper[64];
    snprintf(gw_upper, sizeof(gw_upper), "%s", gateway_id);
    for (int i = 0; gw_upper[i]; i++) gw_upper[i] = (char)toupper((unsigned char)gw_upper[i]);
    snprintf(g_gateway_id, sizeof(g_gateway_id), "%s", gw_upper);
    snprintf(g_prompt, sizeof(g_prompt), "[%s]> ", g_gateway_id);

    /* Connect */
    printf("Connecting to %s:%d as %s …\n", host, port, g_gateway_id);
    g_sockfd = connect_gateway(host, port);
    if (g_sockfd < 0) return 1;

    if (do_handshake(g_sockfd, g_gateway_id, client_name) < 0) {
        close(g_sockfd);
        return 1;
    }

    printf("Type %sHELP%s for commands.  Tab=complete  ↑↓=history\n\n",
           COL_BOLD, COL_RESET);

    /* History file */
    const char *home = getenv("HOME");
    char histfile[256] = "";
    if (home) snprintf(histfile, sizeof(histfile), "%s/.alf_client_history", home);
    if (*histfile) read_history(histfile);

    /* Readline setup */
    rl_attempted_completion_function = alf_completion;
    rl_callback_handler_install(g_prompt, line_handler);

    signal(SIGINT,  on_sigint);
    signal(SIGTERM, on_sigint);
    signal(SIGPIPE, SIG_IGN);

    /* Event loop */
    int maxfd = (g_sockfd > STDIN_FILENO) ? g_sockfd : STDIN_FILENO;
    while (g_running) {
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(STDIN_FILENO, &rfds);
        FD_SET(g_sockfd, &rfds);

        struct timeval tv = {0, 100000}; /* 100 ms */
        int r = select(maxfd + 1, &rfds, NULL, NULL, &tv);
        if (r < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (FD_ISSET(g_sockfd, &rfds))
            process_socket_data();
        if (g_running && FD_ISSET(STDIN_FILENO, &rfds))
            rl_callback_read_char();
    }

    /* Graceful exit */
    rl_callback_handler_remove();
    gwy_send("EXIT\n");
    if (*histfile) write_history(histfile);
    close(g_sockfd);
    printf("\n%sDisconnected.%s\n", COL_BOLD, COL_RESET);
    return 0;
}
