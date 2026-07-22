#ifndef EDUMATCHER_API_GATEWAY_CLIENT_H
#define EDUMATCHER_API_GATEWAY_CLIENT_H

/* Minimal POSIX-socket REST client for the EduMatcher API Gateway.
 *
 * `host` and `api_key` are stored as-is (not copied), so the strings
 * passed to api_gateway_client() must outlive the returned client, e.g.
 * string literals or storage with program lifetime.
 */
typedef struct ApiGatewayClient {
    const char *host;
    int port;
    const char *api_key;
} ApiGatewayClient;

ApiGatewayClient api_gateway_client(const char *host, int port, const char *api_key);

/* Issue a GET request for `path` and return the decoded response body.
 *
 * Returns NULL on any connection or protocol failure. On success, returns
 * a NUL-terminated, heap-allocated string that the caller owns and must
 * release with free().
 */
char *api_gateway_get(const ApiGatewayClient *client, const char *path);

#endif