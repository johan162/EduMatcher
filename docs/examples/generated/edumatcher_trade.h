/* GENERATED FROM spec/messages/trade.yaml - DO NOT EDIT
 *
 * Regenerate with:  make msgen  (or: poetry run pm-msgen generate)
 *
 * Typed C bindings for the 'trade' message family, one struct
 * per declared external projection. A struct mirrors what its transport
 * actually carries, not the internal bus payload - see design section 5.2.
 */
#ifndef EDUMATCHER_TRADE_H
#define EDUMATCHER_TRADE_H

#include <stddef.h>
#include <stdint.h>

#include "calf_parser.h"
#include "edumatcher_msg.h"

#define EDU_TRADE_FAMILY_VERSION 1

/* --- trade_executed / CALF TRADE --- Public print of a completed match.
 * The authoritative record of what traded, consumed by statistics,
 * clearing, index and market data.
 */

#define EDU_TRADE_EXECUTED_CALF_MSGTYPE "TRADE"

typedef enum {
    EDU_TRADE_EXECUTED_AGGRESSOR_SIDE_BUY = 1,
    EDU_TRADE_EXECUTED_AGGRESSOR_SIDE_SELL = 2,
    EDU_TRADE_EXECUTED_AGGRESSOR_SIDE_AUCTION = 3
} edu_trade_executed_aggressor_side_t;

const char *edu_trade_executed_aggressor_side_to_str(edu_trade_executed_aggressor_side_t v);
int edu_trade_executed_aggressor_side_from_str(const char *s, edu_trade_executed_aggressor_side_t *out);

typedef struct {
    char id[65];  /* TRADE_ID */
    int64_t run_seq;  /* RUN_SEQ, unit: dimensionless */
    double price;  /* PX, unit: display_price */
    int64_t quantity;  /* QTY, unit: shares */
    edu_trade_executed_aggressor_side_t aggressor_side;  /* SIDE */
    /* CH, SYM, SEQ, TS are gateway-injected CALF envelope keys, parsed into
     * the frame around this message rather than into it - see design
     * section 4.6.
     */
} edu_trade_executed_calf_t;

/* Convert an already-tokenised line into the typed struct. Coerces but does
 * not validate, mirroring the Python binding's from_dict (design section
 * 5.1.1). Returns EDU_MSG_OK, EDU_MSG_ERR_MSGTYPE, EDU_MSG_ERR_FIELD or
 * EDU_MSG_ERR_OVERFLOW.
 */
int edu_trade_executed_calf_parse(const calf_message_t *in, edu_trade_executed_calf_t *out);

/* Enforce the rules declared in the spec. Writes a message into err when it
 * fails and errlen is non-zero. Returns EDU_MSG_OK or EDU_MSG_ERR_FIELD.
 */
int edu_trade_executed_calf_validate(const edu_trade_executed_calf_t *m, char *err, size_t errlen);

#endif /* EDUMATCHER_TRADE_H */
