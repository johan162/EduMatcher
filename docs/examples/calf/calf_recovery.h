/* CALF sequence tracking, gap detection and replay reconciliation.
 *
 * This is the part of a CALF client that is easy to get subtly wrong, so it
 * is kept free of sockets, threads and timers: feed it the (msg_type, CH,
 * SYM, SEQ) of each inbound message and it tells you whether to process
 * that message and whether a RESUME should go out. You own the connection;
 * this owns the bookkeeping.
 *
 * Three rules drive everything here, all normative in
 * docs/user-guide/920-app-calf-protocol.md, "Reconnect behavior":
 *
 *   1. A replay is not disjoint from live traffic. RESUME|LASTSEQ=n returns
 *      *everything* the gateway still buffers past n, and n is your
 *      position from before the gap -- so the reply re-sends the message
 *      that revealed the gap, plus anything delivered live while the
 *      request was in flight. Replayed and live lines share one ordered
 *      connection, so a duplicate always arrives after its original. The
 *      per-stream hole range is what separates the backfill you actually
 *      want from a message you already handled. Without it a client either
 *      processes every trade twice or discards the repair it just asked
 *      for.
 *
 *   2. A SNAP re-baselines and is never a gap. It re-anchors the stream
 *      wherever the gateway now is. Gap-checking one would ask to replay
 *      history it just superseded -- and since REPLAY_MISS is answered
 *      with a SNAP on the snapshot-backed channels, would loop RESUME
 *      against a window already known to be too old.
 *
 *   3. A sequence never moves backward within one connection. Letting it
 *      turns the next ordinary message into a phantom gap, or hides a real
 *      one. Across connections it *can* move backward, and that means
 *      something different: a gateway restarted and began its counters
 *      again at 1. Call calf_recovery_new_connection() after each connect
 *      so the two can be told apart.
 *
 * Typical use:
 *
 *     calf_recovery_t rec;
 *     calf_recovery_init(&rec);
 *     ...
 *     calf_recovery_new_connection(&rec);          // after each connect
 *     ...
 *     calf_action_t act = calf_recovery_observe(&rec, msg.msg_type,
 *                                               ch, sym, seq, &gap);
 *     if (act == CALF_DROP) continue;              // replayed duplicate
 *     if (act == CALF_RESUME) {
 *         char line[CALF_RESUME_LINE_LEN];
 *         calf_recovery_build_resume(line, sizeof(line), &gap);
 *         send_line(fd, line);
 *     }
 *     // CALF_PROCESS, or after either of the above: use the message
 */

#ifndef CALF_RECOVERY_H
#define CALF_RECOVERY_H

/* Streams tracked at once. A client following more than this stops
 * tracking further new streams rather than failing; raise it if you
 * subscribe broadly with SYM=*. */
#ifndef CALF_MAX_TRACKED_STREAMS
#define CALF_MAX_TRACKED_STREAMS 256
#endif

#define CALF_RECOVERY_CH_LEN 16
#define CALF_RECOVERY_SYM_LEN 32
/* Comfortably fits "RESUME|CH=..|SYM=..|LASTSEQ=..\n". */
#define CALF_RESUME_LINE_LEN 128

/* What the caller should do with the message just observed. */
typedef enum {
    /* Use it. Nothing is outstanding. */
    CALF_PROCESS = 0,
    /* A duplicate the gateway replayed and you have already handled.
     * Discard it -- acting on it a second time is the whole problem. */
    CALF_DROP = 1,
    /* Use it, and send the RESUME described by the out-parameter: a hole
     * was found on a channel that can be replayed. */
    CALF_RESUME = 2,
    /* Use it, but the hole cannot be repaired -- either the channel has no
     * replay path, or it has no snapshot to fall back on. Surface it: a
     * record with an unmarked hole is worse than one that admits it. */
    CALF_GAP_UNREPAIRABLE = 3
} calf_action_t;

/* A hole in one stream. `first_seq`..`last_seq` are inclusive. */
typedef struct {
    char channel[CALF_RECOVERY_CH_LEN];
    char symbol[CALF_RECOVERY_SYM_LEN];
    long first_seq;
    long last_seq;
} calf_gap_t;

typedef struct {
    char channel[CALF_RECOVERY_CH_LEN];
    char symbol[CALF_RECOVERY_SYM_LEN];
    long seq;
    int generation;
    /* Outstanding hole, inclusive. hole_lo > hole_hi means "none". */
    long hole_lo;
    long hole_hi;
    int used;
} calf_stream_t;

typedef struct {
    calf_stream_t streams[CALF_MAX_TRACKED_STREAMS];
    int count;
    int generation;
} calf_recovery_t;

/* Zero the tracker. Call once before use. */
void calf_recovery_init(calf_recovery_t *rec);

/* Note that a fresh connection was established.
 *
 * Stream positions are deliberately *kept*: the gateway's counters live in
 * its process, not the socket, so the value from before a drop is exactly
 * what reveals whether the drop cost anything. Clearing them would make
 * every reconnect look gap-free by definition. Only the generation moves,
 * which is what lets a restarted gateway's renumbering be told apart from
 * a replayed duplicate. */
void calf_recovery_new_connection(calf_recovery_t *rec);

/* Account for one inbound message.
 *
 * `msg_type` is the CALF message type ("SNAP", "MD", "TRADE", ...);
 * `channel` and `symbol` are the CH and SYM fields; `seq` is SEQ. A `seq`
 * of 0 or less means the field was absent or unparseable rather than a
 * position, and the message passes through unsequenced -- baselining at
 * zero would make the next real sequence look like a gap and produce a
 * RESUME|LASTSEQ=0, which the gateway rejects with BAD_MESSAGE rather than
 * REPLAY_MISS, leaving a hole nobody is told about.
 *
 * `gap_out` may be NULL if you do not care about the detail; it is filled
 * only when the return value is CALF_RESUME or CALF_GAP_UNREPAIRABLE. */
calf_action_t calf_recovery_observe(calf_recovery_t *rec, const char *msg_type,
                                    const char *channel, const char *symbol, long seq,
                                    calf_gap_t *gap_out);

/* Give up on repairing a stream's outstanding hole.
 *
 * Call on ERR|CODE=REPLAY_MISS: nothing is coming to fill it, and a range
 * left open would mislabel a later redelivery as backfill. */
void calf_recovery_abandon(calf_recovery_t *rec, const char *channel, const char *symbol);

/* Highest sequence seen on a stream, or -1 if it has never been seen. */
long calf_recovery_position(const calf_recovery_t *rec, const char *channel,
                            const char *symbol);

/* Write "RESUME|CH=..|SYM=..|LASTSEQ=..\n" for `gap` into `buf`.
 *
 * LASTSEQ is the position *before* the hole, which is what the gateway
 * replays from. Returns the number of bytes written, or a negative value
 * if the buffer was too small. */
int calf_recovery_build_resume(char *buf, unsigned long cap, const calf_gap_t *gap);

/* Whether a REPLAY_MISS on this channel is followed by a fresh SNAP.
 *
 * True for TOP, STATE, INDEX, DEPTH and CB. False for TRADE and AUCTION:
 * those carry discrete events, and there is no snapshot of a print that
 * already happened, so a gap there is permanent once it ages out. */
int calf_channel_has_snapshot(const char *channel);

/* Whether a gap on this channel is worth a RESUME.
 *
 * False for the snapshot-backed channels, whose gaps close themselves --
 * the SUB that follows a reconnect triggers a fresh baseline, so replaying
 * them would only re-send data that baseline is about to supersede. */
int calf_channel_is_resumable(const char *channel);

#endif /* CALF_RECOVERY_H */
