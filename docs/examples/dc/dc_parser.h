#ifndef DC_PARSER_H
#define DC_PARSER_H

#include <stddef.h>

#define DC_MAX_FIELDS 64
#define DC_MAX_KEY_LEN 64
#define DC_MAX_VAL_LEN 512
#define DC_MAX_MSGTYPE_LEN 32

typedef struct {
    char key[DC_MAX_KEY_LEN];
    char value[DC_MAX_VAL_LEN];
} dc_field_t;

typedef struct {
    char msg_type[DC_MAX_MSGTYPE_LEN];
    int field_count;
    dc_field_t fields[DC_MAX_FIELDS];
} dc_message_t;

/* Parse one mutable line (without trailing '\n') into a DC1 message. */
int dc_parse_line(char *line, dc_message_t *out_msg);

/* Get field value by key, or NULL when absent. */
const char *dc_get_field(const dc_message_t *msg, const char *key);

#endif
