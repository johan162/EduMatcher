"""Run the tuning chapter's recipes one after another and record each.

recipes.py NAME [NAME ...] | all
Each recipe: a fresh data dir with its own engine/market_sim/swarm files and
ai-sim profile, real speed from simulated Monday 09:28, observed 16 minutes
(simwatch2.py), then stopped. Results: rec/<name>/watch.jsonl.
"""
import copy, os, shutil, signal, subprocess, sys, time
import yaml

EM = "/home/claude/em"
EX = f"{EM}/docs/examples/ref_data/s300-sim-setup"
BIN = "/home/claude/emv/bin"
BASE_PROFILE = yaml.safe_load(open("/home/claude/aisim/tmpinit/emo-config.yaml"))

def sim(f):
    def g(d):
        f(d); return d
    return g

def scale_vol(d, k):
    d["defaults"]["vol"] *= k
    for sec in d["sectors"].values():
        if "vol" in sec: sec["vol"] = round(sec["vol"] * k, 4)
    for s in d["symbols"].values():
        if "vol" in s: s["vol"] = round(s["vol"] * k, 4)

def no_news(d):
    d["news"].update(rate_symbol=0, rate_sector=0, rate_market=0)

RECIPES = {
    "calm": dict(sim=lambda d: (scale_vol(d, 0.5), d["defaults"].update(jump_rate=0),
                                [s.pop("jump_rate", None) for s in list(d["sectors"].values()) + list(d["symbols"].values())],
                                no_news(d)),
                 swarm=lambda s: s.update(budget=30)),
    "wild": dict(sim=lambda d: (scale_vol(d, 2.0), d["defaults"].update(jump_rate=0.2)),
                 swarm=lambda s: s["composition"].update({"trend-follower": 20, "scalper": 15, "market-taker": 8})),
    "inefficient": dict(swarm=lambda s: s["composition"].update({"value-investor": 5, "institutional": 2}), mm=None),
    "efficient": dict(swarm=lambda s: s["composition"].update({"value-investor": 40, "institutional": 15}), mm={"--anchor-sim": "0.5"}),
    "newsday": dict(sim=lambda d: d["news"].update(rate_symbol=60, rate_sector=3),
                    swarm=lambda s: s["composition"].update({"news-trader": 15})),
    "rumourmill": dict(sim=lambda d: d["news"].update(rate_symbol=60, rumour_share=0.7, rumour_confirm=0.5), mm=None),
    "auction": dict(swarm=lambda s: (s["composition"].update({"auction-player": 20}), s.update(budget=30))),
    "symmetric": dict(mmcmd=lambda c: [x for i, x in enumerate(c) if x not in ("--fade-ticks", "--fade-sec") and (i == 0 or c[i - 1] not in ("--fade-ticks", "--fade-sec"))],
                      mm={"--strategy": "symmetric"}),
    "final": dict(mmcmd=lambda c: [x for i, x in enumerate(c) if x not in ("--fade-ticks", "--fade-sec") and (i == 0 or c[i - 1] not in ("--fade-ticks", "--fade-sec"))],
                  mm={"--strategy": "symmetric"}, swarm=lambda s: s.update(budget=80)),
    "speed24": dict(mmcmd=lambda c: [x for i, x in enumerate(c) if x not in ("--fade-ticks", "--fade-sec") and (i == 0 or c[i - 1] not in ("--fade-ticks", "--fade-sec"))],
                    mm={"--strategy": "symmetric"}, swarm=lambda s: s.update(budget=80),
                    env={"EM_SPEED": "24", "EM_START": "2026-10-12T08:58"}, minutes=21),
    "soak": dict(mmcmd=lambda c: [x for i, x in enumerate(c) if x not in ("--fade-ticks", "--fade-sec") and (i == 0 or c[i - 1] not in ("--fade-ticks", "--fade-sec"))],
                 mm={"--strategy": "symmetric"}, swarm=lambda s: s.update(budget=80),
                 env={"EM_SPEED": "600", "EM_START": "2026-10-12T08:50"}, minutes=110),
    "newsday24": dict(sim=lambda d: d["news"].update(rate_symbol=60, rate_sector=3),
                      swarm=lambda s: s["composition"].update({"news-trader": 15}),
                      env={"EM_SPEED": "24", "EM_START": "2026-10-12T08:58"}, minutes=21),
    "rumourmill24": dict(sim=lambda d: d["news"].update(rumour_share=0.7, rumour_confirm=0.5), mm=None,
                         env={"EM_SPEED": "24", "EM_START": "2026-10-12T08:58"}, minutes=21),
    "nomm24": dict(mm=None, env={"EM_SPEED": "24", "EM_START": "2026-10-12T08:58"}, minutes=21),
    "auction24": dict(swarm=lambda s: (s["composition"].update({"auction-player": 20}), s.update(budget=30)),
                      env={"EM_SPEED": "24", "EM_START": "2026-10-12T08:58"}, minutes=21),
    "auction2": dict(swarm=lambda s: s["composition"].update({"auction-player": 20})),
    "passive-nocover": dict(mm={"--min-cover-qty": "1000000"}),
    "thin": dict(swarm=lambda s: s["symbols"].update(per_agent=5), mm={"--qty": "50"}),
}

