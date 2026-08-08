/* Shared runtime for generated EduMatcher message bindings.
 *
 * Hand-written and committed - the C counterpart of
 * src/edumatcher/models/generated/_runtime.py, and the one file in this
 * directory that is NOT generated. Every generated family header includes it
 * rather than redeclaring these codes, so a client writes one error-handling
 * path for all of them.
 *
 * See docs-design/EduMatcher-Message-Generator.md section 5.2 and
 * docs/developer/06-msgen.md.
 */
#ifndef EDUMATCHER_MSG_H
#define EDUMATCHER_MSG_H

/* Return codes for generated parse/validate functions.
 *
 * -1..-5 mirror docs/examples/balf/balf_parser.c's parse_header/split_frame,
 * whose meanings the generated BALF parser reimplements exactly. -6 and -7 are
 * additions for field-level failures.
 *
 * IMPORTANT: a return code is a per-function contract, not a global registry.
 * docs/examples/calf/calf_parser.c's calf_parse_line independently returns
 * -1..-6 with entirely different meanings (-4 is "too many fields" there, not
 * "unknown msg_type"). Check each call's result against the function you
 * called, and print it with edu_msg_strerror only for functions declared in a
 * generated header.
 */
#define EDU_MSG_OK 0            /* success                                    */
#define EDU_MSG_ERR_SHORT (-1)  /* frame or line too short                    */
#define EDU_MSG_ERR_MAGIC (-2)  /* bad magic byte (binary only)               */
#define EDU_MSG_ERR_VERSION (-3) /* unsupported version (binary only)         */
#define EDU_MSG_ERR_MSGTYPE (-4) /* unknown or unexpected msg_type            */
#define EDU_MSG_ERR_LENGTH (-5) /* length mismatch for msg_type (binary only) */
#define EDU_MSG_ERR_FIELD (-6)  /* required field missing, unparseable, or a
                                 * declared validation rule failed            */
#define EDU_MSG_ERR_OVERFLOW (-7) /* value exceeds a fixed-size buffer        */

/* Human-readable text for a code above, or "unknown error" for anything else.
 *
 * Shared rather than generated per family: the codes do not vary by family, and
 * emitting an identical function into every generated header would be exactly
 * the duplication this generator exists to remove.
 */
const char *edu_msg_strerror(int rc);

#endif /* EDUMATCHER_MSG_H */
