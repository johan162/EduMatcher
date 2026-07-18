#include "api_gateway_client.h"

#include <stdio.h>
#include <stdlib.h>

/* Returns 0 on success, 1 if the request failed (so callers can propagate
 * a non-zero process exit status, mirroring the Python example).
 */
static int print_endpoint(const ApiGatewayClient *client, const char *path) {
    char *body = api_gateway_get(client, path);
    printf("\n%s\n", path);
    if (body == NULL) {
        fprintf(stderr, "request failed: %s\n", path);
        return 1;
    }
    printf("%s\n", body);
    free(body);
    return 0;
}

int main(void) {
    const char *key = getenv("EDUMATCHER_API_KEY");
    if (key == NULL) {
        key = "key-trader-demo";
    }
    ApiGatewayClient client = api_gateway_client("127.0.0.1", 8080, key);

    int failed = 0;
    failed |= print_endpoint(&client, "/api/v1/status");
    failed |= print_endpoint(&client, "/api/v1/symbols");
    failed |= print_endpoint(&client, "/api/v1/session");
    return failed ? 1 : 0;
}