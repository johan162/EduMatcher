/*
 * implied_fanout_benchmark.c
 *
 * Measures how long a matching engine needs to recalculate first-generation
 * implied quotes after one book side changes, for a 12-month futures strip
 * with every calendar spread listed (12 outright + 66 spread = 78 books).
 *
 * The results are the latency table and figure in "What one book change
 * costs", in src/02-orders-and-matching/
 * 13-implied-orders-and-synthetic-liquidity.md. The figure's values are
 * copied by hand into LATENCY in gen_implied_fanout_figures.py.
 *
 * BUILD AND RUN (x86-64 Linux, GCC or Clang)
 *
 *     gcc -O2 -march=native -Wall -Wextra -o /tmp/implied_fanout \
 *         scripts/implied_fanout_benchmark.c
 *     taskset -c 6 /tmp/implied_fanout
 *
 * Pin to one otherwise idle core. A full run takes about four minutes.
 *
 * THE MODEL
 *
 * The strip is a graph, as in the multi-layer implied orders chapter. Node 0
 * is cash ($) and nodes 1..12 are the months. Each book side is one directed
 * edge, so 78 books give 156 edges:
 *
 *     outright ask    $ -> month    cost = +ask
 *     outright bid    month -> $    cost = -bid
 *     spread ask      far -> near   cost = +ask
 *     spread bid      near -> far   cost = -bid
 *
 * Every ladder is therefore sorted by ascending cost, and all six formulas of
 * the chapter become one rule: the implied quote for u -> v combines
 * u -> k with k -> v, at cost(u -> k) + cost(k -> v), for an intermediate
 * node k. Each k is one "route", and routes into one target never share an
 * order, so their quantities can be added at equal prices.
 *
 * Two implication scopes are measured:
 *
 *     IN+OUT     Outright targets use all 11 routes, spread targets only the
 *                route through $ (implied IN). 396 route computations.
 *     IN+OUT+SS  Also spread-from-spread: every target uses all 11 routes.
 *                1,716 route computations.
 *
 * Each scenario combines one value from each of these:
 *
 *     scope      IN+OUT or IN+OUT+SS
 *     recalc     dirty (only quotes depending on the changed side) or all
 *     depth      implied levels kept per quote: 1 or 2
 *     event      the changed book is an outright or a spread
 *     cache      warm, or cold (L1 and L2 evicted before each event)
 *
 * OUTPUT COLUMNS
 *
 *     quotes     implied quotes recalculated per event
 *     pairs      route computations per event (an upper bound on work,
 *                because a route stops once it cannot improve the quote)
 *     mean, p50, p99, p99.9
 *                recalculation time in nanoseconds, timer overhead removed
 *
 * WHAT IS NOT MEASURED
 *
 * Only the recalculation is timed. Order validation, matching, persistence,
 * order-level ingredient lists, tick rounding and market-data encoding are
 * excluded, and prices are synthetic. Results depend on CPU, clock and system
 * noise. On a core that is not isolated, p99.9 mostly shows interrupts.
 */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <x86intrin.h>

enum {
    NODES = 13,            /* $ plus 12 months */
    EDGES = NODES * (NODES - 1), /* 156 book sides */
    MAX_ROUTES = NODES - 2,      /* intermediate nodes for one target */
    BOOK_LEVELS = 5,       /* aggregated price levels held per book side */
    MAX_DEPTH = 2,         /* implied levels published per quote */
    MAX_BEST_GAP = 4,      /* furthest the best price may move ahead of level 2 */
    WARM_EVENTS = 1000000,
    COLD_EVENTS = 60000,
    CACHE_LINE = 64,
};

/* Large enough to displace this CPU's 1 MiB L2 and the 32 KiB L1. */
#define EVICT_BYTES (4u << 20)

typedef struct { int64_t px, qty; } Level;
typedef struct { Level level[BOOK_LEVELS]; int n; } __attribute__((aligned(CACHE_LINE))) Ladder;
typedef struct { Level level[MAX_DEPTH]; int n; } Quote;
typedef struct { uint16_t first, second; } Route;

typedef struct {
    int spread_from_spread;
    int dirty_only;
    int depth;
    int spread_event;
    int cold;
} Scenario;

static Ladder books[EDGES];
static Quote quotes[EDGES];
static int edge_id[NODES][NODES], edge_from[EDGES], edge_to[EDGES];
static Route routes[EDGES][MAX_ROUTES];
static int route_count[EDGES];
static uint16_t dependants[EDGES][EDGES];
static int dependant_count[EDGES];
static uint32_t samples[WARM_EVENTS];
static volatile uint8_t *evict_buffer;

/* xorshift64: fast and deterministic, so runs use the same event sequence. */
static uint64_t rng_state = 0x9E3779B97F4A7C15ULL;

