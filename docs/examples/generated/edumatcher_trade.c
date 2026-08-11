/* GENERATED FROM spec/messages/trade.yaml - DO NOT EDIT
 *
 * Regenerate with:  make msgen  (or: poetry run pm-msgen generate)
 */
#include "edumatcher_trade.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const char *edu_trade_executed_aggressor_side_to_str(edu_trade_executed_aggressor_side_t v) {
    switch (v) {
        case EDU_TRADE_EXECUTED_AGGRESSOR_SIDE_BUY:
            return "BUY";
        case EDU_TRADE_EXECUTED_AGGRESSOR_SIDE_SELL:
            return "SELL";
        case EDU_TRADE_EXECUTED_AGGRESSOR_SIDE_AUCTION:
            return "AUCTION";
        default:
            return "";
    }
}

int edu_trade_executed_aggressor_side_from_str(const char *s, edu_trade_executed_aggressor_side_t *out) {
    if (!s || !out) return EDU_MSG_ERR_FIELD;
    if (strcmp(s, "BUY") == 0) {
        *out = EDU_TRADE_EXECUTED_AGGRESSOR_SIDE_BUY;
        return EDU_MSG_OK;
    }
    if (strcmp(s, "SELL") == 0) {
        *out = EDU_TRADE_EXECUTED_AGGRESSOR_SIDE_SELL;
        return EDU_MSG_OK;
    }
    if (strcmp(s, "AUCTION") == 0) {
        *out = EDU_TRADE_EXECUTED_AGGRESSOR_SIDE_AUCTION;
        return EDU_MSG_OK;
    }
    return EDU_MSG_ERR_FIELD;
}

int edu_trade_executed_calf_parse(const calf_message_t *in, edu_trade_executed_calf_t *out) {
    const char *raw;
    char *end;

    if (!in || !out) return EDU_MSG_ERR_FIELD;
    memset(out, 0, sizeof(*out));

    if (strcmp(in->msg_type, EDU_TRADE_EXECUTED_CALF_MSGTYPE) != 0)
        return EDU_MSG_ERR_MSGTYPE;

    raw = calf_get_field(in, "PX");
    if (!raw) return EDU_MSG_ERR_FIELD;
    errno = 0;
    out->price = strtod(raw, &end);
    if (end == raw || *end != '\0' || errno == ERANGE)
        return EDU_MSG_ERR_FIELD;

    raw = calf_get_field(in, "QTY");
    if (!raw) return EDU_MSG_ERR_FIELD;
    errno = 0;
    out->quantity = (int64_t)strtoll(raw, &end, 10);
    if (end == raw || *end != '\0' || errno == ERANGE)
        return EDU_MSG_ERR_FIELD;

    raw = calf_get_field(in, "SIDE");
    if (!raw) return EDU_MSG_ERR_FIELD;
    if (edu_trade_executed_aggressor_side_from_str(raw, &out->aggressor_side) != EDU_MSG_OK)
        return EDU_MSG_ERR_FIELD;

    return EDU_MSG_OK;
}

int edu_trade_executed_calf_validate(const edu_trade_executed_calf_t *m, char *err, size_t errlen) {
    if (!m) return EDU_MSG_ERR_FIELD;

    if (m->price <= 0) {
        if (err && errlen) snprintf(err, errlen, "price must be > 0");
        return EDU_MSG_ERR_FIELD;
    }
    if (m->quantity <= 0) {
        if (err && errlen) snprintf(err, errlen, "quantity must be > 0");
        return EDU_MSG_ERR_FIELD;
    }
    return EDU_MSG_OK;
}
