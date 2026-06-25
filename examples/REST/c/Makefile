CC ?= cc
CFLAGS ?= -Wall -Wextra -std=c11

demo_info: demo_info.c api_gateway_client.c api_gateway_client.h
	$(CC) $(CFLAGS) -o demo_info demo_info.c api_gateway_client.c

clean:
	rm -f demo_info