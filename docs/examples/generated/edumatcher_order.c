/* GENERATED FROM spec/messages/order.yaml - DO NOT EDIT
 *
 * Regenerate with:  make msgen  (or: poetry run pm-msgen generate)
 */
#include "edumatcher_order.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t edu_rd_u8(const uint8_t *p) {
    return p[0];
}

static uint32_t edu_rd_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
               ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t edu_rd_u64(const uint8_t *p) {
    uint64_t v = 0;
        int i;
        for (i = 7; i >= 0; i--) v = (v << 8) | p[i];
        return v;
}

static int64_t edu_rd_i64(const uint8_t *p) {
    return (int64_t)edu_rd_u64(p);
}

const char *edu_execution_report_side_to_str(edu_execution_report_side_t v) {
    switch (v) {
        case EDU_EXECUTION_REPORT_SIDE_BUY:
            return "BUY";
        case EDU_EXECUTION_REPORT_SIDE_SELL:
            return "SELL";
        default:
            return "";
    }
}

int edu_execution_report_side_from_str(const char *s, edu_execution_report_side_t *out) {
    if (!s || !out) return EDU_MSG_ERR_FIELD;
    if (strcmp(s, "BUY") == 0) {
        *out = EDU_EXECUTION_REPORT_SIDE_BUY;
        return EDU_MSG_OK;
    }
    if (strcmp(s, "SELL") == 0) {
        *out = EDU_EXECUTION_REPORT_SIDE_SELL;
        return EDU_MSG_OK;
    }
    return EDU_MSG_ERR_FIELD;
}

const char *edu_execution_report_status_to_str(edu_execution_report_status_t v) {
    switch (v) {
        case EDU_EXECUTION_REPORT_STATUS_PARTIAL:
            return "PARTIAL";
        case EDU_EXECUTION_REPORT_STATUS_FILLED:
            return "FILLED";
        default:
            return "";
    }
}

int edu_execution_report_status_from_str(const char *s, edu_execution_report_status_t *out) {
    if (!s || !out) return EDU_MSG_ERR_FIELD;
    if (strcmp(s, "PARTIAL") == 0) {
        *out = EDU_EXECUTION_REPORT_STATUS_PARTIAL;
        return EDU_MSG_OK;
    }
    if (strcmp(s, "FILLED") == 0) {
        *out = EDU_EXECUTION_REPORT_STATUS_FILLED;
        return EDU_MSG_OK;
    }
    return EDU_MSG_ERR_FIELD;
}

int edu_execution_report_balf_parse(const uint8_t *frame, size_t len, edu_execution_report_balf_t *out) {
    const uint8_t *body;

    if (!frame || !out) return EDU_MSG_ERR_FIELD;
    if (len < 8) return EDU_MSG_ERR_SHORT;
    if (frame[0] != EDU_BALF_MAGIC) return EDU_MSG_ERR_MAGIC;
    if (frame[1] != EDU_BALF_VERSION) return EDU_MSG_ERR_VERSION;
    if (frame[2] != EDU_EXECUTION_REPORT_BALF_MSGTYPE) return EDU_MSG_ERR_MSGTYPE;
    if (len != EDU_EXECUTION_REPORT_BALF_FRAME_SIZE) return EDU_MSG_ERR_LENGTH;

    memset(out, 0, sizeof(*out));
    body = frame + 8;

    out->client_order_id = edu_rd_u64(body + 0);
    out->order_id = edu_rd_u64(body + 8);
    out->fill_price = (double)edu_rd_i64(body + 16) / 100000000.0;
    out->fill_qty = edu_rd_u32(body + 24);
    out->remaining_qty = edu_rd_u32(body + 28);
    out->timestamp_ns = edu_rd_u64(body + 32);
    memcpy(out->symbol, body + 40, 8);
    out->symbol[8] = '\0';
    switch (edu_rd_u8(body + 48)) {
        case 1:
            out->side = EDU_EXECUTION_REPORT_SIDE_BUY;
            break;
        case 2:
            out->side = EDU_EXECUTION_REPORT_SIDE_SELL;
            break;
        default:
            return EDU_MSG_ERR_FIELD;
    }
    switch (edu_rd_u8(body + 49)) {
        case 1:
            out->status = EDU_EXECUTION_REPORT_STATUS_PARTIAL;
            break;
        case 2:
            out->status = EDU_EXECUTION_REPORT_STATUS_FILLED;
            break;
        default:
            return EDU_MSG_ERR_FIELD;
    }

    return EDU_MSG_OK;
}

int edu_execution_report_balf_validate(const edu_execution_report_balf_t *m, char *err, size_t errlen) {
    if (!m) return EDU_MSG_ERR_FIELD;

    if (m->fill_price <= 0) {
        if (err && errlen) snprintf(err, errlen, "fill_price must be > 0");
        return EDU_MSG_ERR_FIELD;
    }
    if (m->fill_qty <= 0) {
        if (err && errlen) snprintf(err, errlen, "fill_qty must be > 0");
        return EDU_MSG_ERR_FIELD;
    }
    if (strlen(m->symbol) > 8) {
        if (err && errlen) snprintf(err, errlen, "symbol exceeds max_len 8");
        return EDU_MSG_ERR_FIELD;
    }
    return EDU_MSG_OK;
}
