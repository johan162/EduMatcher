CC := cc
CFLAGS := -O2 -Wall -Wextra -std=c11 -D_POSIX_C_SOURCE=200809L

all: dc_subscriber

dc_subscriber: dc_subscriber.c dc_parser.c dc_parser.h
	$(CC) $(CFLAGS) -o dc_subscriber dc_subscriber.c dc_parser.c

clean:
	rm -f dc_subscriber

.PHONY: all clean
