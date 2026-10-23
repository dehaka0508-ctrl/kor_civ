"""같은 시드에서 AI 성장·행정 적자·연구·공사 정지를 비교하고 매 턴 상태를 검사한다."""
import argparse
import json
from pathlib import Path
import pickle
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from korciv import config as C
from korciv.game import Game
from korciv.state import Settings
import qa_fuzz as Q


def run(seed, mode, turns, factions):
    g = Game(Settings(seed=seed, mode=mode, all_ai=True, n_enemies=factions - 1,
                      victories=("time",), max_turns=turns))
    totals = dict(lawless=0, hungry=0, stalled=0, active=0, states=0)
    for _ in range(turns):
        if g.game_over:
            break
        g.end_turn()
        Q.check(g, f"growth/{mode} seed={seed} turn={g.turn}")
        for f in g.factions:
            if f.alive:
                totals['states'] += 1
                totals['lawless'] += int(f.lawless)
                totals['hungry'] += int(f.res.get('food', 0) <= 0)
        ps = list(g.unique_projects(g.regions.values()))
        totals['active'] += len(ps)
        totals['stalled'] += sum(p.stalled for p in ps)
        if g.turn % 32 == 0:
            g = pickle.loads(pickle.dumps(g))
            Q.check(g, 'growth reload')
    alive = [f for f in g.factions if f.alive]
    return dict(seed=seed, mode=mode, turn=g.turn - 1, pop=sum(g.total_pop(f.id) for f in alive),
                gdp=sum(g.gdp(f.id) for f in alive), science=sum(g.science_production(f.id) for f in alive),
                techs=sum(len(f.techs) for f in alive), policies=sum(f.policy_level for f in alive),
                money=sum(f.money for f in alive), regions=sum(g.region_count(f.id) for f in alive),
                people=len(g.great_people), factions=len(alive), **totals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--turns', type=int, default=96)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--seed', type=int, default=14000)
    ap.add_argument('--factions', type=int, default=4)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    start = time.perf_counter()
    rows = []
    for mode in C.GAME_MODES:
        for i in range(args.seeds):
            row = run(args.seed + i, mode, args.turns, args.factions)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    report = dict(rows=rows, problems=dict(Q.PROBLEMS), seconds=round(time.perf_counter() - start, 2))
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Problems:', dict(Q.PROBLEMS), 'seconds=', report['seconds'], flush=True)
    return bool(Q.PROBLEMS)


if __name__ == '__main__':
    raise SystemExit(main())