static inline uint32_t rnd(void)
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return (uint32_t)(rng_state >> 16);
}

static inline int is_outright(int edge)
{
    return edge_from[edge] == 0 || edge_to[edge] == 0;
}

static void number_edges(void)
{
    int edge = 0;
    for (int u = 0; u < NODES; u++) {
        for (int v = 0; v < NODES; v++) {
            if (u == v)
                continue;
            edge_id[u][v] = edge;
            edge_from[edge] = u;
            edge_to[edge] = v;
            edge++;
        }
    }
}

/* The generated RECALC and ON_CHANGE tables of the chapter. */
static void build_tables(int spread_from_spread)
{
    memset(route_count, 0, sizeof route_count);
    memset(dependant_count, 0, sizeof dependant_count);
    for (int target = 0; target < EDGES; target++) {
        int u = edge_from[target], v = edge_to[target];
        for (int k = 0; k < NODES; k++) {
            if (k == u || k == v)
                continue;
            if (!spread_from_spread && !is_outright(target) && k != 0)
                continue;
            int first = edge_id[u][k], second = edge_id[k][v];
            routes[target][route_count[target]++] = (Route){first, second};
            dependants[first][dependant_count[first]++] = target;
            dependants[second][dependant_count[second]++] = target;
        }
    }
}

/* Merge one level into a quote. Returns 0 if it is worse than all kept levels. */
static inline int add_level(Quote *quote, int depth, int64_t px, int64_t qty)
{
    for (int i = 0; i < quote->n; i++) {
        if (quote->level[i].px == px) {
            quote->level[i].qty += qty;
            return 1;
        }
        if (px < quote->level[i].px) {
            int last = quote->n < depth ? quote->n++ : depth - 1;
            for (int j = last; j > i; j--)
                quote->level[j] = quote->level[j - 1];
            quote->level[i] = (Level){px, qty};
            return 1;
        }
    }
    if (quote->n < depth) {
        quote->level[quote->n++] = (Level){px, qty};
        return 1;
    }
    return 0;
}

/* The chapter's pair(): walk two ladders best first, consuming from both. */
static inline void pair_route(const Ladder *a, const Ladder *b, Quote *quote, int depth)
{
    int i = 0, j = 0;
    int64_t a_left = a->level[0].qty, b_left = b->level[0].qty;

    while (i < a->n && j < b->n) {
        int64_t qty = a_left < b_left ? a_left : b_left;
        if (!add_level(quote, depth, a->level[i].px + b->level[j].px, qty))
            break;
        a_left -= qty;
        b_left -= qty;
        if (a_left == 0 && ++i < a->n)
            a_left = a->level[i].qty;
        if (b_left == 0 && ++j < b->n)
            b_left = b->level[j].qty;
    }
}

static inline void recalc_quote(int target, int depth)
{
    Quote quote = {.n = 0};
    for (int r = 0; r < route_count[target]; r++) {
        const Route route = routes[target][r];
        pair_route(&books[route.first], &books[route.second], &quote, depth);
    }
    quotes[target] = quote;
}

static inline void recalc_after_change(int edge, const Scenario *s)
{
    if (s->dirty_only) {
        for (int d = 0; d < dependant_count[edge]; d++)
            recalc_quote(dependants[edge][d], s->depth);
    } else {
        for (int target = 0; target < EDGES; target++)
            recalc_quote(target, s->depth);
    }
}

/* Consistent month prices plus a small edge, so routes often tie or nearly tie. */
static void seed_books(void)
{
    int64_t node_price[NODES] = {0};
    for (int i = 1; i < NODES; i++)
        node_price[i] = 7500 + 20 * i + rnd() % 8;

    for (int edge = 0; edge < EDGES; edge++) {
        int64_t cost = node_price[edge_to[edge]] - node_price[edge_from[edge]] + 1 + rnd() % 4;
        books[edge].n = BOOK_LEVELS;
        for (int l = 0; l < BOOK_LEVELS; l++) {
            books[edge].level[l] = (Level){cost, 1 + rnd() % 200};
            cost += 1 + rnd() % 3;
        }
    }
}

/* One event: a new quantity on a level and, one time in four, a best-price tick. */
static inline void apply_event(int edge)
{
    Ladder *book = &books[edge];
    book->level[rnd() % BOOK_LEVELS].qty = 1 + rnd() % 200;

    if (rnd() % 4 == 0) {
        int64_t worst = book->level[1].px - 1;
        int64_t best = book->level[1].px - MAX_BEST_GAP;
        int64_t px = book->level[0].px + ((rnd() & 1) ? 1 : -1);
        book->level[0].px = px > worst ? worst : px < best ? best : px;
    }
}

