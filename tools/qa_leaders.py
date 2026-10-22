"""지도자 전원: 세 판도를 순회하며 생산·전쟁·점령·위인·저장 상호작용 퍼징."""
import argparse
import pickle
import random
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from korciv import config as C, diplomacy as D
from korciv.game import Game
from korciv.leaders import LEADERS, POLICIES
from korciv.progression import TECHS, GREAT_PEOPLE
from korciv.state import Settings
import qa_fuzz as Q


def run(index, leader, turns, seed):
    rng = random.Random(seed)
    mode = list(C.GAME_MODES)[index % len(C.GAME_MODES)]
    g = Game(Settings(seed=seed, mode=mode, player_start="S002", ai_starts=["N001"],
                      n_enemies=1, player_leader=leader, ai_leaders=["cus"], victories=("time",), max_turns=1000))
    g.set_player_government(rng.choice(list(POLICIES)))
    g.factions[1].is_ai = False
    near = sorted(g.world.land_adj["S002"])
    frontier = near[0]
    for rid in near[1:4]:
        g.transfer_region(rid, 0, reason="편입")
    for rr in g.regions_of(0):
        rr.b = dict.fromkeys(rr.b, 0)
        rr.b.update(housing=5, admin=3, edu=4, academy=0 if leader == "sta" else 1)
        rr.pop, rr.happy = 12, 20
    g.transfer_region(frontier, 1, reason="편입")
    g.regions[frontier].pop = 12
    for a in list(g.armies_at(frontier)):
        g.remove_army(a)
    g.new_army(0, next(iter(g.world.seas)), {"dd": 1, "lst": 1, "inf": 1})
    g.player.money = g.player.admin = g.player.sci_points = 1e6
    g.player.res["food"] = 1e6
    D._start_war(g, 0, 1, aggressor=0)
    actions = 0
    for turn in range(turns):
        Q.player_turn(g, rng)
        g.unlock_policy(0)
        g.unlock_tech(0, rng.choice(list(TECHS)))
        mine = [r.id for r in g.regions_of(0)]
        if mine:
            g.recruit_great_person(0, rng.choice(list(GREAT_PEOPLE)), rng.choice(mine))
        if turn % 4 == 0 and g.regions[frontier].owner == 1:
            for a in list(g.armies_at(frontier)):
                g.remove_army(a)
            g.new_army(1, frontier, {"inf": 3})
            a = g.new_army(0, "S002", {"inf": 12, "tank": 2})
            g._ground_battle(0, [a], frontier, rng.choice(("assault", "surprise")), [a])
            actions += 1
        if turn % 4 == 3 and g.regions[frontier].owner == 0:
            g.complete_occupation(1, frontier)
        if turn % 5 == 2 and mine:
            g.set_flooded(rng.choice(mine))
        g.end_turn()
        Q.check(g, f"leader={leader} seed={seed} turn={g.turn}")
        if turn % 4 == 0:
            g = pickle.loads(pickle.dumps(g))
            Q.check(g, "leader reload")
    print(f"{leader}/{mode} seed={seed} turns={turns} battles={actions}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=16)
    ap.add_argument("--seed", type=int, default=13600)
    args = ap.parse_args()
    for index, item in enumerate(LEADERS):
        try:
            run(index, item["key"], args.turns, args.seed + index)
        except Exception:
            Q.report("지도자 퍼징 예외", f"{item['key']} seed={args.seed + index}\n{traceback.format_exc()}")
    print("Problems:", dict(Q.PROBLEMS), flush=True)
    raise SystemExit(bool(Q.PROBLEMS))
