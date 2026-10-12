import json, sys, statistics as st
def summ(name):
    rows = [json.loads(l) for l in open(f"/home/claude/aisim/rec/{name}/watch.jsonl")]
    c = [r for r in rows if r["phase"] == "CONTINUOUS"][4:]
    if not c:
        return f"{name}: no steady rows"
    m = lambda k: round(st.mean(r[k] for r in c if r.get(k) is not None), 3)
    s5 = [r["symbols_5min"] for r in c if r.get("symbols_5min")]
    return (f"{name:12s} n={len(c):2d} rms={m('rms')} med={m('median')} far2={m('far2')} "
            f"ret1m={m('ret1m_rms')} spread={m('spread_med')} trades={round(m('trades'))} "
            f"syms={round(m('symbols_traded'))} s5={s5} news={sum(r['news'] for r in c)} cpu={m('cpu_total')}")
for n in sys.argv[1:]:
    print(summ(n))
