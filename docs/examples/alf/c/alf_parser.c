#define _POSIX_C_SOURCE 200809L

#include "alf_parser.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

/* --------------------------------------------------------------------------
 * Internal helpers
 * -------------------------------------------------------------------------- */

static int is_valid_msgtype(const char *s)
{
    if (!s || !*s) return 0;
    for (; *s; s++) {
        unsigned char ch = (unsigned char)*s;
        if (!(isupper(ch) || isdigit(ch) || ch == '_')) return 0;
    }
    return 1;
}

/* Uppercase a string in-place. */
static void str_toupper(char *s)
{
    for (; *s; s++)
        *s = (char)toupper((unsigned char)*s);
}

static char *trim(char *s)
{
    while (isspace((unsigned char)*s)) s++;
    char *end = s + strlen(s);
    while (end > s && isspace((unsigned char)end[-1])) *--end = '\0';
    return s;
}

/* --------------------------------------------------------------------------
 * alf_parse_line
 * -------------------------------------------------------------------------- */

int alf_parse_line(char *line, alf_message_t *out_msg)
{
    if (!line || !out_msg) return -1;

    memset(out_msg, 0, sizeof(*out_msg));

    line = trim(line);
    if (!*line) return -2;
    char *token = line;
    char *next = strchr(token, '|');
    if (next) *next++ = '\0';

    /* Uppercase the verb. */
    token = trim(token);
    str_toupper(token);
    if (!is_valid_msgtype(token)) return -3;
    if (strlen(token) >= sizeof(out_msg->msg_type)) return -6;
    snprintf(out_msg->msg_type, sizeof(out_msg->msg_type), "%s", token);

    int idx = 0;
    while (next) {
        token = next;
        next = strchr(token, '|');
        if (next) *next++ = '\0';

        char *eq = strchr(token, '=');
        if (!eq)
            continue; /* silently skip bare-word segments */

        *eq = '\0';
        char *key = trim(token);
        const char *value = trim(eq + 1);

        if (*key == '\0') continue; /* empty key — skip */

        /* Uppercase the key; value preserves original case. */
        if (strlen(key) >= ALF_MAX_KEY_LEN || strlen(value) >= ALF_MAX_VAL_LEN) return -6;
        str_toupper(key);

        int field = 0;
        while (field < idx && strcmp(out_msg->fields[field].key, key) != 0) field++;
        if (field == idx) {
            if (idx >= ALF_MAX_FIELDS) return -4;
            idx++;
        }
        snprintf(out_msg->fields[field].key, sizeof(out_msg->fields[field].key), "%s", key);
        snprintf(out_msg->fields[field].value, sizeof(out_msg->fields[field].value), "%s", value);
    }

    out_msg->field_count = idx;
    return 0;
}

/* --------------------------------------------------------------------------
 * alf_get_field
 * -------------------------------------------------------------------------- */

const char *alf_get_field(const alf_message_t *msg, const char *key)
{
    int i;
    if (!msg || !key) return NULL;

    for (i = 0; i < msg->field_count; i++) {
        if (strcasecmp(msg->fields[i].key, key) == 0)
            return msg->fields[i].value;
    }
    return NULL;
}

/* --------------------------------------------------------------------------
 * alf_build_line
 * -------------------------------------------------------------------------- */

int alf_build_line(char *out, size_t cap,
                   const char *msg_type,
                   const char * const *kv)
{
    if (!out || cap == 0 || !msg_type || !*msg_type) return -1;
    for (const char *p = msg_type; *p; p++) {
        unsigned char ch = (unsigned char)toupper((unsigned char)*p);
        if (!((ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '_')) return -1;
    }

    int written = snprintf(out, cap, "%s", msg_type);
    if (written < 0 || (size_t)written >= cap) return -1;

    if (kv) {
        int i;
        for (i = 0; kv[i]; i += 2) {
            if (!kv[i + 1] || !*kv[i] || strpbrk(kv[i], "|=\r\n") ||
                strchr(kv[i + 1], '|')) return -1;
            int n = snprintf(out + written, cap - (size_t)written,
                             "|%s=%s", kv[i], kv[i + 1]);
            if (n < 0 || (size_t)(written + n) >= cap) return -1;
            written += n;
        }
    }

    if ((size_t)(written + 1) >= cap) return -1;
    out[written++] = '\n';
    out[written]   = '\0';
    for (int i = 0; i < written - 1; i++) {
        if (out[i] == '\r' || out[i] == '\n') out[i] = ' ';
    }
    return written;
}
