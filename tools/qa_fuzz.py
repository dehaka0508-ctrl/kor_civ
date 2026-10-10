"""QA 퍼저: 게임 엔진을 무작위로 두드리며 예외와 불변식 위반을 찾는다(개발용).

  python tools/qa_fuzz.py sim --games 6 --turns 300          # 전원 AI, 매 턴 불변식 점검
  python tools/qa_fuzz.py player --games 6 --turns 200       # 플레이어가 매 턴 무작위 행동
문제가 생기면 시드·턴·내용을 출력하고 계속 진행한다(마지막에 요약).
"""
from __future__ import annotations

import argparse
import math
import os
import pickle
import random
import sys
import traceback
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from korciv import config as C                    # noqa: E402
from korciv import diplomacy as D                 # noqa: E402
from korciv.game import Game                      # noqa: E402
from korciv.leaders import GOVERNMENTS, LEADERS   # noqa: E402
from korciv.state import NEUTRAL, Settings        # noqa: E402

PROBLEMS = Counter()
EXAMPLES = {}


def report(tag, msg):
    PROBLEMS[tag] += 1
    if tag not in EXAMPLES:
        EXAMPLES[tag] = msg
        print("  [문제]", tag, "-", msg, flush=True)


def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def check(g, where):
    """불변식."""
    nf = len(g.factions)
    for rid, r in g.regions.items():
        if not (r.owner == NEUTRAL or 0 <= r.owner < nf):
            report("소유자 범위", f"{where} {rid} owner={r.owner}")
        elif r.owner != NEUTRAL and not g.factions[r.owner].alive:
            report("멸망 세력 소유", f"{where} {rid} owner={r.owner}")
        if not finite(r.pop) or r.pop < 0:
            report("인구 이상", f"{where} {rid} pop={r.pop}")
        if not finite(r.happy):
            report("행복도 NaN", f"{where} {rid}")
        for k, v in r.b.items():
            if not isinstance(v, int) or v < 0 or v > 5:
                report("건물 단계 범위", f"{where} {rid} {k}={v}")
        p = r.project
        if p is not None:
            if p.progress > p.turns or p.turns < 1:
                report("프로젝트 진행", f"{where} {rid} {p.kind}:{p.key} {p.progress}/{p.turns}")
            if r.owner == NEUTRAL:
                report("중립 지역 프로젝트", f"{where} {rid}")
        for fid, o in r.occs.items():
            if o["progress"] > o["need"] + 1:
                report("점령 진행 초과", f"{where} {rid} {o}")
    for f in g.factions:
        if not finite(f.money):
            report("돈 NaN", f"{where} f{f.id}")
        for k, v in f.res.items():
            if not finite(v) or v < -1e-6:
                report("자원 음수/NaN", f"{where} f{f.id} {k}={v}")
        for k, v in f.specialty.items():
            if not finite(v) or v < -1e-6:
                report("특산물 음수", f"{where} f{f.id} {k}={v}")
        if f.alive:
            if g.regions.get(f.capital) is None or g.regions[f.capital].owner != f.id:
                if g.region_count(f.id) > 0:
                    report("수도 소유 불일치", f"{where} f{f.id} cap={f.capital} owner={g.regions.get(f.capital).owner}")
            if g.region_count(f.id) == 0:
                report("영토 없는 생존 세력", f"{where} f{f.id}")
        if not (0 <= f.tax <= 1):
            report("세율 범위", f"{where} f{f.id} {f.tax}")
        if not finite(f.war_weary) or f.war_weary < -1e-6:
            report("전쟁 피로 이상", f"{where} f{f.id} {f.war_weary}")
    for aid, a in g.armies.items():
        if a.id != aid:
            report("부대 id 불일치", f"{where} {aid}")
        if a.loc not in g.regions and a.loc not in g.world.seas:
            report("부대 위치 이상", f"{where} {aid} {a.loc}")
        if not a.units or any(n <= 0 for n in a.units.values()):
            report("빈 부대/음수 유닛", f"{where} {aid} {a.units}")
        if a.owner != NEUTRAL and (a.owner >= nf or not g.factions[a.owner].alive):
            report("멸망 세력 부대", f"{where} {aid} owner={a.owner}")
        if a.loc in g.world.seas and a.domain() == "land" and a.owner != NEUTRAL:
            report("육군만 바다에", f"{where} {aid} {a.units}")
        stale = [k for k, d in a.dmg.items() if k not in a.units and d > 1e-9]
        if stale:
            report("없는 유닛의 피해 기록", f"{where} {aid} units={a.units} dmg={a.dmg}")
        for k, d in a.dmg.items():
            if not finite(d) or d < -1e-6 or (k in a.units and d > a.hp_max(k) + 1e-6):
                report("피해량 범위", f"{where} {aid} {k} dmg={d} max={a.hp_max(k) if k in a.units else '-'}")
    for key, v in vars(g.dip).items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                if isinstance(vv, float) and not math.isfinite(vv):
                    report("외교 수치 NaN", f"{where} {key}")


