"""Observe a running simulation; one JSON line a minute.

simwatch.py OUT.jsonl SECONDS
Per minute: symbols traded, RMS and median |ln(mid/value)|, share > 2 %,
trades, CPU % and RSS MB per process (summed by program name), disk use of
the data directory, and the swarm's latest status line.
"""
import json, math, os, re, statistics, subprocess, sys, time
from collections import defaultdict
import zmq
from edumatcher.config import ENGINE_PUB_ADDR, SIM_PUB_ADDR
from edumatcher.messaging.bus import get_context
from edumatcher.models.message import decode

out, duration = sys.argv[1], float(sys.argv[2])
data = os.environ["EDUMATCHER_DATA_DIR"]
TICK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")

def procs():
    res = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
            st = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
            rss = int(open(f"/proc/{pid}/statm").read().split()[1]) * PAGE
        except OSError:
            continue
        name = next((os.path.basename(c.decode()) for c in cmd if b"/pm-" in c or c.startswith(b"pm-")), None)
        if name is None and any(b"multiprocessing" in c for c in cmd):
            name = "swarm-worker"
        if name:
            res[pid] = (name, int(st[11]) + int(st[12]), rss)
    return res

def disk():
    return int(subprocess.run(["du", "-sb", data], capture_output=True, text=True).stdout.split()[0])

s = get_context().socket(zmq.SUB)
s.connect(ENGINE_PUB_ADDR); s.connect(SIM_PUB_ADDR)
for t in (b"book.", b"trade.executed", b"sim.value", b"session.state", b"news."):
    s.setsockopt(zmq.SUBSCRIBE, t)
mid, val, spread, prev_mid = {}, {}, {}, {}
traded, trades, phase, news = set(), 0, None, 0
window5, minute = set(), 0
p0, t0 = procs(), time.time()
end = t0 + duration
with open(out, "a") as f:
    while time.time() < end:
        if s.poll(200):
            topic, p = decode(s.recv_multipart())
            if topic.startswith("book."):
                b, a = p.get("bids") or [], p.get("asks") or []
                if b and a:
                    bb, aa = float(b[0]["price"]), float(a[0]["price"])
                    mid[topic[5:]] = (bb + aa) / 2
                    spread[topic[5:]] = aa / bb - 1
            elif topic == "trade.executed":
                traded.add(p["symbol"]); window5.add(p["symbol"]); trades += 1
            elif topic == "sim.value":
                for x in p["values"]:
                    val[x["symbol"]] = x["value"]
            elif topic == "session.state":
                phase = p.get("state")
            elif topic.startswith("news."):
                news += 1
        now = time.time()
        if now - t0 >= 60:
            p1 = procs()
            cpu, rss = defaultdict(float), defaultdict(float)
            for pid, (name, ticks, mem) in p1.items():
                if pid in p0 and p0[pid][0] == name:
                    cpu[name] += (ticks - p0[pid][1]) / TICK / (now - t0) * 100
                rss[name] += mem / 2**20
            g = [math.log(mid[k] / val[k]) for k in mid if k in val]
            r1 = [math.log(mid[k] / prev_mid[k]) for k in mid if k in prev_mid]
            prev_mid = dict(mid)
            swarm = ""
            try:
                emo = os.path.join(data, "emo")
                logs = [os.path.join(dp, fn) for dp, _, fs in os.walk(emo) for fn in fs if "swarm" in fn]
                for path in logs:
                    lines = [l for l in open(path, errors="ignore") if " t=" in l and "actions=" in l]
                    if lines:
                        swarm = lines[-1].strip()[-160:]
            except OSError:
                pass
            minute += 1
            row = dict(wall=round(now), phase=phase, symbols_traded=len(traded), symbols_5min=(len(window5) if minute % 5 == 0 else None), trades=trades, news=news,
                       n_gap=len(g),
                       rms=round(math.sqrt(statistics.fmean(x * x for x in g)) * 100, 3) if g else None,
                       median=round(statistics.median(abs(x) for x in g) * 100, 3) if g else None,
                       far2=sum(abs(x) > 0.02 for x in g),
                       ret1m_rms=round(math.sqrt(statistics.fmean(x * x for x in r1)) * 100, 3) if r1 else None,
                       spread_med=round(statistics.median(spread.values()) * 100, 3) if spread else None,
                       cpu={k: round(v, 1) for k, v in sorted(cpu.items())}, cpu_total=round(sum(cpu.values()), 1),
                       rss={k: round(v) for k, v in sorted(rss.items())}, rss_total=round(sum(rss.values())),
                       disk_mb=round(disk() / 2**20, 1), swarm=swarm)
            f.write(json.dumps(row) + "\n"); f.flush()
            if minute % 5 == 0:
                window5 = set()
            traded, trades, news, p0, t0 = set(), 0, 0, p1, now
