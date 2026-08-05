/* Self-test for the CALF recovery helpers.
 *
 * They are pure functions over the sequence stream, so every rule they
 * encode can be checked without a gateway, a socket, or a clock. Build and
 * run with `make test`.
 */

#include "calf_recovery.h"

#include <stdio.h>
#include <string.h>

static int g_failures = 0;

static void check(int condition, const char *what) {
    if (condition) {
        printf("  ok   %s\n", what);
    } else {
        printf("  FAIL %s\n", what);
        g_failures++;
    }
}

static calf_action_t observe(calf_recovery_t *rec, const char *type, const char *sym, long seq,
                             calf_gap_t *gap) {
    return calf_recovery_observe(rec, type, "TRADE", sym, seq, gap);
}

static void test_baseline_and_consecutive(void) {
    printf("baseline and consecutive delivery\n");
    calf_recovery_t rec;
    calf_recovery_init(&rec);
    calf_recovery_new_connection(&rec);

    /* A first sighting has no baseline to have missed anything against,
     * whatever SEQ it starts at. */
    check(observe(&rec, "TRADE", "AAPL", 40, NULL) == CALF_PROCESS, "first message is never a gap");
    check(observe(&rec, "TRADE", "AAPL", 41, NULL) == CALF_PROCESS, "consecutive is not a gap");
    check(calf_recovery_position(&rec, "TRADE", "AAPL") == 41, "position tracks the newest SEQ");
    check(calf_recovery_position(&rec, "TRADE", "MSFT") == -1, "unseen stream has no position");
}

static void test_gap_triggers_resume(void) {
    printf("a gap on a resumable channel asks for replay\n");
    calf_recovery_t rec;
    calf_gap_t gap;
    calf_recovery_init(&rec);
    calf_recovery_new_connection(&rec);

    observe(&rec, "TRADE", "AAPL", 1, NULL);
    check(observe(&rec, "TRADE", "AAPL", 4, &gap) == CALF_RESUME, "1 -> 4 requests a RESUME");
    check(gap.first_seq == 2 && gap.last_seq == 3, "the hole is 2..3");

    char line[CALF_RESUME_LINE_LEN];
    int n = calf_recovery_build_resume(line, sizeof(line), &gap);
    /* LASTSEQ is the position *before* the hole: the gateway replays
     * everything past it. */
    check(n > 0 && strcmp(line, "RESUME|CH=TRADE|SYM=AAPL|LASTSEQ=1\n") == 0,
          "RESUME asks from LASTSEQ=1, not from the first missing SEQ");
}

static void test_replay_is_reconciled(void) {
    printf("replay: backfill is kept, duplicates are dropped\n");
    calf_recovery_t rec;
    calf_gap_t gap;
    calf_recovery_init(&rec);
    calf_recovery_new_connection(&rec);

    observe(&rec, "TRADE", "AAPL", 1, NULL);
    observe(&rec, "TRADE", "AAPL", 4, &gap); /* hole 2..3, RESUME|LASTSEQ=1 */

    /* The gateway replays everything past LASTSEQ=1, which is 2, 3 *and* 4
     * -- the message that revealed the gap and was already delivered. */
    check(observe(&rec, "TRADE", "AAPL", 2, NULL) == CALF_PROCESS, "backfill SEQ=2 is kept");
    check(observe(&rec, "TRADE", "AAPL", 3, NULL) == CALF_PROCESS, "backfill SEQ=3 is kept");
    check(observe(&rec, "TRADE", "AAPL", 4, NULL) == CALF_DROP, "replayed SEQ=4 is dropped");
    check(calf_recovery_position(&rec, "TRADE", "AAPL") == 4, "the baseline never moved backward");
    check(observe(&rec, "TRADE", "AAPL", 5, NULL) == CALF_PROCESS,
          "the next live message is not a phantom gap");
}

static void test_snapshot_rebaselines(void) {
    printf("a SNAP re-baselines and is never a gap\n");
    calf_recovery_t rec;
    calf_gap_t gap;
    calf_recovery_init(&rec);
    calf_recovery_new_connection(&rec);

    calf_recovery_observe(&rec, "SNAP", "TOP", "AAPL", 1, NULL);
    /* A jump on a snapshot-backed channel is not worth reporting: the SUB
     * after a reconnect triggers a fresh SNAP that supersedes it. */
    check(calf_recovery_observe(&rec, "MD", "TOP", "AAPL", 9, &gap) == CALF_PROCESS,
          "TOP gap is left for the next SNAP");
    /* The SNAP answering a REPLAY_MISS re-anchors wherever the gateway now
     * is. Gap-checking it would loop RESUME against a dead window. */
    check(calf_recovery_observe(&rec, "SNAP", "TOP", "AAPL", 9001, NULL) == CALF_PROCESS,
          "a SNAP far ahead is a baseline, not a gap");
    check(calf_recovery_position(&rec, "TOP", "AAPL") == 9001, "the SNAP moved the baseline");
    check(calf_recovery_observe(&rec, "MD", "TOP", "AAPL", 9002, &gap) == CALF_PROCESS,
          "the stream continues from the snapshot");
}

