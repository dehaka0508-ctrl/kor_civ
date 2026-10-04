"""8개국 전원 AI 시뮬레이션: 지도자별 승률·멸망·지역 수·GDP 추이.

판마다 지금까지 가장 적게 나온 지도자 8명을 뽑아(동률은 무작위) 지도자별 출전 수를 고르게 맞춘다.
시작 위치 무작위, 정치체제는 AI가 직접 고르고, 기본 승리 조건(시간 종료 포함)으로 끝까지 진행한다.
판마다 결과를 JSON 한 줄로 남기므로 중단돼도 같은 --out 으로 이어서 돌릴 수 있다.

  python tools/nation_sim.py --games 300 --turns 480 --workers 4 --out nation_runs.jsonl
  python tools/nation_sim.py --report nation_runs.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

N_FAC = 8
SNAPS = (100, 240, 480)


def lineups(n_games, seed):
    from korciv.leaders import LEADERS
    keys = [l["key"] for l in LEADERS if l["key"] != "custom"]
    rng = random.Random(seed)
    used = Counter({k: 0 for k in keys})
    out = []
    for i in range(n_games):
        order = sorted(keys, key=lambda k: (used[k], rng.random()))[:N_FAC]
        rng.shuffle(order)
        used.update(order)
        out.append((seed * 1000 + i, order))
    return out


def run_game(job):
    seed, lineup, turns = job
    from korciv.game import Game
    from korciv.state import Settings
    t0 = time.time()
    g = Game(Settings(n_enemies=N_FAC - 1, seed=seed, all_ai=True, max_turns=turns,
                      player_leader=lineup[0], ai_leaders=list(lineup[1:])))
    snaps = {}

    def snap(t):
        snaps[t] = {f.id: (g.region_count(f.id), g.gdp(f.id) if f.alive else 0.0) for f in g.factions[:N_FAC]}
    while not g.game_over and g.turn <= turns:
        g.end_turn()
        done = g.turn - 1                      # 처리한 턴 수
        if done in SNAPS:
            snap(done)
    for t in SNAPS:                            # 일찍 끝난 판은 종료 시점 값을 쓴다
        if t not in snaps:
            snap(t)
    winners = list(g.winner[0]) if g.winner else []
    rows = []
    for f in g.factions[:N_FAC]:
        rows.append({"leader": f.leader, "gov": f.gov, "alive": f.alive, "eliminated": f.eliminated_turn,
                     "win": (1 / len(winners)) if f.id in winners else 0.0,
                     "regions": {t: snaps[t][f.id][0] for t in SNAPS},
                     "gdp": {t: round(snaps[t][f.id][1], 1) for t in SNAPS}})
    return {"seed": seed, "turns": g.turn - 1, "victory": g.winner[1] if g.winner else None,
            "winner_rebel": bool(winners) and all(w >= N_FAC for w in winners),
            "secs": round(time.time() - t0, 1), "factions": rows}


def simulate(args):
    todo = [(s, lu, args.turns) for s, lu in lineups(args.games, args.seed)]
    done = set()
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            done = {json.loads(line)["seed"] for line in f if line.strip()}
    todo = [j for j in todo if j[0] not in done]
    print(f"{len(todo)}판 실행 (이미 {len(done)}판 완료)", flush=True)
    t0 = time.time()
    with Pool(args.workers) as pool, open(args.out, "a", encoding="utf-8") as out:
        for i, res in enumerate(pool.imap_unordered(run_game, todo), 1):
            out.write(json.dumps(res, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{i}/{len(todo)} seed={res['seed']} {res['turns']}턴 {res['victory']} {res['secs']}s "
                  f"(경과 {time.time() - t0:.0f}s)", flush=True)
            if args.budget and time.time() - t0 > args.budget:
                print("시간 예산 초과: 여기서 멈춤(같은 --out 으로 이어서 실행)", flush=True)
                pool.terminate()
                break


VNAME = {"conquest": "정복", "economic": "경제", "landmark": "랜드마크", "time": "시간 종료"}


def report(path):
    from korciv.leaders import LEADER_BY_KEY, LEADER_CATEGORIES
    games = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    cat_of = {k: title for _, title, ks in LEADER_CATEGORIES for k in ks}
    by = defaultdict(list)
    for gm in games:
        for r in gm["factions"]:
            by[r["leader"]].append(r)
    vc = Counter(gm["victory"] for gm in games)
    print(f"{len(games)}판, 평균 종료 턴 {sum(g['turns'] for g in games) / len(games):.0f}, "
          f"평균 {sum(g['secs'] for g in games) / len(games):.0f}초/판")
    print("승리 유형:", {VNAME.get(k, k or "없음"): v for k, v in vc.most_common()},
          "반란 세력 승리", sum(g["winner_rebel"] for g in games))
    rows = []
    for k, rs in by.items():
        n = len(rs)
        wins = sum(r["win"] for r in rs)
        el = [r["eliminated"] for r in rs if r["eliminated"] is not None]
        rows.append({"key": k, "name": LEADER_BY_KEY[k]["name"], "cat": cat_of.get(k, ""),
                     "aggr": LEADER_BY_KEY[k]["aggr"], "n": n, "win": wins / n, "elim": len(el) / n,
                     "elim_turn": sum(el) / len(el) if el else None,
                     **{f"r{t}": sum(r["regions"][str(t)] for r in rs) / n for t in SNAPS},
                     **{f"g{t}": sum(r["gdp"][str(t)] for r in rs) / n for t in SNAPS}})
    # 지도자별 가장 많았던 승리 유형
    vt = defaultdict(Counter)
    for gm in games:
        for r in gm["factions"]:
            if r["win"]:
                vt[r["leader"]][gm["victory"]] += 1
    rows.sort(key=lambda x: -x["win"])
    print("| 순위 | 지도자 | 분류 | 호전 | 판 | 승률 | 멸망률 | 평균 멸망 턴 | 지역 100/240/480 | GDP 100/240/480 | 최다 승리 유형 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, x in enumerate(rows, 1):
        top = vt[x["key"]].most_common(1)
        tops = f"{VNAME.get(top[0][0], top[0][0])} ({top[0][1]})" if top else "–"
        et = f"{x['elim_turn']:.0f}" if x["elim_turn"] is not None else "–"
        print(f"| {i} | {x['name']} | {x['cat']} | {x['aggr']} | {x['n']} | {x['win'] * 100:.1f}% | "
              f"{x['elim'] * 100:.1f}% | {et} | {x['r100']:.1f} / {x['r240']:.1f} / {x['r480']:.1f} | "
              f"{x['g100']:,.0f} / {x['g240']:,.0f} / {x['g480']:,.0f} | {tops} |")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--turns", type=int, default=480)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="nation_runs.jsonl")
    ap.add_argument("--budget", type=float, default=0, help="이 초가 지나면 새 판을 그만 받고 멈춤")
    ap.add_argument("--report")
    args = ap.parse_args()
    if args.report:
        report(args.report)
    else:
        simulate(args)


if __name__ == "__main__":
    main()
