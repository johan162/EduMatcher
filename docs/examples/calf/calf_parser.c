#define _POSIX_C_SOURCE 200809L

#include "calf_parser.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>

static int is_valid_msgtype(const char *s) {
    if (!s || !*s) return 0;
    for (; *s; s++) {
        unsigned char ch = (unsigned char)*s;
        if (!(isupper(ch) || isdigit(ch) || ch == '_')) return 0;
    }
    return 1;
}

int calf_parse_line(char *line, calf_message_t *out_msg) {
    if (!line || !out_msg) return -1;

    memset(out_msg, 0, sizeof(*out_msg));

    char *saveptr = NULL;
    char *token = strtok_r(line, "|", &saveptr);
    if (!token) return -2;

    if (!is_valid_msgtype(token)) return -3;
    snprintf(out_msg->msg_type, sizeof(out_msg->msg_type), "%s", token);

    int idx = 0;
    while ((token = strtok_r(NULL, "|", &saveptr)) != NULL) {
        if (idx >= CALF_MAX_FIELDS) return -4;

        char *eq = strchr(token, '=');
        if (!eq) return -5;
        *eq = '\0';
        const char *key = token;
        const char *value = eq + 1;

        if (strlen(key) == 0) return -6;

        snprintf(out_msg->fields[idx].key, sizeof(out_msg->fields[idx].key), "%s", key);
        snprintf(out_msg->fields[idx].value, sizeof(out_msg->fields[idx].value), "%s", value);
        idx++;
    }

    out_msg->field_count = idx;
    return 0;
}

const char *calf_get_field(const calf_message_t *msg, const char *key) {
    int i;
    if (!msg || !key) return NULL;

    for (i = 0; i < msg->field_count; i++) {
        if (strcmp(msg->fields[i].key, key) == 0) {
            return msg->fields[i].value;
        }
    }
    return NULL;
}
