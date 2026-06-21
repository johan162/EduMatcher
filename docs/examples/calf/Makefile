CC := cc
CFLAGS := -O2 -Wall -Wextra -std=c11 -D_POSIX_C_SOURCE=200809L

all: calf_subscriber

calf_subscriber: calf_subscriber.c calf_parser.c calf_parser.h
	$(CC) $(CFLAGS) -o calf_subscriber calf_subscriber.c calf_parser.c

clean:
	rm -f calf_subscriber

.PHONY: all clean
