/* GENERATED FROM spec/messages/order.yaml - DO NOT EDIT
 *
 * Regenerate with:  make msgen  (or: poetry run pm-msgen generate)
 *
 * Typed C bindings for the 'order' message family, one struct
 * per declared external projection. A struct mirrors what its transport
 * actually carries, not the internal bus payload - see design section 5.2.
 */
#ifndef EDUMATCHER_ORDER_H
#define EDUMATCHER_ORDER_H

#include <stddef.h>
#include <stdint.h>

#include "edumatcher_msg.h"

#define EDU_ORDER_FAMILY_VERSION 1

/* --- execution_report / BALF 0x20 --- Private per-order fill notification,
 * sent to the gateway session that owns the order. Both sides of a match
 * receive their own report.
 */

#define EDU_EXECUTION_REPORT_BALF_MSGTYPE 0x20
#define EDU_EXECUTION_REPORT_BALF_FRAME_SIZE 64
#define EDU_EXECUTION_REPORT_BALF_BODY_SIZE 56
#define EDU_EXECUTION_REPORT_BALF_PRICE_SCALE 100000000LL

typedef enum {
    EDU_EXECUTION_REPORT_SIDE_BUY = 1,
    EDU_EXECUTION_REPORT_SIDE_SELL = 2
} edu_execution_report_side_t;

const char *edu_execution_report_side_to_str(edu_execution_report_side_t v);
int edu_execution_report_side_from_str(const char *s, edu_execution_report_side_t *out);

typedef enum {
    EDU_EXECUTION_REPORT_STATUS_PARTIAL = 1,
    EDU_EXECUTION_REPORT_STATUS_FILLED = 2
} edu_execution_report_status_t;

const char *edu_execution_report_status_to_str(edu_execution_report_status_t v);
int edu_execution_report_status_from_str(const char *s, edu_execution_report_status_t *out);

typedef struct {
    uint64_t client_order_id;  /* u64 @0, unit: dimensionless */
    uint64_t order_id;  /* u64 @8, unit: dimensionless */
    double fill_price;  /* i64 @16, unit: display_price, wire is x100000000 */
    uint32_t fill_qty;  /* u32 @24, unit: shares */
    uint32_t remaining_qty;  /* u32 @28, unit: shares */
    uint64_t timestamp_ns;  /* u64 @32, unit: epoch_nanos */
    char symbol[9];  /* char[8] @40 */
    edu_execution_report_side_t side;  /* u8 @48 */
    edu_execution_report_status_t status;  /* u8 @49 */
    /* bytes 50..56 reserved, must be zero */
} edu_execution_report_balf_t;

/* Parse one complete 64-byte frame, header included. Checks magic, version,
 * msg_type and length before reading any field: a frame of the wrong length
 * is not this message, and unpacking it anyway would read neighbouring
 * bytes as values. Coerces but does not validate (design section 5.1.1).
 * Returns EDU_MSG_OK, EDU_MSG_ERR_SHORT, EDU_MSG_ERR_MAGIC,
 * EDU_MSG_ERR_VERSION, EDU_MSG_ERR_MSGTYPE, EDU_MSG_ERR_LENGTH or
 * EDU_MSG_ERR_FIELD.
 */
int edu_execution_report_balf_parse(const uint8_t *frame, size_t len, edu_execution_report_balf_t *out);

/* Enforce the rules declared in the spec. Writes a message into err when it
 * fails and errlen is non-zero. Returns EDU_MSG_OK or EDU_MSG_ERR_FIELD.
 */
int edu_execution_report_balf_validate(const edu_execution_report_balf_t *m, char *err, size_t errlen);

/* --- stop_triggered / BALF 0x21 --- A stop, stop-limit or trailing stop of
 * this session has fired. Sent before the order's own execution reports, so
 * a client knows why its stop traded -- the FIX analogue is ExecType=L.
 */

#define EDU_STOP_TRIGGERED_BALF_MSGTYPE 0x21
#define EDU_STOP_TRIGGERED_BALF_FRAME_SIZE 56
#define EDU_STOP_TRIGGERED_BALF_BODY_SIZE 48
#define EDU_STOP_TRIGGERED_BALF_PRICE_SCALE 100000000LL

typedef enum {
    EDU_STOP_TRIGGERED_ORDER_TYPE_STOP = 1,
    EDU_STOP_TRIGGERED_ORDER_TYPE_STOP_LIMIT = 2,
    EDU_STOP_TRIGGERED_ORDER_TYPE_TRAILING_STOP = 3
} edu_stop_triggered_order_type_t;

const char *edu_stop_triggered_order_type_to_str(edu_stop_triggered_order_type_t v);
int edu_stop_triggered_order_type_from_str(const char *s, edu_stop_triggered_order_type_t *out);

typedef enum {
    EDU_STOP_TRIGGERED_BECOMES_MARKET = 1,
    EDU_STOP_TRIGGERED_BECOMES_LIMIT = 2
} edu_stop_triggered_becomes_t;

const char *edu_stop_triggered_becomes_to_str(edu_stop_triggered_becomes_t v);
int edu_stop_triggered_becomes_from_str(const char *s, edu_stop_triggered_becomes_t *out);

typedef struct {
    uint64_t client_order_id;  /* u64 @0, unit: dimensionless */
    uint64_t order_id;  /* u64 @8, unit: dimensionless */
    double stop_price;  /* i64 @16, unit: display_price, wire is x100000000 */
    double trigger_price;  /* i64 @24, unit: display_price, wire is x100000000 */
    char symbol[9];  /* char[8] @32 */
    edu_stop_triggered_order_type_t order_type;  /* u8 @40 */
    edu_stop_triggered_becomes_t becomes;  /* u8 @41 */
    /* bytes 42..48 reserved, must be zero */
} edu_stop_triggered_balf_t;

/* Parse one complete 56-byte frame, header included. Checks magic, version,
 * msg_type and length before reading any field: a frame of the wrong length
 * is not this message, and unpacking it anyway would read neighbouring
 * bytes as values. Coerces but does not validate (design section 5.1.1).
 * Returns EDU_MSG_OK, EDU_MSG_ERR_SHORT, EDU_MSG_ERR_MAGIC,
 * EDU_MSG_ERR_VERSION, EDU_MSG_ERR_MSGTYPE, EDU_MSG_ERR_LENGTH or
 * EDU_MSG_ERR_FIELD.
 */
int edu_stop_triggered_balf_parse(const uint8_t *frame, size_t len, edu_stop_triggered_balf_t *out);

/* Enforce the rules declared in the spec. Writes a message into err when it
 * fails and errlen is non-zero. Returns EDU_MSG_OK or EDU_MSG_ERR_FIELD.
 */
int edu_stop_triggered_balf_validate(const edu_stop_triggered_balf_t *m, char *err, size_t errlen);

#endif /* EDUMATCHER_ORDER_H */
