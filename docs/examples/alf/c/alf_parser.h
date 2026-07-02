#ifndef ALF_PARSER_H
#define ALF_PARSER_H

#include <stddef.h>

/* ------------------------------------------------------------------
 * ALF protocol parser and line builder.
 *
 * Wire format:
 *   VERB|KEY=VALUE|KEY=VALUE\n
 *
 * Keys and the verb are case-insensitive; parsed values preserve case.
 * Segments without '=' are silently skipped.
 * Duplicate keys: last value wins.
 * ------------------------------------------------------------------ */

#define ALF_MAX_FIELDS       64
#define ALF_MAX_KEY_LEN      64
#define ALF_MAX_VAL_LEN     512
#define ALF_MAX_MSGTYPE_LEN  32
#define ALF_MAX_LINE_LEN   4096

typedef struct {
    char key  [ALF_MAX_KEY_LEN];
    char value[ALF_MAX_VAL_LEN];
} alf_field_t;

typedef struct {
    char        msg_type   [ALF_MAX_MSGTYPE_LEN];
    int         field_count;
    alf_field_t fields     [ALF_MAX_FIELDS];
} alf_message_t;

/* alf_parse_line -- parse one mutable line (without trailing '\n').
 *
 * Modifies `line` in-place (strtok_r).  Returns 0 on success.
 * Negative return codes:
 *   -1  null argument
 *   -2  empty or pipe-only line
 *   -3  invalid message type characters
 *   -4  too many fields (> ALF_MAX_FIELDS)
 *   -5  field segment has no '='
 *
 * On -5 the segment is silently skipped and parsing continues;
 * the function still returns 0 when that is the only issue.
 */
int alf_parse_line(char *line, alf_message_t *out_msg);

/* alf_get_field -- return the value for `key`, or NULL when absent.
 *
 * Key comparison is case-insensitive.
 */
const char *alf_get_field(const alf_message_t *msg, const char *key);

/* alf_build_line -- write one ALF line into `out`.
 *
 * `kv` is a NULL-terminated array of alternating key/value C strings:
 *   const char *kv[] = {"SYM", "AAPL", "SIDE", "BUY", NULL};
 *   alf_build_line(buf, sizeof(buf), "NEW", kv);
 *   → "NEW|SYM=AAPL|SIDE=BUY\n"
 *
 * Pass kv=NULL or an array with only NULL for a bare-verb line.
 * Returns the number of bytes written (including '\n'), or -1 on overflow.
 */
int alf_build_line(char *out, size_t cap,
                   const char *msg_type,
                   const char * const *kv);

#endif /* ALF_PARSER_H */
