CC := gcc

# Default flags
CFLAGS := -O2 -Wall -Wextra -std=gnu11 -D_POSIX_C_SOURCE=200809L

# Readline detection
# On macOS, Homebrew readline provides full GNU readline (libedit on the system
# lacks rl_callback_handler_install). On Linux, install libreadline-dev.
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
    HOMEBREW_RL := $(shell brew --prefix readline 2>/dev/null)
    ifneq ($(HOMEBREW_RL),)
        READLINE_CFLAGS  := -I$(HOMEBREW_RL)/include
        READLINE_LDFLAGS := -L$(HOMEBREW_RL)/lib -lreadline
    else
        READLINE_CFLAGS  :=
        READLINE_LDFLAGS := -lreadline
    endif
else
    READLINE_CFLAGS  :=
    READLINE_LDFLAGS := -lreadline
endif

CFLAGS += $(READLINE_CFLAGS)
LDFLAGS := $(READLINE_LDFLAGS)

all: alf_client

alf_client: alf_client.c alf_parser.c alf_parser.h
	$(CC) $(CFLAGS) -o alf_client alf_client.c alf_parser.c $(LDFLAGS)

clean:
	rm -f alf_client

.PHONY: all clean
