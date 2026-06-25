#ifndef EDUMATCHER_API_GATEWAY_CLIENT_H
#define EDUMATCHER_API_GATEWAY_CLIENT_H

typedef struct ApiGatewayClient {
    const char *host;
    int port;
    const char *api_key;
} ApiGatewayClient;

ApiGatewayClient api_gateway_client(const char *host, int port, const char *api_key);
char *api_gateway_get(const ApiGatewayClient *client, const char *path);

#endif