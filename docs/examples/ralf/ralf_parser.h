#ifndef RALF_PARSER_H
#define RALF_PARSER_H

#include <stddef.h>

#define RALF_MAX_FIELDS 64
#define RALF_MAX_KEY_LEN 64
#define RALF_MAX_VAL_LEN 512
#define RALF_MAX_MSGTYPE_LEN 32

typedef struct {
    char key[RALF_MAX_KEY_LEN];
    char value[RALF_MAX_VAL_LEN];
} ralf_field_t;

typedef struct {
    char msg_type[RALF_MAX_MSGTYPE_LEN];
    int field_count;
    ralf_field_t fields[RALF_MAX_FIELDS];
} ralf_message_t;

/* Parse one mutable line (without trailing '\n') into a RALF message. */
int ralf_parse_line(char *line, ralf_message_t *out_msg);

/* Get field value by key, or NULL when absent. */
const char *ralf_get_field(const ralf_message_t *msg, const char *key);

#endif
