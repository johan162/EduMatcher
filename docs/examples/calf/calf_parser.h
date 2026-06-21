#ifndef CALF_PARSER_H
#define CALF_PARSER_H

#include <stddef.h>

#define CALF_MAX_FIELDS 64
#define CALF_MAX_KEY_LEN 64
#define CALF_MAX_VAL_LEN 512
#define CALF_MAX_MSGTYPE_LEN 32

typedef struct {
    char key[CALF_MAX_KEY_LEN];
    char value[CALF_MAX_VAL_LEN];
} calf_field_t;

typedef struct {
    char msg_type[CALF_MAX_MSGTYPE_LEN];
    int field_count;
    calf_field_t fields[CALF_MAX_FIELDS];
} calf_message_t;

/* Parse one mutable line (without trailing '\n') into a CALF message. */
int calf_parse_line(char *line, calf_message_t *out_msg);

/* Get field value by key, or NULL when absent. */
const char *calf_get_field(const calf_message_t *msg, const char *key);

#endif