static inline int random_event_edge(int spread_event)
{
    int edge;
    do
        edge = rnd() % EDGES;
    while (is_outright(edge) == spread_event);
    return edge;
}

static void evict_caches(void)
{
    for (size_t i = 0; i < EVICT_BYTES; i += CACHE_LINE)
        (void)evict_buffer[i];
}

/* Serialised timestamp reads, so the measured code cannot leak past them. */
static inline uint64_t timer_start(void)
{
    _mm_lfence();
    uint64_t t = __rdtsc();
    _mm_lfence();
    return t;
}

static inline uint64_t timer_stop(void)
{
    unsigned aux;
    uint64_t t = __rdtscp(&aux);
    _mm_lfence();
    return t;
}

static double elapsed_ns(const struct timespec *a, const struct timespec *b)
{
    return (b->tv_sec - a->tv_sec) * 1e9 + (b->tv_nsec - a->tv_nsec);
}

static double measure_tsc_ghz(void)
{
    struct timespec start, now;
    clock_gettime(CLOCK_MONOTONIC, &start);
    uint64_t t0 = __rdtsc();
    do
        clock_gettime(CLOCK_MONOTONIC, &now);
    while (elapsed_ns(&start, &now) < 2e8);
    return (__rdtsc() - t0) / elapsed_ns(&start, &now);
}

static uint64_t measure_timer_overhead(void)
{
    uint64_t best = UINT64_MAX;
    for (int i = 0; i < 100000; i++) {
        uint64_t a = timer_start(), b = timer_stop();
        if (b - a < best)
            best = b - a;
    }
    return best;
}

static int compare_samples(const void *x, const void *y)
{
    uint32_t a = *(const uint32_t *)x, b = *(const uint32_t *)y;
    return (a > b) - (a < b);
}

static void run_scenario(const Scenario *s, double ghz, uint64_t overhead)
{
    int events = s->cold ? COLD_EVENTS : WARM_EVENTS;
    int quotes_per_event = EDGES;
    long pairs_per_event = 0;
    double total = 0;

    seed_books();
    for (int target = 0; target < EDGES; target++)
        recalc_quote(target, s->depth);

    for (int i = 0; i < events; i++) {
        int edge = random_event_edge(s->spread_event);
        apply_event(edge);
        if (s->cold)
            evict_caches();

        uint64_t start = timer_start();
        recalc_after_change(edge, s);
        uint64_t ticks = timer_stop() - start;

        ticks = ticks > overhead ? ticks - overhead : 0;
        samples[i] = (uint32_t)ticks;
        total += ticks;

        if (i == 0) {
            if (s->dirty_only) {
                quotes_per_event = dependant_count[edge];
                for (int d = 0; d < quotes_per_event; d++)
                    pairs_per_event += route_count[dependants[edge][d]];
            } else {
                for (int target = 0; target < EDGES; target++)
                    pairs_per_event += route_count[target];
            }
        }
    }

    qsort(samples, events, sizeof samples[0], compare_samples);
    printf("%-9s %-6s %-5d %-8s %-5s %6d %6ld %8.0f %8.0f %8.0f %8.0f\n",
           s->spread_from_spread ? "IN+OUT+SS" : "IN+OUT",
           s->dirty_only ? "dirty" : "all", s->depth,
           s->spread_event ? "spread" : "outright", s->cold ? "cold" : "warm",
           quotes_per_event, pairs_per_event, total / events / ghz,
           samples[events / 2] / ghz,
           samples[(int)(events * 0.99)] / ghz,
           samples[(int)(events * 0.999)] / ghz);
    fflush(stdout);
}

int main(void)
{
    number_edges();
    evict_buffer = aligned_alloc(CACHE_LINE, EVICT_BYTES);
    memset((void *)evict_buffer, 1, EVICT_BYTES);

    double ghz = measure_tsc_ghz();
    uint64_t overhead = measure_timer_overhead();
    printf("TSC %.3f GHz, timer overhead %.1f ns, times in ns\n", ghz, overhead / ghz);
    printf("%-9s %-6s %-5s %-8s %-5s %6s %6s %8s %8s %8s %8s\n", "scope", "recalc",
           "depth", "event", "cache", "quotes", "pairs", "mean", "p50", "p99", "p99.9");

    for (int sfs = 0; sfs <= 1; sfs++) {
        build_tables(sfs);
        for (int dirty = 0; dirty <= 1; dirty++)
            for (int depth = 1; depth <= MAX_DEPTH; depth++)
                for (int spread = 0; spread <= 1; spread++)
                    for (int cold = 0; cold <= 1; cold++)
                        run_scenario(&(Scenario){sfs, dirty, depth, spread, cold}, ghz, overhead);
    }
    free((void *)evict_buffer);
    return 0;
}
