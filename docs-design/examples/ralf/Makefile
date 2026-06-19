CC := cc
CFLAGS := -O2 -Wall -Wextra -std=c11

all: ralf_subscriber

ralf_subscriber: ralf_subscriber.c ralf_parser.c ralf_parser.h
	$(CC) $(CFLAGS) -o ralf_subscriber ralf_subscriber.c ralf_parser.c

clean:
	rm -f ralf_subscriber

.PHONY: all clean
