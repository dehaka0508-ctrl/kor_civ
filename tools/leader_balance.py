"""지도자 밸런스 시뮬레이션: 전원 AI, 무작위 시작 위치, 정치체제는 모두 철인통치(효과 없음).

한 라운드마다 지도자 39명을 섞어 6명씩 6판에 나눈다(남는 3명은 다음 라운드에 무작위로 순번이 돈다).
결과·제안은 docs/지도자_밸런스.md 참고.
판마다 결과를 JSON 한 줄로 남기고, --report 로 지도자별 표를 만든다.

  python tools/leader_balance.py --rounds 40 --turns 240 --workers 4 --out leader_runs.jsonl
  python tools/leader_balance.py --report leader_runs.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FACTIONS_PER_GAME = 6


def _leader_keys():
    from korciv.leaders import LEADERS
    return [l["key"] for l in LEADERS if l["key"] != "custom"]


def run_game(job):
    """job = (seed, [지도자 n명], turns, flat[, govs]) -> 판 결과 dict.
    flat 이면 모든 지도자 호전성 5(효과만 비교). govs 이면 AI가 정치체제를 직접 고른다(아니면 전원 철인통치)."""
    seed, lineup, turns, flat = job[:4]
    govs = job[4] if len(job) > 4 else False
    n_fac = len(lineup)
    import korciv.game as G
    if flat:
        from korciv.leaders import LEADERS
        for l in LEADERS:
            l["aggr"] = 5
    from korciv import diplomacy as D
    from korciv import rules as R
    from korciv.state import Settings
    if not govs:
        G.ai_pick_government = lambda *a, **k: "philosopher"      # 반란 세력 포함 전원 철인통치
    from korciv import ai as A
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import leader_tracking as LT
    tracker = LT.install(G, D, A)
    wars = {}
    orig_declare = D.declare_war

    def declare(g, a, b, reason="선전포고", _joined=None, _role="declare"):
        if _joined is None and not D.at_war(g, a, b) and not D.has_nonaggr(g, a, b):
            wars[a] = wars.get(a, 0) + 1
        return orig_declare(g, a, b, reason, _joined, _role)
    D.declare_war = declare
    t0 = time.time()
    g = G.Game(Settings(n_enemies=n_fac - 1, seed=seed, all_ai=True,
                        player_leader=lineup[0], ai_leaders=list(lineup[1:])))
    assert govs or all(f.gov == "philosopher" for f in g.factions)
    tracker.g = g
    starts = {}
    for f in g.factions:
        info = g.world.regions[f.capital]
        starts[f.id] = {"rid": f.capital, "name": info.name, "value": g.region_value(f.capital)[0],
                        "output": R.region_output(info.pop0, info.farm, info.fishery, info.factory, info.bank,
                                                  False)}
    mid = {}
    peak = {f.id: 1 for f in g.factions}
    for _ in range(turns):
        g.end_turn()
        LT.after_turn(tracker, g)
        for f in g.factions[:n_fac]:
            peak[f.id] = max(peak[f.id], g.region_count(f.id))
        if g.turn == 121:
            tot = sum(g.gdp(x) for x in g.alive_ids()) or 1
            mid = {f.id: g.gdp(f.id) / tot for f in g.factions[:n_fac]}
        if g.game_over:
            break
    total_gdp = sum(g.gdp(x) for x in g.alive_ids()) or 1.0
    alive = [f for f in g.factions[:n_fac] if f.alive]
    top = max(alive, key=lambda f: g.gdp(f.id)).id if alive else None
    winners = list(g.winner[0]) if g.winner else []
    rows = []
    for f in g.factions[:n_fac]:
        rebels = sum(1 for x in g.factions if x.rebel_of == f.id)
        win = (1 / len(winners)) if f.id in winners else 0.0
        first = win if winners else (1.0 if f.id == top else 0.0)
        rows.append({
            "leader": f.leader, "aggr": f.aggression, "start": starts[f.id],
            "alive": f.alive, "regions": g.region_count(f.id), "peak": peak[f.id],
            "gdp_share": g.gdp(f.id) / total_gdp, "mid_share": mid.get(f.id),
            "win": win, "first": first, "wars_declared": wars.get(f.id, 0), "rebel_states": rebels,
            "eliminated": f.eliminated_turn, "happy": g.avg_happiness(f.id) if f.alive else None,
            "victory_type": g.winner[1] if f.id in winners else None,
            "gov": f.gov, "victory_turn": g.turn if f.id in winners else None,
            "rank": sorted((x for x in g.factions[:n_fac]), key=lambda x: -g.gdp(x.id)).index(f) + 1,
            "landmarks": sum(1 for r in g.regions.values() if r.owner == f.id and r.landmark),
            **LT.summary(tracker, f.id),
        })
    return {"seed": seed, "turns": g.turn, "victory": g.winner[1] if g.winner else None,
            "secs": round(time.time() - t0, 1), "factions": rows, "n_factions": n_fac,
            "alive_end": sum(1 for f in g.factions if f.alive), "rebel_states": sum(1 for f in g.factions if f.rebel_of is not None)}


def jobs(rounds, turns, base_seed, flat=False, n_fac=FACTIONS_PER_GAME, govs=False):
    keys = _leader_keys()
    out = []
    for r in range(rounds):
        order = keys[:]
        random.Random(base_seed + r).shuffle(order)
        for gi in range(len(order) // n_fac):
            lineup = order[gi * n_fac:(gi + 1) * n_fac]
            out.append((base_seed * 100 + r * 10 + gi, lineup, turns, flat, govs))
    return out


def simulate(args):
    todo = jobs(args.rounds, args.turns, args.seed, args.flat_aggr, args.factions, args.govs)
    done = set()
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            done = {json.loads(line)["seed"] for line in f if line.strip()}
    todo = [j for j in todo if j[0] not in done]
    print(f"{len(todo)}판 실행 (이미 {len(done)}판 완료)", flush=True)
    with Pool(args.workers) as pool, open(args.out, "a", encoding="utf-8") as out:
        for i, res in enumerate(pool.imap_unordered(run_game, todo), 1):
            out.write(json.dumps(res, ensure_ascii=False) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}", flush=True)


# ------------------------------------------------------------------ 보고서
def _ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs) or 1e-9
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def report(path):
    from korciv.leaders import LEADER_BY_KEY
    games = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    rows = [r for gm in games for r in gm["factions"]]
    # 시작 위치 보정: 종료 GDP 점유율 ~ log(시작 지역 산출)
    xs = [math.log(r["start"]["output"]) for r in rows]
    ys = [r["gdp_share"] for r in rows]
    a, b = _ols(xs, ys)
    by = {}
    for r, x in zip(rows, xs):
        d = by.setdefault(r["leader"], [])
        d.append((r, r["gdp_share"] - (a + b * x)))
    n_games = len(games)
    vic = {}
    for gm in games:
        vic[gm["victory"]] = vic.get(gm["victory"], 0) + 1
    print(f"{n_games}판, 평균 {sum(g['turns'] for g in games) / n_games:.0f}턴, 종료 유형 {vic}")
    print(f"위치 보정: 점유율 = {a:.3f} + {b:.3f} × ln(시작 산출)")
    table = []
    for k, lst in by.items():
        n = len(lst)
        rs = [r for r, _ in lst]
        first = sum(r["first"] for r in rs) / n
        se = math.sqrt(max(first * (1 - first), 1e-9) / n)
        table.append({
            "leader": LEADER_BY_KEY[k]["name"], "key": k, "aggr": LEADER_BY_KEY[k]["aggr"], "n": n,
            "victory_n": sum(1 for r in rs if r["win"] > 0),
            "win": sum(r["win"] for r in rs) / n, "first": first, "se": se,
            "share": sum(r["gdp_share"] for r in rs) / n,
            "adj": sum(res for _, res in lst) / n,
            "alive": sum(r["alive"] for r in rs) / n,
            "regions": sum(r["regions"] for r in rs) / n,
            "wars": sum(r["wars_declared"] for r in rs) / n,
            "rebels": sum(r["rebel_states"] for r in rs) / n,
        })
    table.sort(key=lambda t: -t["adj"])
    print(f"{'지도자':8s} 호전 판수  승리  1위율(±SE)  GDP점유  위치보정  생존  지역  선포  분리독립")
    for t in table:
        print(f"{t['leader']:8s} {t['aggr']:4d} {t['n']:4d} {t['win']*100:5.1f}% {t['first']*100:5.1f}%(±{t['se']*100:4.1f})"
              f" {t['share']*100:6.1f}% {t['adj']*100:+6.1f}%p {t['alive']*100:4.0f}% {t['regions']:5.1f}"
              f" {t['wars']:4.1f} {t['rebels']:4.2f}")
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=40)
    ap.add_argument("--turns", type=int, default=240)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="leader_runs.jsonl")
    ap.add_argument("--flat-aggr", action="store_true", help="모든 지도자 호전성 5: AI 성향을 빼고 버프·디버프만 비교")
    ap.add_argument("--factions", type=int, default=FACTIONS_PER_GAME, help="판당 세력 수")
    ap.add_argument("--govs", action="store_true", help="AI가 정치체제를 직접 고른다(기본: 전원 철인통치)")
    ap.add_argument("--report")
    args = ap.parse_args()
    if args.report:
        report(args.report)
    else:
        simulate(args)


if __name__ == "__main__":
    main()