def stop_all(entry_pid):
    try:
        os.kill(entry_pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    time.sleep(30)
    subprocess.run("pkill -f '[s]imwatch2.py'; for p in pm-ai-swarm multiprocessing.spawn pm-mm-bot pm-market-sim pm-alf-gwy pm-engine pm-scheduler pm-stats pm-clearing pm-audit pm-log-srv pm-md-gwy pm-ralf-gwy pm-dc-gwy pm-api-gwy pm-balf-gwy pm-index; do pkill -9 -f \"/home/claude/emv/bin/$p\"; done; true", shell=True)
    time.sleep(5)

def wait_quiet():
    """Never start while another exchange still holds the ports."""
    while subprocess.run(["pgrep", "-f", "/home/claude/emv/bin/pm-"], capture_output=True).returncode == 0:
        time.sleep(10)

def run(name, spec, minutes=16):
    wait_quiet()
    R = f"/home/claude/aisim/rec/{name}"
    shutil.rmtree(R, ignore_errors=True)
    custom = f"{R}/data/custom"
    os.makedirs(custom)
    shutil.copy(f"{EX}/engine_config.yaml", custom)
    msim = yaml.safe_load(open(f"{EX}/market_sim.yaml"))
    if "sim" in spec: spec["sim"](msim)
    yaml.safe_dump(msim, open(f"{custom}/market_sim.yaml", "w"), sort_keys=False)
    swarm = yaml.safe_load(open(f"{EX}/swarm.yaml"))
    swarm["budget"] = 80  # the adopted s300-sim base; a recipe may override
    if "swarm" in spec: spec["swarm"](swarm)
    yaml.safe_dump(swarm, open(f"{custom}/swarm.yaml", "w"), sort_keys=False)
    prof = copy.deepcopy(BASE_PROFILE)
    procs = prof["ai-sim"]["processes"]
    for p in procs:
        if p["name"] == "ai-swarm":
            p["command"] = ["pm-ai-swarm", "--swarm", f"{custom}/swarm.yaml", "--verbose"]
    for p in procs:  # the adopted base: a symmetric market maker
        if p["name"] == "mm-bot":
            c = p["command"]
            c = [x for i, x in enumerate(c) if x not in ("--fade-ticks", "--fade-sec") and (i == 0 or c[i - 1] not in ("--fade-ticks", "--fade-sec"))]
            c[c.index("--strategy") + 1] = "symmetric"
            p["command"] = c
    if "mm" in spec:
        if spec["mm"] is None:
            procs[:] = [p for p in procs if p["name"] != "mm-bot"]
        else:
            for p in procs:
                if p["name"] == "mm-bot":
                    if "mmcmd" in spec:
                        p["command"] = spec["mmcmd"](p["command"])
                    cmd = p["command"]
                    for flag, value in spec["mm"].items():
                        if flag in cmd:
                            cmd[cmd.index(flag) + 1] = value
                        else:
                            cmd += [flag, value]
    yaml.safe_dump(prof, open(f"{R}/data/emo-config.yaml", "w"), sort_keys=False)
    env = dict(os.environ, PATH=f"{BIN}:" + os.environ["PATH"], EDUMATCHER_DATA_DIR=f"{R}/data",
               TZ="Europe/Stockholm", EM_PROFILE="ai-sim", EM_RESTART_DEAD="1", EM_SPEED="1",
               EM_START="2026-10-12T09:28", EM_CONFIG_FILE=f"{custom}/engine_config.yaml")
    env.update(spec.get("env", {}))
    entry = subprocess.Popen(["bash", "deployment/docker/entrypoint.sh"], cwd=EM, env=env,
                             stdout=open(f"{R}/entrypoint.log", "w"), stderr=subprocess.STDOUT,
                             start_new_session=True)
    watch = subprocess.Popen([f"{BIN}/python", "/home/claude/aisim/simwatch2.py", f"{R}/watch.jsonl", str(minutes * 60)],
                             cwd=EM, env=env, stdout=open(f"{R}/watch.err", "w"), stderr=subprocess.STDOUT)
    watch.wait()
    stop_all(entry.pid)
    print(name, "done", time.strftime("%T"), flush=True)

names = list(RECIPES) if sys.argv[1:] == ["all"] else sys.argv[1:]
for n in names:
    run(n, RECIPES[n], RECIPES[n].get("minutes", 16))
