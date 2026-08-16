/* Shared runtime for generated EduMatcher message bindings.
 *
 * Hand-written and committed; see edumatcher_msg.h.
 */
#include "edumatcher_msg.h"

const char *edu_msg_strerror(int rc) {
    switch (rc) {
        case EDU_MSG_OK:
            return "ok";
        case EDU_MSG_ERR_SHORT:
            return "frame or line too short";
        case EDU_MSG_ERR_MAGIC:
            return "bad magic byte";
        case EDU_MSG_ERR_VERSION:
            return "unsupported protocol version";
        case EDU_MSG_ERR_MSGTYPE:
            return "unknown or unexpected msg_type";
        case EDU_MSG_ERR_LENGTH:
            return "frame length does not match msg_type";
        case EDU_MSG_ERR_FIELD:
            return "required field missing, unparseable, or failed validation";
        case EDU_MSG_ERR_OVERFLOW:
            return "value exceeds a fixed-size buffer";
        default:
            return "unknown error";
    }
}