static void test_unrepairable_gap_reported(void) {
    printf("a gap with neither replay nor snapshot is surfaced\n");
    calf_recovery_t rec;
    calf_gap_t gap;
    calf_recovery_init(&rec);
    calf_recovery_new_connection(&rec);

    /* AUCTION is resumable, so pick a channel that is neither: an unknown
     * one stands in for any future channel with no baseline. */
    calf_recovery_observe(&rec, "XX", "XCHAN", "AAPL", 1, NULL);
    check(calf_recovery_observe(&rec, "XX", "XCHAN", "AAPL", 5, &gap) == CALF_GAP_UNREPAIRABLE,
          "reported rather than silently dropped");
    check(gap.first_seq == 2 && gap.last_seq == 4, "the reported hole is 2..4");
}

static void test_abandon_after_replay_miss(void) {
    printf("REPLAY_MISS closes the hole so nothing is mislabelled as backfill\n");
    calf_recovery_t rec;
    calf_gap_t gap;
    calf_recovery_init(&rec);
    calf_recovery_new_connection(&rec);

    observe(&rec, "TRADE", "AAPL", 1, NULL);
    observe(&rec, "TRADE", "AAPL", 9, &gap); /* hole 2..8 */
    calf_recovery_abandon(&rec, "TRADE", "AAPL");
    check(observe(&rec, "TRADE", "AAPL", 5, NULL) == CALF_DROP,
          "a late arrival in the abandoned range is not treated as backfill");
}

static void test_gateway_restart_adopted(void) {
    printf("a gateway restart renumbers rather than duplicates\n");
    calf_recovery_t rec;
    calf_recovery_init(&rec);
    calf_recovery_new_connection(&rec);

    observe(&rec, "TRADE", "AAPL", 5000, NULL);
    /* Same connection: backward means replay, and this is not in a hole. */
    check(observe(&rec, "TRADE", "AAPL", 1, NULL) == CALF_DROP,
          "backward within one connection is a duplicate");

    calf_recovery_new_connection(&rec);
    /* New connection: the gateway's counters live in its process, so
     * starting at 1 again means it restarted. Adopting is the only
     * alternative to blacking the stream out for that process's lifetime. */
    check(observe(&rec, "TRADE", "AAPL", 1, NULL) == CALF_PROCESS,
          "backward on a new connection adopts the new numbering");
    check(observe(&rec, "TRADE", "AAPL", 2, NULL) == CALF_PROCESS, "and continues from there");
}

static void test_unsequenced_passes_through(void) {
    printf("a message with no usable SEQ is passed through unsequenced\n");
    calf_recovery_t rec;
    calf_recovery_init(&rec);
    calf_recovery_new_connection(&rec);

    /* Baselining at zero would make the next real SEQ look like a gap and
     * produce RESUME|LASTSEQ=0, which the gateway rejects with
     * BAD_MESSAGE rather than REPLAY_MISS -- a hole nobody is told about. */
    check(observe(&rec, "TRADE", "AAPL", 0, NULL) == CALF_PROCESS, "SEQ=0 is not a position");
    check(calf_recovery_position(&rec, "TRADE", "AAPL") == -1, "and does not create a baseline");
    check(observe(&rec, "TRADE", "AAPL", 7, NULL) == CALF_PROCESS, "the next real SEQ baselines");
}

static void test_channel_predicates(void) {
    printf("channel classification\n");
    check(calf_channel_has_snapshot("TOP") && calf_channel_has_snapshot("CB"),
          "TOP and CB have a snapshot");
    check(!calf_channel_has_snapshot("TRADE") && !calf_channel_has_snapshot("AUCTION"),
          "TRADE and AUCTION have none");
    check(calf_channel_is_resumable("TRADE"), "TRADE is worth resuming");
    check(!calf_channel_is_resumable("TOP"), "TOP self-heals via SNAP");
}

static void test_streams_are_independent(void) {
    printf("streams are tracked independently\n");
    calf_recovery_t rec;
    calf_gap_t gap;
    calf_recovery_init(&rec);
    calf_recovery_new_connection(&rec);

    observe(&rec, "TRADE", "AAPL", 1, NULL);
    observe(&rec, "TRADE", "MSFT", 1, NULL);
    check(observe(&rec, "TRADE", "AAPL", 5, &gap) == CALF_RESUME, "AAPL's gap is AAPL's");
    check(observe(&rec, "TRADE", "MSFT", 2, NULL) == CALF_PROCESS, "MSFT is unaffected");
}

int main(void) {
    test_baseline_and_consecutive();
    test_gap_triggers_resume();
    test_replay_is_reconciled();
    test_snapshot_rebaselines();
    test_unrepairable_gap_reported();
    test_abandon_after_replay_miss();
    test_gateway_restart_adopted();
    test_unsequenced_passes_through();
    test_channel_predicates();
    test_streams_are_independent();

    if (g_failures) {
        printf("\n%d check(s) FAILED\n", g_failures);
        return 1;
    }
    printf("\nall checks passed\n");
    return 0;
}
