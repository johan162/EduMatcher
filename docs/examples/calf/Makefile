CC := cc
CFLAGS := -O2 -Wall -Wextra -std=c11 -D_POSIX_C_SOURCE=200809L

all: calf_subscriber

SRC := calf_subscriber.c calf_parser.c calf_recovery.c
HDR := calf_parser.h calf_recovery.h

calf_subscriber: $(SRC) $(HDR)
	$(CC) $(CFLAGS) -o calf_subscriber $(SRC)

# Self-test for the recovery helpers. They are pure functions over the
# sequence stream, so they can be exercised without a gateway.
calf_recovery_test: calf_recovery_test.c calf_recovery.c $(HDR)
	$(CC) $(CFLAGS) -o calf_recovery_test calf_recovery_test.c calf_recovery.c

test: calf_recovery_test
	./calf_recovery_test

clean:
	rm -f calf_subscriber calf_recovery_test

.PHONY: all clean test
