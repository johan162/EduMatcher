# EduMatcher — Improving existing GUI Application for coherence and usability


This design document will record ideas hoe to align the fve different GUI applications
1. **pm-log** - The log server
2. **pm-trader** - The trading plaform 
3. **pm-terminal** - The "Tapedeck" info terminal
4. **pm-dash** - Operator dashbaóard
5. **pm-book** - The order book viewer

Started: —

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 1 | WP-UI01 | Add Session state and time to next states | - | 0.5 d | ☐ | |
| 1 | WP-UI02 | Add tooltip and better help text  | - | 0.5 d | ☐ | |



## Workpackages

### WP-UI01 - Add Session state and time to next states


In `pm-trader` top-row there is a highlighted current sessions state with the next state indicated as well as the
time left until state-changes, 
The format used is

```
<CURRENT STATE>  ->  <NEXT STATE> in <TIME TO STATE CHANGE>  <CURRENT TIME>
```

For example

```
CONTINUES -> Closing Auction in 03:08.23  12:51:37
```

The same indication, using identical color schema and fonts should be added to

   | GUI App   | Position  | WP Step | 
|-----------|-----------|---------|
| pm-dash   | Top row   |  WP-UI01.1       |
| pm-terminal | Bottom status row | WP-UI01.2 |
| pm-book  | Top row | WP-UI01.3 |
| pm-log  | Top row | WP-UI01.4 |  

If the exchange is started outside traing hours and before the proper states has been determined the stae should be shown
as "UNKNOWN" usually just takes a second or two to resolve. See `pm-trader` logic for fetching current and next state.

### WP-UI02 - Add tooltip and better help text 

As an educational tool we need to have explanation readily available to columns and data fields 
that are not obvious

1. **WP-UI02.1**: pm-log On the dashboard page the fields "total events", "error rate", "warnings", "processes", "log server"
should be tooltipped. 
2. **WP-UI02.2**: pm-log. BUG 1: When the log-srv is shut dow the "log server" still shows "UP" 
3. **WP-UI02.3**: pm-dash. The columns header in the second dashboard row that shows a table of processes needs explanation vy a tooltip (perhaps a separate circled "i" to be clicked)
4. **WP-UI02.4**: pm-trader. The current help text (top right corner "?") is too compact. Each order type needs a much more extensive and formatted description.