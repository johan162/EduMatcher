#include "api_gateway_client.h"

#include <stdio.h>
#include <stdlib.h>

static void print_endpoint(const ApiGatewayClient *client, const char *path) {
    char *body = api_gateway_get(client, path);
    printf("\n%s\n", path);
    if (body == NULL) {
        printf("request failed\n");
        return;
    }
    printf("%s\n", body);
    free(body);
}

int main(void) {
    const char *key = getenv("EDUMATCHER_API_KEY");
    if (key == NULL) {
        key = "key-trader-demo";
    }
    ApiGatewayClient client = api_gateway_client("127.0.0.1", 8080, key);
    print_endpoint(&client, "/api/v1/status");
    print_endpoint(&client, "/api/v1/symbols");
    print_endpoint(&client, "/api/v1/session");
    return 0;
}