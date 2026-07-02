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

/* --------------------------------------------------------------------------
 * alf_parse_line
 * -------------------------------------------------------------------------- */

int alf_parse_line(char *line, alf_message_t *out_msg)
{
    if (!line || !out_msg) return -1;

    memset(out_msg, 0, sizeof(*out_msg));

    char   *saveptr = NULL;
    char   *token   = strtok_r(line, "|", &saveptr);
    if (!token) return -2;

    /* Uppercase the verb. */
    str_toupper(token);
    if (!is_valid_msgtype(token)) return -3;
    snprintf(out_msg->msg_type, sizeof(out_msg->msg_type), "%s", token);

    int idx = 0;
    while ((token = strtok_r(NULL, "|", &saveptr)) != NULL) {
        if (idx >= ALF_MAX_FIELDS) return -4;

        char *eq = strchr(token, '=');
        if (!eq)
            continue; /* silently skip bare-word segments */

        *eq = '\0';
        const char *key   = token;
        const char *value = eq + 1;

        if (*key == '\0') continue; /* empty key — skip */

        /* Uppercase the key; value preserves original case. */
        char upper_key[ALF_MAX_KEY_LEN];
        snprintf(upper_key, sizeof(upper_key), "%s", key);
        str_toupper(upper_key);

        snprintf(out_msg->fields[idx].key,   sizeof(out_msg->fields[idx].key),   "%s", upper_key);
        snprintf(out_msg->fields[idx].value, sizeof(out_msg->fields[idx].value), "%s", value);
        idx++;
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
    if (!out || cap == 0 || !msg_type) return -1;

    int written = snprintf(out, cap, "%s", msg_type);
    if (written < 0 || (size_t)written >= cap) return -1;

    if (kv) {
        int i;
        for (i = 0; kv[i] && kv[i + 1]; i += 2) {
            int n = snprintf(out + written, cap - (size_t)written,
                             "|%s=%s", kv[i], kv[i + 1]);
            if (n < 0 || (size_t)(written + n) >= cap) return -1;
            written += n;
        }
    }

    if ((size_t)(written + 1) >= cap) return -1;
    out[written++] = '\n';
    out[written]   = '\0';
    return written;
}
