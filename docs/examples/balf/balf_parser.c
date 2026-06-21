/* Reference BALF parser (C, C11)
 *
 * Compile:
 *   cc -std=c11 -Wall -Wextra -pedantic -O2 balf_parser.c -o balf_parser
 * Run:
 *   ./balf_parser
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

static int frame_size(uint8_t msg_type) {
    switch (msg_type) {
        case MSG_LOGON: return 32;
        case MSG_LOGON_ACK: return 92;
        case MSG_NEW_ORDER: return 60;
        case MSG_ORDER_ACK: return 68;
        case MSG_CANCEL_ORDER: return 32;
        case MSG_CANCEL_ACK: return 40;
        case MSG_AMEND_ORDER: return 52;
        case MSG_AMEND_ACK: return 56;
        case MSG_EXECUTION_REPORT: return 72;
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

int main(void) {
    uint8_t frame[92];
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

    puts("balf_parser.c self-test: OK");
    return 0;
}
