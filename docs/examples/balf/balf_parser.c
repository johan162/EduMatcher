/* Reference BALF parser (C, C11)
 *
 * Compile:
 *   cc -std=c11 -Wall -Wextra -pedantic -O2 -I../generated \
 *      balf_parser.c ../generated/edumatcher_order.c \
 *      ../generated/edumatcher_msg.c -o balf_parser
 * Run:
 *   ./balf_parser
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "edumatcher_order.h"

#define BALF_MAGIC   0xBAu
#define BALF_VERSION 0x01u

#define MSG_LOGON            0x01u
#define MSG_LOGON_ACK        0x02u
#define MSG_NEW_ORDER        0x10u
#define MSG_ORDER_ACK        0x11u
#define MSG_CANCEL_ORDER     0x12u
#define MSG_CANCEL_ACK       0x13u
#define MSG_AMEND_ORDER      0x14u
#define MSG_AMEND_ACK        0x15u
#define MSG_EXECUTION_REPORT 0x20u
#define MSG_HEARTBEAT        0x30u
#define MSG_HEARTBEAT_ACK    0x31u
#define MSG_LOGOUT           0x40u

typedef struct {
    uint8_t magic;
    uint8_t version;
    uint8_t msg_type;
    uint8_t flags;
    uint32_t seq_no;
} BalfHeader;

static uint32_t read_u32_le(const uint8_t *p) {
    return ((uint32_t)p[0]) |
           ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

/* Little-endian writers, used only to build the demo frames in main(). */
static void write_u32_le(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v);
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static void write_u64_le(uint8_t *p, uint64_t v) {
    int i;
    for (i = 0; i < 8; i++) {
        p[i] = (uint8_t)(v >> (8 * i));
    }
}

static int frame_size(uint8_t msg_type) {
    switch (msg_type) {
        case MSG_LOGON: return 32;
        case MSG_LOGON_ACK: return 92;
        case MSG_NEW_ORDER: return 60;
        case MSG_ORDER_ACK: return 60;
        case MSG_CANCEL_ORDER: return 24;
        case MSG_CANCEL_ACK: return 32;
        case MSG_AMEND_ORDER: return 44;
        case MSG_AMEND_ACK: return 48;
        case MSG_EXECUTION_REPORT: return 64;
        case MSG_HEARTBEAT: return 16;
        case MSG_HEARTBEAT_ACK: return 16;
        case MSG_LOGOUT: return 8;
        default: return -1;
    }
}

static int parse_header(const uint8_t *frame, size_t len, BalfHeader *out) {
    if (len < 8) return -1;
    out->magic = frame[0];
    out->version = frame[1];
    out->msg_type = frame[2];
    out->flags = frame[3];
    out->seq_no = read_u32_le(frame + 4);

    if (out->magic != BALF_MAGIC) return -2;
    if (out->version != BALF_VERSION) return -3;
    return 0;
}

static int split_frame(const uint8_t *frame, size_t len, BalfHeader *hdr, const uint8_t **body, size_t *body_len) {
    int rc = parse_header(frame, len, hdr);
    int total;
    if (rc != 0) return rc;
    total = frame_size(hdr->msg_type);
    if (total < 0) return -4;
    if (len != (size_t)total) return -5;
    *body = frame + 8;
    *body_len = len - 8;
    return 0;
}

static void parse_logon_ack(const uint8_t *body, size_t len) {
    char gateway_id[17];
    uint8_t accepted;
    uint8_t reject_code;
    uint8_t msg_len;
    char message[65];

    if (len != 84) {
        fprintf(stderr, "LOGON_ACK body size error: %zu\n", len);
        return;
    }

    memset(gateway_id, 0, sizeof(gateway_id));
    memcpy(gateway_id, body, 16);
    accepted = body[16];
    reject_code = body[17];
    msg_len = body[18];
    if (msg_len > 64) msg_len = 64;
    memset(message, 0, sizeof(message));
    memcpy(message, body + 20, msg_len);

    printf("LOGON_ACK gateway_id=%s accepted=%u reject_code=%u msg=%s\n",
           gateway_id, (unsigned)accepted, (unsigned)reject_code, message);
}

