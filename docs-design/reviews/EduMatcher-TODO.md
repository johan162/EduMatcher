## TODO

1. the two circuit-breaker sweeps have no command_id, so their acks can't be told apart — the same problem risk.kill_switch had. I did not fix it. Unlike the note, both halves agree there: handlers read only gateway_id, builders send only gateway_id. That's a feature request, not a repair, and the test pins the contrast with the six per-symbol topics so it stays visible.

2. there is no surface for the kill-switch `note` in the messsage

