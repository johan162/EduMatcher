/* Implementation of the CALF sequence/recovery helpers.
 *
 * See calf_recovery.h for the three rules this encodes and why each one
 * matters. Nothing here does I/O: the caller owns the socket and decides
 * what to do with the verdict.
 */

#include "calf_recovery.h"

#include <stdio.h>
#include <string.h>

static const char *const SNAPSHOT_CHANNELS[] = {"TOP", "STATE", "INDEX", "DEPTH", "CB", NULL};
static const char *const RESUMABLE_CHANNELS[] = {"TRADE", "AUCTION", NULL};

static int in_list(const char *const *list, const char *value) {
    if (!value) {
        return 0;
    }
    for (int i = 0; list[i] != NULL; i++) {
        if (strcmp(list[i], value) == 0) {
            return 1;
        }
    }
    return 0;
}

int calf_channel_has_snapshot(const char *channel) {
    return in_list(SNAPSHOT_CHANNELS, channel);
}

int calf_channel_is_resumable(const char *channel) {
    return in_list(RESUMABLE_CHANNELS, channel);
}

void calf_recovery_init(calf_recovery_t *rec) {
    if (!rec) {
        return;
    }
    memset(rec, 0, sizeof(*rec));
}

void calf_recovery_new_connection(calf_recovery_t *rec) {
    if (rec) {
        rec->generation++;
    }
}

static calf_stream_t *find_stream(calf_recovery_t *rec, const char *channel,
                                  const char *symbol) {
    for (int i = 0; i < rec->count; i++) {
        if (rec->streams[i].used && strcmp(rec->streams[i].channel, channel) == 0 &&
            strcmp(rec->streams[i].symbol, symbol) == 0) {
            return &rec->streams[i];
        }
    }
    return NULL;
}

static calf_stream_t *add_stream(calf_recovery_t *rec, const char *channel, const char *symbol,
                                 long seq) {
    if (rec->count >= CALF_MAX_TRACKED_STREAMS) {
        /* Table full: stop tracking new streams rather than evict a live
         * one, whose position is the only thing that can reveal a gap. */
        return NULL;
    }
    calf_stream_t *s = &rec->streams[rec->count++];
    snprintf(s->channel, sizeof(s->channel), "%s", channel);
    snprintf(s->symbol, sizeof(s->symbol), "%s", symbol);
    s->seq = seq;
    s->generation = rec->generation;
    s->hole_lo = 1; /* lo > hi: no outstanding hole */
    s->hole_hi = 0;
    s->used = 1;
    return s;
}

static void fill_gap(calf_gap_t *gap_out, const calf_stream_t *s, long first, long last) {
    if (!gap_out) {
        return;
    }
    snprintf(gap_out->channel, sizeof(gap_out->channel), "%s", s->channel);
    snprintf(gap_out->symbol, sizeof(gap_out->symbol), "%s", s->symbol);
    gap_out->first_seq = first;
    gap_out->last_seq = last;
}

calf_action_t calf_recovery_observe(calf_recovery_t *rec, const char *msg_type,
                                    const char *channel, const char *symbol, long seq,
                                    calf_gap_t *gap_out) {
    if (!rec || !channel || !channel[0] || seq <= 0) {
        return CALF_PROCESS;
    }
    if (!symbol) {
        symbol = "";
    }

    calf_stream_t *s = find_stream(rec, channel, symbol);
    if (!s) {
        /* The first message on a stream establishes the baseline. It is
         * never a gap, because there is nothing yet for it to be a gap in. */
        add_stream(rec, channel, symbol, seq);
        return CALF_PROCESS;
    }

    /* Rule 2: a SNAP re-baselines and is never a gap. */
    if (msg_type && strcmp(msg_type, "SNAP") == 0) {
        s->seq = seq;
        s->generation = rec->generation;
        s->hole_lo = 1;
        s->hole_hi = 0;
        return CALF_PROCESS;
    }

    if (seq <= s->seq) {
        /* Rule 3, across connections: a gateway that restarted numbers
         * this stream from 1 again. Adopting its numbering is the only
         * alternative to discarding the stream for as long as that process
         * lives. */
        if (s->generation != rec->generation) {
            s->seq = seq;
            s->generation = rec->generation;
            s->hole_lo = 1;
            s->hole_hi = 0;
            return CALF_PROCESS;
        }
        /* Rule 1: backfill inside the hole is wanted, anything else is a
         * duplicate. Either way the baseline stays put. Replay arrives in
         * sequence order, so everything below `seq` in this hole has
         * already been handed over and the range can advance past it. */
        if (seq >= s->hole_lo && seq <= s->hole_hi) {
            s->hole_lo = seq + 1;
            return CALF_PROCESS;
        }
        return CALF_DROP;
    }

    long previous = s->seq;
    s->seq = seq;
    s->generation = rec->generation;

    if (seq == previous + 1) {
        return CALF_PROCESS;
    }

    if (calf_channel_is_resumable(channel)) {
        s->hole_lo = previous + 1;
        s->hole_hi = seq - 1;
        fill_gap(gap_out, s, previous + 1, seq - 1);
        return CALF_RESUME;
    }

    /* A gap on a snapshot-baselined channel closes itself: the SUB that
     * follows every reconnect triggers a fresh SNAP, so whatever was missed
     * is superseded before anyone could act on knowing about it. */
    if (calf_channel_has_snapshot(channel)) {
        return CALF_PROCESS;
    }

    fill_gap(gap_out, s, previous + 1, seq - 1);
    return CALF_GAP_UNREPAIRABLE;
}

void calf_recovery_abandon(calf_recovery_t *rec, const char *channel, const char *symbol) {
    if (!rec || !channel) {
        return;
    }
    calf_stream_t *s = find_stream(rec, channel, symbol ? symbol : "");
    if (s) {
        s->hole_lo = 1;
        s->hole_hi = 0;
    }
}

long calf_recovery_position(const calf_recovery_t *rec, const char *channel,
                            const char *symbol) {
    if (!rec || !channel) {
        return -1;
    }
    for (int i = 0; i < rec->count; i++) {
        if (rec->streams[i].used && strcmp(rec->streams[i].channel, channel) == 0 &&
            strcmp(rec->streams[i].symbol, symbol ? symbol : "") == 0) {
            return rec->streams[i].seq;
        }
    }
    return -1;
}

int calf_recovery_build_resume(char *buf, unsigned long cap, const calf_gap_t *gap) {
    if (!buf || !gap || cap == 0) {
        return -1;
    }
    /* LASTSEQ is the position before the hole: the gateway replays
     * everything *past* it. */
    int written = snprintf(buf, cap, "RESUME|CH=%s|SYM=%s|LASTSEQ=%ld\n", gap->channel,
                           gap->symbol, gap->first_seq - 1);
    if (written < 0 || (unsigned long)written >= cap) {
        return -1;
    }
    return written;
}
