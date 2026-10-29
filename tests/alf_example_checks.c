#define main alf_example_main
#include "../docs/examples/alf/c/alf_client.c"
#undef main

#include <assert.h>

int main(void)
{
    alf_message_t msg;
    char duplicate[] = " ack | ORDER_ID = first |order_id=abc123|REASON=Mixed case ";
    assert(alf_parse_line(duplicate, &msg) == 0);
    assert(strcmp(alf_get_field(&msg, "ORDER_ID"), "abc123") == 0);
    assert(strcmp(alf_get_field(&msg, "reason"), "Mixed case") == 0);
    char bare[] = "INDEX|HISTORY|VALUE=1=2";
    assert(alf_parse_line(bare, &msg) == 0);
    assert(strcmp(alf_get_field(&msg, "VALUE"), "1=2") == 0);
    char no_verb[] = "|ORDER_ID=abc";
    assert(alf_parse_line(no_verb, &msg) < 0);

    char long_value[ALF_MAX_VAL_LEN + 32];
    memset(long_value, 'x', sizeof(long_value));
    memcpy(long_value, "ACK|REASON=", 11);
    long_value[sizeof(long_value) - 1] = '\0';
    assert(alf_parse_line(long_value, &msg) < 0);

    char out[128];
    const char *invalid[] = {"TAG", "bad|value", NULL};
    assert(alf_build_line(out, sizeof(out), "NEW", invalid) < 0);
    const char *newline[] = {"TAG", "bad\nvalue", NULL};
    assert(alf_build_line(out, sizeof(out), "NEW", newline) > 0);
    assert(strcmp(out, "NEW|TAG=bad value\n") == 0);

    update_position("AAPL", "BUY", 10, 100.0);
    update_position("AAPL", "SELL", 15, 110.0);
    assert(g_positions[0].net_qty == -5);
    assert(g_positions[0].avg_cost == 110.0);
    assert(g_positions[0].realized_pnl == 100.0);
    update_position("AAPL", "BUY", 6, 105.0);
    assert(g_positions[0].net_qty == 1);
    assert(g_positions[0].avg_cost == 105.0);
    assert(g_positions[0].realized_pnl == 125.0);

    use_color = 0;
    rl_initialize();
    char ack[] = "ACK|ORDER_ID=abc123|ACCEPTED=TRUE|SYMBOL=|SIDE=";
    assert(alf_parse_line(ack, &msg) == 0);
    handle_event(&msg);
    char fill[] = "FILL|ORDER_ID=abc123|SYMBOL=MSFT|SIDE=BUY|FILL_QTY=2|FILL_PRICE=25|REMAINING=0|STATUS=FILLED";
    assert(alf_parse_line(fill, &msg) == 0);
    handle_event(&msg);
    assert(strcmp(find_order("abc123")->status, "FILLED") == 0);
    assert(g_positions[1].net_qty == 2);
    assert(g_positions[1].avg_cost == 25.0);

    char cancel[] = "CANCELLED|ORDER_ID=abc123";
    assert(alf_parse_line(cancel, &msg) == 0);
    handle_event(&msg);
    assert(strcmp(find_order("abc123")->status, "CANCELLED") == 0);
    char expire[] = "EXPIRED|ORDER_ID=abc123";
    assert(alf_parse_line(expire, &msg) == 0);
    handle_event(&msg);
    assert(strcmp(find_order("abc123")->status, "EXPIRED") == 0);
    char dc[] = "DC_FILL|ORDER_ID=abc123|SYMBOL=MSFT|FILL_QTY=2|FILL_PRICE=25|SEQ=1|LIQUIDITY=MAKER";
    assert(alf_parse_line(dc, &msg) == 0);
    handle_event(&msg);
    assert(g_positions[1].net_qty == 2);

    int sockets[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    g_sockfd = sockets[0];
    const char *part1 = "SYMBOLS|COUNT=1\nSYMBOL|SYM=AA";
    assert(write(sockets[1], part1, strlen(part1)) == (ssize_t)strlen(part1));
    process_socket_data();
    assert(g_collecting == COL_SYMBOLS);
    const char *part2 = "PL|TICK=0.01\nEND|TYPE=ORDERS\n";
    assert(write(sockets[1], part2, strlen(part2)) == (ssize_t)strlen(part2));
    process_socket_data();
    assert(g_collecting == COL_SYMBOLS);
    assert(g_collect_count == 1);
    const char *end = "END|TYPE=SYMBOLS\n";
    assert(write(sockets[1], end, strlen(end)) == (ssize_t)strlen(end));
    process_socket_data();
    assert(g_collecting == COL_NONE);
    assert(g_nsymbols == 1 && strcmp(g_symbols[0], "AAPL") == 0);
    close(sockets[0]);
    close(sockets[1]);

    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    g_sockfd = sockets[0];
    const char *bad_welcome = "WELCOME|PROTO=ALF2|GW=test|ID=TRADER01|HBINT=1|IDLE=3\n";
    assert(write(sockets[1], bad_welcome, strlen(bad_welcome)) == (ssize_t)strlen(bad_welcome));
    assert(do_handshake(sockets[0], "TRADER01", "test") < 0);
    close(sockets[0]);
    close(sockets[1]);

    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    g_sockfd = sockets[0];
    const char *welcome = "HB|TS=now\nWELCOME|PROTO=ALF1|GW=test|ID=TRADER01|HBINT=1|IDLE=3\n";
    assert(write(sockets[1], welcome, strlen(welcome)) == (ssize_t)strlen(welcome));
    assert(do_handshake(sockets[0], "TRADER01", "test") == 0);
    assert(g_idle_sec == 3);
    close(sockets[0]);
    close(sockets[1]);
    puts("ALF C behavioral checks passed");
    return 0;
}
