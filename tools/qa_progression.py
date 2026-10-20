"""6개 체제 × 3개 판도: 위인·기술·수복·대기열·재해·저장을 섞는 재현 가능한 퍼저."""
import argparse
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from korciv.game import Game
from korciv.state import Settings
from korciv import config as C, metro as M
from korciv.leaders import POLICIES
from korciv.progression import TECHS, GREAT_PEOPLE
import qa_fuzz as Q


def run(seed, mode, gov, turns):
    rng = random.Random(seed)
    g = Game(Settings(seed=seed, mode=mode, player_start="S002", ai_starts=["N001"],
                      n_enemies=1, player_leader="cus", ai_leaders=["cus"],
                      victories=("time",), max_turns=1000))
    g.set_player_government(gov)
    g.factions[1].is_ai = False
    sel = sorted(M.distances(g, "S002", 2), key=lambda r: (r != "S002", r))[:12]
    for rid in sel:
        if g.regions[rid].owner != 0:
            g.transfer_region(rid, 0, reason="편입")
        r = g.regions[rid]
        r.pop, r.happy = 12, 20
        r.b.update(admin=3, edu=4, housing=5, factory=3, bank=3, academy=1, specialty=3 if g.info(rid).specialty else 0)
    g.player.admin = g.player.sci_points = 1e6
    g.player.money = g.player.res["food"] = 1e8
    for _ in range(5):
        assert g.unlock_policy(0)[0]
    saves = actions = captures = 0
    for turn in range(turns):
        key = rng.choice(list(TECHS))
        g.unlock_tech(0, key)
        rid = rng.choice(sel)
        rr = g.regions[rid]
        if rr.owner == 0:
            for _ in range(2):
                opts = [o for o in g.options(0, rid) if o["ok"] and o["kind"] != "annex"]
                if opts and len(g.local_projects(rid)) < 5:
                    o = rng.choice(opts)
                    g.start_project(0, rid, o["kind"], o["key"], border=o.get("border"), pool=o.get("pool"), site=o.get("site"))
                    actions += 1
            ps = g.local_projects(rid)
            if len(ps) > 1:
                g.move_queued_project(0, rid, rng.randrange(len(ps)), rng.randrange(len(ps)))
            if ps and rng.random() < .25:
                g.cancel_queued_project(0, rid, rng.randrange(len(ps)))
            g.recruit_great_person(0, rng.choice(list(GREAT_PEOPLE)), rid)
        for person in list(g.great_people):
            choices = [r.id for r in g.regions_of(person["owner"])]
            if choices:
                g.move_great_person(person["id"], rng.choice(choices))
                if rng.random() < .5:
                    g.activate_great_person(person["id"], rng.choice(("project", "science")))
        if turn % 9 == 3:
            g.set_flooded(rid)
        if turn % 12 == 5:
            g.earthquake(rid, rng.randint(5, 9))
        if turn % 12 == 7 and rr.owner == 0 and len(g.regions_of(0)) > 1:
            g.complete_occupation(1, rid)
            captures += 1
        if turn % 12 == 10:
            for loc in sel:
                if g.regions[loc].owner == 1:
                    g.complete_occupation(0, loc)
                    captures += 1
        g.end_turn()
        Q.check(g, f"progression seed={seed} mode={mode} gov={gov} turn={turn}")
        if turn % 6 == 0:
            g = pickle.loads(pickle.dumps(g))
            Q.check(g, "reload")
            saves += 1
    print(f"{mode}/{gov} seed={seed} turns={turns} actions={actions} captures={captures} saves={saves}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1330)
    ap.add_argument("--turns", type=int, default=48)
    args = ap.parse_args()
    for i, (mode, gov) in enumerate((m, v) for m in C.GAME_MODES for v in POLICIES):
        run(args.seed + i, mode, gov, args.turns)
    print("Problems:", dict(Q.PROBLEMS), flush=True)
    raise SystemExit(bool(Q.PROBLEMS))
