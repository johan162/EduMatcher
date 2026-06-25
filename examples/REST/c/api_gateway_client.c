#include "api_gateway_client.h"

#include <arpa/inet.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

ApiGatewayClient api_gateway_client(const char *host, int port, const char *api_key) {
    ApiGatewayClient client = {host, port, api_key};
    return client;
}

static int connect_tcp(const char *host, int port) {
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    char service[16];
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    snprintf(service, sizeof(service), "%d", port);
    if (getaddrinfo(host, service, &hints, &result) != 0) {
        return -1;
    }
    int fd = -1;
    for (struct addrinfo *rp = result; rp != NULL; rp = rp->ai_next) {
        fd = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
        if (fd == -1) {
            continue;
        }
        if (connect(fd, rp->ai_addr, rp->ai_addrlen) == 0) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(result);
    return fd;
}

char *api_gateway_get(const ApiGatewayClient *client, const char *path) {
    int fd = connect_tcp(client->host, client->port);
    if (fd < 0) {
        return NULL;
    }

    char request[2048];
    int written = snprintf(
        request,
        sizeof(request),
        "GET %s HTTP/1.1\r\nHost: %s:%d\r\nAuthorization: Bearer %s\r\nAccept: application/json\r\nConnection: close\r\n\r\n",
        path,
        client->host,
        client->port,
        client->api_key
    );
    if (written <= 0 || (size_t)written >= sizeof(request)) {
        close(fd);
        return NULL;
    }
    if (send(fd, request, (size_t)written, 0) < 0) {
        close(fd);
        return NULL;
    }

    size_t cap = 8192;
    size_t len = 0;
    char *response = malloc(cap);
    if (response == NULL) {
        close(fd);
        return NULL;
    }
    for (;;) {
        if (len + 4096 + 1 > cap) {
            cap *= 2;
            char *grown = realloc(response, cap);
            if (grown == NULL) {
                free(response);
                close(fd);
                return NULL;
            }
            response = grown;
        }
        ssize_t n = recv(fd, response + len, 4096, 0);
        if (n <= 0) {
            break;
        }
        len += (size_t)n;
    }
    close(fd);
    response[len] = '\0';

    char *body = strstr(response, "\r\n\r\n");
    if (body == NULL) {
        return response;
    }
    body += 4;
    size_t body_len = strlen(body) + 1;
    char *copy = malloc(body_len);
    if (copy == NULL) {
        free(response);
        return NULL;
    }
    memcpy(copy, body, body_len);
    free(response);
    return copy;
}