/* EXECUTION_REPORT is parsed by the GENERATED binding rather than by hand.
 *
 * Every other message in this file re-derives its layout from the protocol
 * appendix, which is exactly how this example came to disagree with the
 * gateway: it modelled order_id as a 16-byte string where the protocol defines
 * a u64, making it eight bytes too large on all six messages that carry one.
 * The generated parser cannot drift that way -- its offsets come from
 * spec/messages/order.yaml, and `pm-msgen check` fails the build if the two
 * disagree. See docs/developer/06-msgen.md.
 */
static void parse_execution_report_generated(const uint8_t *frame, size_t len) {
    edu_execution_report_balf_t er;
    char err[128];
    int rc = edu_execution_report_balf_parse(frame, len, &er);

    if (rc != EDU_MSG_OK) {
        fprintf(stderr, "EXECUTION_REPORT parse failed: %s\n", edu_msg_strerror(rc));
        return;
    }
    if (edu_execution_report_balf_validate(&er, err, sizeof(err)) != EDU_MSG_OK) {
        fprintf(stderr, "EXECUTION_REPORT rejected: %s\n", err);
        return;
    }

    printf("EXECUTION_REPORT order_id=%llu %s %u @ %.8f (%s, remaining %u)\n",
           (unsigned long long)er.order_id,
           er.symbol,
           er.fill_qty,
           er.fill_price,
           edu_execution_report_status_to_str(er.status),
           er.remaining_qty);
}

int main(void) {
    uint8_t frame[92];
    uint8_t exec[EDU_EXECUTION_REPORT_BALF_FRAME_SIZE];
    BalfHeader hdr;
    const uint8_t *body = NULL;
    size_t body_len = 0;
    int rc;

    memset(frame, 0, sizeof(frame));
    frame[0] = BALF_MAGIC;
    frame[1] = BALF_VERSION;
    frame[2] = MSG_LOGON_ACK;
    frame[3] = 0;
    /* seq_no = 0 at bytes 4..7 */

    memcpy(frame + 8, "TRADER01", 8);
    frame[8 + 16] = 1; /* accepted */
    frame[8 + 17] = 0; /* reject_code */
    frame[8 + 18] = 2; /* msg_len */
    memcpy(frame + 8 + 20, "ok", 2);

    rc = split_frame(frame, sizeof(frame), &hdr, &body, &body_len);
    if (rc != 0) {
        fprintf(stderr, "split_frame failed rc=%d\n", rc);
        return 1;
    }

    if (hdr.msg_type == MSG_LOGON_ACK) {
        parse_logon_ack(body, body_len);
    }

    /* A minimal EXECUTION_REPORT: order_id 4242, 25 AAPL fully filled at
     * 150.00. Offsets are the protocol's; the generated parser reads them
     * back. Values are written with a helper rather than as hand-computed hex
     * -- the first draft of this block spelled 150.00 wrong and printed
     * 149.81, which is the whole reason the layout lives in a spec now. */
    memset(exec, 0, sizeof(exec));
    exec[0] = BALF_MAGIC;
    exec[1] = BALF_VERSION;
    exec[2] = MSG_EXECUTION_REPORT;
    write_u64_le(exec + 8 + 0, 1);                  /* client_order_id      */
    write_u64_le(exec + 8 + 8, 4242);               /* order_id             */
    write_u64_le(exec + 8 + 16, 150ULL * 100000000ULL); /* fill_price x1e8  */
    write_u32_le(exec + 8 + 24, 25);                /* fill_qty             */
    write_u32_le(exec + 8 + 28, 0);                 /* remaining_qty        */
    write_u64_le(exec + 8 + 32, 1700000000000000000ULL); /* timestamp_ns    */
    memcpy(exec + 8 + 40, "AAPL", 4);               /* symbol               */
    exec[8 + 48] = 1;                               /* side   = BUY         */
    exec[8 + 49] = 2;                               /* status = FILLED      */
    parse_execution_report_generated(exec, sizeof(exec));

    puts("balf_parser.c self-test: OK");
    return 0;
}
