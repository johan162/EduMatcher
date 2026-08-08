CC := cc
# ../generated holds the message bindings produced by pm-msgen from
# spec/messages/*.yaml, plus their shared runtime. See docs/developer/06-msgen.md.
GEN_DIR := ../generated
# -I. is explicit because the generated header includes "calf_parser.h", which
# lives here rather than beside it.
CFLAGS := -O2 -Wall -Wextra -std=c11 -D_POSIX_C_SOURCE=200809L -I. -I$(GEN_DIR)

all: calf_subscriber

GEN_SRC := $(GEN_DIR)/edumatcher_trade.c $(GEN_DIR)/edumatcher_msg.c
GEN_HDR := $(GEN_DIR)/edumatcher_trade.h $(GEN_DIR)/edumatcher_msg.h

SRC := calf_subscriber.c calf_parser.c calf_recovery.c $(GEN_SRC)
HDR := calf_parser.h calf_recovery.h $(GEN_HDR)

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