def run_sim(seed, turns, n):
    rng = random.Random(seed)
    leaders = [l["key"] for l in LEADERS if l["key"] != "cus"]
    lineup = rng.sample(leaders, n)
    g = Game(Settings(n_enemies=n - 1, seed=seed, all_ai=True, max_turns=turns, fog=rng.choice([0, 1, 2]),
                      difficulty=rng.randrange(len(C.DIFFICULTIES)), player_leader=lineup[0], ai_leaders=lineup[1:]))
    t = 0
    try:
        while not g.game_over and g.turn <= turns:
            g.end_turn()
            t += 1
            check(g, f"sim seed={seed} turn={g.turn}")
            if t % 60 == 0:
                g = pickle.loads(pickle.dumps(g))
    except Exception:
        report("예외(sim)", f"seed={seed} turn={g.turn}\n" + traceback.format_exc())
    return g


def player_turn(g, rng):
    """플레이어(0번)가 무작위로 이것저것 시도한다. 실패 메시지는 정상, 예외만 문제."""
    pid = g.player_id
    f = g.player
    mine = [r.id for r in g.regions_of(pid)]
    acts = 0
    # 반란·제안 응답
    for rid in list(g.pending_rebellions):
        g.resolve_rebellion(pid, rid, rng.choice(["pay", "tax", "suppress"]))
    for prop in list(g.pending_proposals):
        if rng.random() < 0.5 and g.factions[prop["from"]].alive:
            if prop["kind"] == "trade":                    # AI 자원 거래 제의
                fid = prop["from"]
                seller, buyer = (fid, pid) if prop["sell"] else (pid, fid)
                D.make_trade(g, seller, buyer, prop["res"], prop["n"], prop["price"], fid)
            elif prop["kind"] != "coalition_war":
                D.sign_treaty(g, prop["from"], pid, prop["kind"])
        g.pending_proposals.remove(prop)
    # 슬롯
    for rid in rng.sample(mine, min(len(mine), 6)):
        rr = g.regions[rid]
        if rr.project and rng.random() < 0.08:
            g.cancel_project(pid, rid)
            continue
        if rr.project:
            continue
        opts = g.options(pid, rid)
        if opts:
            o = rng.choice(opts)
            g.start_project(pid, rid, o["kind"], o["key"], border=o.get("border"))
            acts += 1
        if rng.random() < 0.1:
            g.set_focus(pid, rid, rng.random() < 0.5)
        if rng.random() < 0.1:
            g.set_pop_focus(pid, rid, rng.random() < 0.5)
    # 부대
    armies = [a for a in g.armies.values() if a.owner == pid]
    for a in rng.sample(armies, min(len(armies), 6)):
        if a.id not in g.armies:
            continue
        r = rng.random()
        if r < 0.5:
            reach = list(g.reachable(a)) if a.id in g.armies else []
            near = list(g.world.node_neighbors(a.loc)) + reach
            if near:
                g.order_army(a.id, rng.choice(near), rng.choice(["assault", "surprise"]), force_bombard=rng.random() < 0.2)
        elif r < 0.6 and a.count() > 1:
            k = rng.choice(list(a.units))
            g.split_army(a.id, {k: max(1, a.units[k] // 2)})
        elif r < 0.7:
            others = [b for b in g.armies_at(a.loc, pid) if b.id != a.id]
            if others:
                g.merge_armies(a.id, others[0].id)
        elif r < 0.74:
            k = rng.choice(list(a.units))
            g.disband(a.id, {k: 1})
        elif r < 0.8:
            g.order_army(a.id, rng.choice(list(g.regions)))      # 먼 곳 경로 계획
    # 국정
    if rng.random() < 0.2:
        g.set_tax(pid, rng.choice([0, 0.05, 0.1, 0.15, 0.2, 0.3, 1.0, -0.5, 2.0]))
    if rng.random() < 0.2:
        res = rng.choice(["food", "oil", "coal", "elec"])
        if rng.random() < 0.5:
            g.market_buy(pid, res, rng.choice([1, 5, 50, 10 ** 6, 0, -3]))
        else:
            g.market_sell(pid, res, rng.choice([1, 5, 50, 10 ** 6, 0, -3]))
    if rng.random() < 0.1:
        g.set_auto_energy(pid, rng.random() < 0.5)
    if rng.random() < 0.15 and mine:
        rid = rng.choice(mine)
        g.set_energy(pid, rid, rng.choice(["p", "f"]), rng.choice(["coal", "oil", "elec"]), rng.choice([0, 1, 3, 9, -1]))
    if rng.random() < 0.1 and mine:
        rid = rng.choice(mine)
        kinds = list(g.specialty_kinds(pid)) if hasattr(g, "specialty_kinds") else []
        if kinds:
            g.set_specialty(pid, rid, rng.choice(kinds), rng.choice(["pin", "block", "auto"]))
    if rng.random() < 0.05:
        ids = [r.id for r in g.projects_by_priority(pid)] if hasattr(g, "projects_by_priority") else []
        rng.shuffle(ids)
        if ids:
            g.set_priority_order(pid, ids)
    # 외교
    others = [o.id for o in g.factions if o.alive and o.id != pid]
    if others and rng.random() < 0.3:
        o = rng.choice(others)
        r = rng.random()
        if r < 0.1:
            D.declare_war(g, pid, o)
        elif r < 0.3:
            D.propose_treaty(g, pid, o, rng.choice(["nonaggr", "passage", "alliance", "coalition", "peace"]))
        elif r < 0.4:
            D.declare_friendship(g, pid, o)
        elif r < 0.5:
            D.denounce(g, pid, o)
        elif r < 0.55:
            D.break_nonaggr(g, pid, o)
        elif r < 0.6:
            D.leave_alliance(g, pid, o)
        elif r < 0.62:
            D.leave_coalition(g, pid)
        else:
            offer = D.empty_offer()
            offer["give"]["money"] = rng.choice([0, 100, 10 ** 9])
            offer["take"]["food"] = rng.choice([0, 1, 10 ** 6])
            border = [r_.id for r_ in g.regions_of(o) if any(g.regions[n].owner == pid for n in g.world.land_adj[r_.id])]
            if border and rng.random() < 0.3:
                offer["take"]["regions"] = [rng.choice(border)]
            res, counter, info = D.evaluate_offer(g, o, pid, offer)
            D.respond_offer(g, o, pid, offer)
    return acts


def run_player(seed, turns, n):
    rng = random.Random(seed * 7 + 1)
    leaders = [l["key"] for l in LEADERS]
    g = Game(Settings(n_enemies=n - 1, seed=seed, max_turns=turns, fog=rng.choice([0, 1, 2]),
                      difficulty=rng.randrange(len(C.DIFFICULTIES)), player_leader=rng.choice(leaders),
                      player_leader_name="퍼저"))
    g.set_player_government(rng.choice(GOVERNMENTS)["key"])
    if not g.setup_done:
        g.finalize_setup()
    try:
        while not g.game_over and g.turn <= turns and g.player.alive:
            player_turn(g, rng)
            check(g, f"player seed={seed} turn={g.turn} (행동 후)")
            g.end_turn()
            check(g, f"player seed={seed} turn={g.turn}")
            if g.turn % 50 == 0:
                g = pickle.loads(pickle.dumps(g))
    except Exception:
        report("예외(player)", f"seed={seed} turn={g.turn}\n" + traceback.format_exc())
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["sim", "player"])
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--turns", type=int, default=200)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--factions", type=int, default=0, help="0이면 판마다 2~10 무작위")
    a = ap.parse_args()
    for i in range(a.games):
        seed = a.seed + i
        n = a.factions or random.Random(seed).randint(2, 10)
        g = (run_sim if a.mode == "sim" else run_player)(seed, a.turns, n)
        alive = sum(f.alive for f in g.factions)
        print(f"{a.mode} seed={seed} 세력{n} → 턴 {g.turn - 1}, 생존 {alive}/{len(g.factions)}, "
              f"승리 {g.winner[1] if g.winner else '-'}", flush=True)
    print("== 요약 ==")
    for k, v in PROBLEMS.most_common():
        print(f"{k}: {v}회")
    if not PROBLEMS:
        print("문제 없음")


if __name__ == "__main__":
    main()
