"""8개국 전원 AI 시뮬레이션 + AI 행동 기록(개발용).

엔진은 건드리지 않고, 시뮬레이션 프로세스 안에서만 주요 함수를 감싸서 세력별로 센다.
- 결과: 승리·승리 유형·멸망 턴, 120/240/480턴 지역 수·GDP, 당한 반란(발생·대응 결과)
- 행동: 완공한 건물·생산한 유닛(병종), 편입·무력 점령·거래로 얻은/잃은 지역, 선전포고·참전·강화·전쟁 기간,
  조약 제안·체결, 우호 선언·비난·조약 파기, 거래 품목, 시장 매매, 세율

  python tools/behavior_sim.py --games 300 --turns 480 --workers 4 --out behavior_runs.jsonl
  python tools/behavior_sim.py --report behavior_runs.jsonl > 보고서.md
판마다 결과를 JSON 한 줄로 남기므로 중단돼도 같은 --out 으로 이어서 돌릴 수 있다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

N_FAC = 8
SNAPS = (120, 240, 480)


# ------------------------------------------------------------------ 계측
def _st(g, fid):
    s = getattr(g, "_st", None)
    if s is None or fid is None or fid not in s:
        return None
    return s[fid]


def _add(g, fid, key, v=1):
    s = _st(g, fid)
    if s is not None:
        s[key] += v


def instrument():
    from korciv import diplomacy as D
    from korciv import game as GM
    from korciv.state import NEUTRAL
    G = GM.Game
    if getattr(G, "_instrumented", False):
        return
    G._instrumented = True

    o_transfer = G.transfer_region

    def transfer_region(self, rid, new_owner, reason="점령"):
        old = self.regions[rid].owner
        r = o_transfer(self, rid, new_owner, reason)
        if old == new_owner:
            return r
        if reason == "편입":
            _add(self, new_owner, "gain:annex")
        elif reason == "점령":
            _add(self, new_owner, "gain:conquer_neutral" if old == NEUTRAL else "gain:conquer_enemy")
            _add(self, old, "lost:conquest")
        elif reason == "거래":
            _add(self, new_owner, "gain:trade")
            _add(self, old, "lost:trade")
        elif reason == "독립":
            _add(self, old, "lost:rebel")
        return r
    G.transfer_region = transfer_region

    o_complete = G._complete_project

    def _complete_project(self, f, rr, p):
        kind, key = p.kind, p.key
        r = o_complete(self, f, rr, p)
        if kind == "build":
            _add(self, f.id, f"build:{key}")
        elif kind == "unit":
            _add(self, f.id, f"unit:{key}")
        elif kind == "science":
            _add(self, f.id, f"science:{key}")
        elif kind == "capital":
            _add(self, f.id, kind)
        return r
    G._complete_project = _complete_project

    o_resolve = G.resolve_rebellion

    def resolve_rebellion(self, fid, rid, choice):
        msg = o_resolve(self, fid, rid, choice)
        if "요구 수용(산출" in msg:
            _add(self, fid, "rebel:pay")
        elif "세율" in msg and "요구 수용" in msg:
            _add(self, fid, "rebel:tax")
        elif "진압 성공" in msg:
            _add(self, fid, "rebel:suppress")
        elif "진압 실패" in msg:
            _add(self, fid, "rebel:independence")
        return msg
    G.resolve_rebellion = resolve_rebellion

    o_event = G.event

    def event(self, kind, text, region=None, fids=()):
        if kind == "rebel" and "반란이 일어났습니다" in text and fids:
            _add(self, fids[0], "rebel:outbreak")
        elif kind == "battle":
            for f in set(fids):
                _add(self, f, "battle")
        return o_event(self, kind, text, region=region, fids=fids)
    G.event = event

    for name in ("market_buy", "market_sell"):
        orig = getattr(G, name)

        def wrap(self, fid, res, qty, _o=orig, _n=name):
            r = _o(self, fid, res, qty)
            q = r[0] if isinstance(r, tuple) else 0
            if q and q > 0:
                tag = "buy" if _n == "market_buy" else "sell"
                _add(self, fid, f"{tag}:{res}", q)
                _add(self, fid, f"{tag}_n:{res}")
            return r
        setattr(G, name, wrap)

    o_war = D.declare_war

    def declare_war(g, a, b, reason="선전포고", _joined=None, _role="declare"):
        ok, msg = o_war(g, a, b, reason, _joined, _role)
        if ok:
            if _role == "declare":
                _add(g, a, "war:declare")
                _add(g, b, "war:received")
                s = _st(g, a)
                if s is not None and "war:first_turn" not in s:
                    s["war:first_turn"] = g.turn
            elif _role == "ally":
                _add(g, a, "war:ally_join")
            else:
                _add(g, a, "war:coalition_join")
        return ok, msg
    D.declare_war = declare_war

    o_peace = D.make_peace

    def make_peace(g, a, b, _done=None):
        p = D.pair(a, b)
        w = g.dip.wars.get(p)
        fresh = w is not None and (_done is None or p not in _done)
        start = w["start"] if fresh else None
        taken = dict(w.get("taken", {})) if fresh else {}
        r = o_peace(g, a, b, _done)
        if fresh and p not in g.dip.wars:
            for f in (a, b):
                _add(g, f, "war:peace")
                _add(g, f, "war:turns", g.turn - start)
                _add(g, f, "war:regions_taken", taken.get(f, 0))
        return r
    D.make_peace = make_peace

    o_sign = D.sign_treaty

    def sign_treaty(g, a, b, kind):
        r = o_sign(g, a, b, kind)
        if kind in ("nonaggr", "passage", "alliance", "coalition"):
            _add(g, a, f"treaty:{kind}")
            _add(g, b, f"treaty:{kind}")
        return r
    D.sign_treaty = sign_treaty

    o_prop = D.propose_treaty

    def propose_treaty(g, proposer, target, kind):
        ok, msg = o_prop(g, proposer, target, kind)
        _add(g, proposer, f"propose:{kind}")
        if ok:
            _add(g, proposer, f"propose_ok:{kind}")
        return ok, msg
    D.propose_treaty = propose_treaty

    o_friend = D.declare_friendship

    def declare_friendship(g, a, b, force=False):
        ok, msg = o_friend(g, a, b, force)
        if ok:
            _add(g, a, "diplo:friendship")
        return ok, msg
    D.declare_friendship = declare_friendship

    o_den = D.denounce

    def denounce(g, a, b):
        ok, msg = o_den(g, a, b)
        if ok:
            _add(g, a, "diplo:denounce")
            _add(g, b, "diplo:denounced")
        return ok, msg
    D.denounce = denounce

    for name, tag in (("break_nonaggr", "diplo:break_nonaggr"), ("leave_alliance", "diplo:leave_alliance")):
        orig = getattr(D, name)

        def wrap(g, a, b, _o=orig, _t=tag):
            r = _o(g, a, b)
            _add(g, a, _t)
            return r
        setattr(D, name, wrap)
    o_leave = D.leave_coalition

    def leave_coalition(g, a):
        r = o_leave(g, a)
        _add(g, a, "diplo:leave_coalition")
        return r
    D.leave_coalition = leave_coalition

    o_exec = D.execute_offer

    def execute_offer(g, proposer, ai, offer):
        _add(g, proposer, "trade:proposed")
        _add(g, ai, "trade:accepted")
        for who, side in ((proposer, "give"), (ai, "take")):
            items = offer.get(side, {})
            other = ai if who == proposer else proposer
            for k in ("money", "food", "oil", "coal", "elec", "specialty"):
                if items.get(k, 0):
                    _add(g, who, f"trade_give:{k}")
                    _add(g, other, f"trade_get:{k}")
            if items.get("passage"):
                _add(g, who, "trade_give:passage")
            if items.get("regions"):
                _add(g, who, "trade_give:regions", len(items["regions"]))
        return o_exec(g, proposer, ai, offer)
    D.execute_offer = execute_offer


# ------------------------------------------------------------------ 한 판
def run_game(job):
    seed, lineup, turns = job
    instrument()
    from korciv.game import Game
    from korciv.state import Settings
    t0 = time.time()
    g = Game(Settings(n_enemies=N_FAC - 1, seed=seed, all_ai=True, max_turns=turns,
                      player_leader=lineup[0], ai_leaders=list(lineup[1:])))
    g._st = {f.id: Counter() for f in g.factions[:N_FAC]}
    starts = {f.id: f.capital for f in g.factions[:N_FAC]}
    snaps = {}
    tax_samples = defaultdict(list)

    def snap(t):
        snaps[t] = {f.id: (g.region_count(f.id), round(g.gdp(f.id), 1) if f.alive else 0.0)
                    for f in g.factions[:N_FAC]}
    while not g.game_over and g.turn <= turns:
        g.end_turn()
        done = g.turn - 1
        if done in SNAPS:
            snap(done)
        if done % 24 == 0:
            for f in g.factions[:N_FAC]:
                if f.alive:
                    tax_samples[f.id].append(f.tax)
        if done % 48 == 0:
            for f in g.factions[:N_FAC]:
                if f.alive and f.ai.get("victory_goal"):
                    g._st[f.id][f"goal:{f.ai['victory_goal']}"] += 1
    for t in SNAPS:
        if t not in snaps:
            snap(t)
    winners = list(g.winner[0]) if g.winner else []
    rows = []
    for f in g.factions[:N_FAC]:
        army = Counter()
        for a in g.armies.values():
            if a.owner == f.id:
                army.update(a.units)
        rows.append({"leader": f.leader, "gov": f.gov, "alive": f.alive, "eliminated": f.eliminated_turn,
                     "start": starts[f.id], "do8": g.world.regions[starts[f.id]].do8,
                     "win": (1 / len(winners)) if f.id in winners else 0.0,
                     "regions": {t: snaps[t][f.id][0] for t in SNAPS},
                     "gdp": {t: snaps[t][f.id][1] for t in SNAPS},
                     "tax": round(sum(tax_samples[f.id]) / len(tax_samples[f.id]), 3) if tax_samples[f.id] else None,
                     "army_end": dict(army), "stats": dict(g._st[f.id]),
                     "goal_end": f.ai.get("victory_goal"), "science_done": len(f.science)})
    return {"seed": seed, "turns": g.turn - 1, "victory": g.winner[1] if g.winner else None,
            "winner_rebel": bool(winners) and all(w >= N_FAC for w in winners),
            "rebel_states": len(g.factions) - N_FAC,
            "secs": round(time.time() - t0, 1), "factions": rows}


def simulate(a):
    from nation_sim import lineups
    todo = [(s, lu, a.turns) for s, lu in lineups(a.games, a.seed)]
    done = set()
    if os.path.exists(a.out):
        with open(a.out, encoding="utf-8") as f:
            done = {json.loads(line)["seed"] for line in f if line.strip()}
    todo = [j for j in todo if j[0] not in done]
    print(f"{len(todo)}판 실행 (이미 {len(done)}판 완료)", flush=True)
    t0 = time.time()
    with Pool(a.workers) as pool, open(a.out, "a", encoding="utf-8") as out:
        for i, res in enumerate(pool.imap_unordered(run_game, todo), 1):
            out.write(json.dumps(res, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{i}/{len(todo)} seed={res['seed']} {res['turns']}턴 {res['victory']} {res['secs']}s "
                  f"(경과 {time.time() - t0:.0f}s)", flush=True)


# ------------------------------------------------------------------ 보고서
VNAME = {"conquest": "정복", "science": "과학", "economic": "경제", "diplomatic": "외교", "time": "시간 종료", None: "없음"}
BLD = {"farm": "농장", "fishery": "어장", "factory": "공장", "bank": "은행", "power": "발전소", "specialty": "특산물",
       "extract": "광산·유전", "shelter": "방공호", "aa": "대공포", "line": "방어선", "academy": "사관학교",
       "airport": "공항", "port": "항구"}


def backfill_starts(games):
    """시작 지역이 없는 예전 기록: 같은 시드·지도자 순서로 게임을 처음 만든 상태만 다시 만들어 채운다.
    시작 위치는 시드로 정해지므로 같아야 하며, 정치체제가 저장된 값과 다르면 그 판은 권역 집계에서 뺀다."""
    from korciv.game import Game
    from korciv.state import Settings
    bad = 0
    for gm in games:
        rows = gm["factions"]
        if all("do8" in r for r in rows):
            continue
        lu = [r["leader"] for r in rows]
        g = Game(Settings(n_enemies=N_FAC - 1, seed=gm["seed"], all_ai=True, max_turns=480,
                          player_leader=lu[0], ai_leaders=lu[1:]))
        if [f.gov for f in g.factions[:N_FAC]] != [r["gov"] for r in rows]:
            bad += 1
            continue
        for f, r in zip(g.factions[:N_FAC], rows):
            r["start"], r["do8"] = f.capital, g.world.regions[f.capital].do8
    if bad:
        print(f"(시작 지역 복원 실패 {bad}판 — 권역 집계에서 제외)", file=sys.stderr)


def report(path):
    from korciv import config as C
    from korciv.leaders import GOV_BY_KEY, LEADER_BY_KEY, LEADER_CATEGORIES
    games = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    backfill_starts(games)
    rows = [r for gm in games for r in gm["factions"]]
    by = defaultdict(list)
    for gm in games:
        for r in gm["factions"]:
            r["_victory"] = gm["victory"]
            by[r["leader"]].append(r)
    cat_of = {k: title for _, title, ks in LEADER_CATEGORIES for k in ks}
    ng = len(games)
    out = []
    p = out.append
    vc = Counter(gm["victory"] for gm in games)
    p(f"- 판 수 {ng}, 평균 종료 턴 {sum(g['turns'] for g in games) / ng:.0f}, 판당 평균 {sum(g['secs'] for g in games) / ng:.0f}초")
    p("- 승리 유형: " + ", ".join(f"{VNAME.get(k, k)} {v}판({v / ng * 100:.0f}%)" for k, v in vc.most_common())
      + f" · 반란 세력이 이긴 판 {sum(g['winner_rebel'] for g in games)}")
    p(f"- 판당 반란으로 생긴 신생국 {sum(g['rebel_states'] for g in games) / ng:.2f}개")
    p("")
    # 표 0: 승리 유형별 종료 턴
    p("## 0. 승리 유형과 종료 턴")
    p("")
    p("| 승리 유형 | 판 | 비율 | 종료 턴 중앙값 | 최소~최대 | 200턴 미만 | 200~350턴 | 350턴 초과 |")
    p("|---|---|---|---|---|---|---|---|")
    import statistics as _st
    for k, v in vc.most_common():
        ts = sorted(g["turns"] for g in games if g["victory"] == k)
        p(f"| {VNAME.get(k, k)} | {v} | {v / ng * 100:.0f}% | {_st.median(ts):.0f} | {ts[0]}~{ts[-1]} | "
          f"{sum(t < 200 for t in ts)} | {sum(200 <= t <= 350 for t in ts)} | {sum(t > 350 for t in ts)} |")
    ts = [g["turns"] for g in games]
    p(f"| 전체 | {ng} | 100% | {_st.median(ts):.0f} | {min(ts)}~{max(ts)} | {sum(t < 200 for t in ts)} | "
      f"{sum(200 <= t <= 350 for t in ts)} | {sum(t > 350 for t in ts)} |")
    p("")
    # 승자가 마지막에 노리던 목표, 처음 8개국이 1년마다 고른 목표 비율
    gc = Counter()
    for r in rows:
        for kk, v in r["stats"].items():
            if kk.startswith("goal:"):
                gc[kk[5:]] += v
    tg = sum(gc.values()) or 1
    p("- AI가 1년마다 고른 승리 목표 비율: " + ", ".join(f"{VNAME.get(k, k)} {v / tg * 100:.0f}%" for k, v in gc.most_common()))
    wg = Counter((r["_victory"] if "_victory" in r else None, r.get("goal_end")) for r in rows if r["win"])
    sd = Counter(r.get("science_done", 0) for r in rows)
    p("- 과학 단계 진행(처음 8개국, 게임 종료 시): " + ", ".join(f"{k}단계 {v}" for k, v in sorted(sd.items())))
    p("")
    # 표 1: 지도자별 결과
    p("## 1. 지도자별 결과")
    p("")
    p("지역·GDP의 240·480 칸은 그 전에 게임이 끝났으면 종료 시점 값입니다.")
    p("")
    p("| 순위 | 지도자 | 분류 | 호전 | 판 | 승률 | 승리 유형(횟수) | 멸망률 | 평균 멸망 턴 | 지역 120/240/480 | GDP 120/240/480 | 당한 반란(판당) | 반란 독립(판당) |")
    p("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    stats = []
    for k, rs in by.items():
        n = len(rs)
        wins = sum(r["win"] for r in rs)
        el = [r["eliminated"] for r in rs if r["eliminated"] is not None and r["eliminated"] <= 480]
        vt = Counter()
        for r in rs:
            if r["win"]:
                vt[r["_victory"]] += r["win"]
        stats.append((wins / n, k, rs, el, vt))
    stats.sort(key=lambda x: -x[0])
    for i, (wr, k, rs, el, vt) in enumerate(stats, 1):
        n = len(rs)
        reg = [sum(r["regions"][str(t)] for r in rs) / n for t in SNAPS]
        gdp = [sum(r["gdp"][str(t)] for r in rs) / n for t in SNAPS]
        reb = sum(r["stats"].get("rebel:outbreak", 0) for r in rs) / n
        ind = sum(r["stats"].get("rebel:independence", 0) for r in rs) / n
        vts = ", ".join(f"{VNAME.get(v, v)} {c:g}" for v, c in vt.most_common()) or "–"
        et = f"{sum(el) / len(el):.0f}" if el else "–"
        L = LEADER_BY_KEY[k]
        p(f"| {i} | {L['name']} | {cat_of.get(k, '')} | {L['aggr']} | {n} | {wr * 100:.1f}% | {vts} | "
          f"{len(el) / n * 100:.1f}% | {et} | {reg[0]:.1f} / {reg[1]:.1f} / {reg[2]:.1f} | "
          f"{gdp[0]:,.0f} / {gdp[1]:,.0f} / {gdp[2]:,.0f} | {reb:.1f} | {ind:.2f} |")
    p("")
    # 권역별(조선 8도, 시작 지역 기준)
    p("## 1-2. 시작 권역(조선 8도)별 결과")
    p("")
    p("| 권역 | 시작 세력 수 | 승률 | 승리 유형(횟수) | 멸망률 | 평균 멸망 턴 | 지역 120 / 240 / 480 | GDP 120 / 240 / 480 |")
    p("|---|---|---|---|---|---|---|---|")
    by8 = defaultdict(list)
    for r in rows:
        if "do8" in r:
            by8[r["do8"]].append(r)
    order = ["경기", "충청", "전라", "경상", "강원", "황해", "평안", "함경"]
    for d in sorted(by8, key=lambda d: -sum(r["win"] for r in by8[d]) / len(by8[d])):
        rs = by8[d]
        n = len(rs)
        el = [r["eliminated"] for r in rs if r["eliminated"] is not None and r["eliminated"] <= 480]
        vt = Counter()
        for r in rs:
            if r["win"]:
                vt[r["_victory"]] += r["win"]
        reg = [sum(r["regions"][str(t)] for r in rs) / n for t in SNAPS]
        gdp = [sum(r["gdp"][str(t)] for r in rs) / n for t in SNAPS]
        vts = ", ".join(f"{VNAME.get(v, v)} {c:g}" for v, c in vt.most_common()) or "–"
        et = f"{sum(el) / len(el):.0f}" if el else "–"
        p(f"| {d}도 | {n} ({n / len(rows) * 100:.0f}%) | {sum(r['win'] for r in rs) / n * 100:.1f}% | {vts} | "
          f"{len(el) / n * 100:.1f}% | {et} | {reg[0]:.1f} / {reg[1]:.1f} / {reg[2]:.1f} | "
          f"{gdp[0]:,.0f} / {gdp[1]:,.0f} / {gdp[2]:,.0f} |")
    missing = [d for d in order if d not in by8]
    if missing:
        p(f"(시작 세력 없음: {', '.join(missing)})")
    p("")
    # 행동 분석 — 세력·판 단위 평균
    nf = len(rows)

    def avg(key):
        return sum(r["stats"].get(key, 0) for r in rows) / nf

    def tot(key):
        return sum(r["stats"].get(key, 0) for r in rows)
    p("## 2. AI 행동 패턴 (세력 1개가 한 판에서 하는 평균)")
    p("")
    p("### 건설 (완공 기준)")
    bl = Counter()
    for r in rows:
        for kk, v in r["stats"].items():
            if kk.startswith("build:"):
                bl[kk[6:]] += v
    total_b = sum(bl.values())
    p(f"판당 완공 {total_b / nf:.1f}건 · 과학 단계 {sum(avg('science:' + k) for k in C.SCIENCE_STEPS):.2f} · 천도 {avg('capital'):.2f}")
    p("")
    p("| 건물 | 판당 완공 | 비중 |")
    p("|---|---|---|")
    for kk, v in bl.most_common():
        p(f"| {BLD.get(kk, kk)} | {v / nf:.1f} | {v / total_b * 100:.1f}% |")
    p("")
    p("### 확장 (지역 획득·상실)")
    p("| 경로 | 판당 지역 수 |")
    p("|---|---|")
    for kk, nm in (("gain:annex", "편입(중립)"), ("gain:conquer_neutral", "무력 점령(중립)"),
                   ("gain:conquer_enemy", "무력 점령(타국)"), ("gain:trade", "거래로 받음"),
                   ("lost:conquest", "점령당해 잃음"), ("lost:rebel", "반란 독립으로 잃음"), ("lost:trade", "거래로 넘김")):
        p(f"| {nm} | {avg(kk):.2f} |")
    p("")
    p("### 전쟁")
    decl = [r for r in rows if r["stats"].get("war:declare")]
    first = [r["stats"]["war:first_turn"] for r in rows if "war:first_turn" in r["stats"]]
    peace = tot("war:peace")
    p(f"- 직접 선전포고 {avg('war:declare'):.2f}회/판, 선전포고를 당함 {avg('war:received'):.2f}회, "
      f"동맹 자동 참전 {avg('war:ally_join'):.2f}회, 연합 공동 참전 {avg('war:coalition_join'):.2f}회")
    p(f"- 한 번이라도 선전포고한 세력 {len(decl) / nf * 100:.0f}%, 첫 선전포고 평균 {sum(first) / max(1, len(first)):.0f}턴"
      f" (중앙값 {sorted(first)[len(first) // 2] if first else '-'}턴)")
    p(f"- 강화 {avg('war:peace'):.2f}회/판, 강화로 끝난 전쟁의 평균 기간 {tot('war:turns') / max(1, peace):.0f}턴, "
      f"전쟁 1회당 빼앗은 지역 {tot('war:regions_taken') / max(1, peace):.2f}곳")
    p(f"- 전투(교전 이벤트) {avg('battle'):.1f}회/판")
    # 첫 전쟁 시점 분포
    bins = Counter(min(4, t // 96) for t in first)
    p("- 첫 선전포고 시점: " + ", ".join(f"{b * 96}~{b * 96 + 95 if b < 4 else '480'}턴 {bins[b]}"
                                    for b in range(5)))
    p("")
    p("### 병종 (생산 완료 기준)")
    ul = Counter()
    for r in rows:
        for kk, v in r["stats"].items():
            if kk.startswith("unit:"):
                ul[kk[5:]] += v
    tu = sum(ul.values())
    end = Counter()
    for r in rows:
        end.update(r["army_end"])
    te = sum(end.values())
    p(f"판당 생산 {tu / nf:.1f}개")
    p("")
    p("| 병종 | 판당 생산 | 생산 비중 | 480턴 보유 비중 |")
    p("|---|---|---|---|")
    for kk, v in ul.most_common():
        p(f"| {C.UNITS[kk]['name']} | {v / nf:.1f} | {v / tu * 100:.1f}% | {end[kk] / max(1, te) * 100:.1f}% |")
    p("")
    p("### 외교")
    p("AI끼리는 제안 단계 없이 양쪽 조건이 맞으면 바로 체결한다.")
    p("")
    p("| 조약 | 한 판 전체 체결 건수 | 세력당 참여 |")
    p("|---|---|---|")
    for kk, nm in (("nonaggr", "불가침"), ("passage", "통행권"), ("alliance", "동맹"), ("coalition", "연합")):
        p(f"| {nm} | {tot('treaty:' + kk) / 2 / ng:.1f} | {avg('treaty:' + kk):.2f} |")
    p(f"| 강화 | {tot('war:peace') / 2 / ng:.1f} | {avg('war:peace'):.2f} |")
    p("")
    p(f"- 우호 선언 {avg('diplo:friendship'):.2f}회/판, 비난 {avg('diplo:denounce'):.2f}회, "
      f"불가침 파기 {avg('diplo:break_nonaggr'):.2f}회, 동맹 탈퇴 {avg('diplo:leave_alliance'):.2f}회, "
      f"연합 탈퇴 {avg('diplo:leave_coalition'):.2f}회")
    gov = Counter(r["gov"] for r in rows)
    p("- 정치체제 선택: " + ", ".join(f"{GOV_BY_KEY.get(k, {}).get('name', k)} {v / nf * 100:.0f}%"
                                for k, v in gov.most_common()))
    taxes = [r["tax"] for r in rows if r["tax"] is not None]
    p(f"- 평균 세율 {sum(taxes) / len(taxes) * 100:.1f}%")
    p("")
    p("### 거래")
    p(f"- 세력 간 거래 성사 {avg('trade:proposed'):.2f}건/판(제안 측 기준)")
    tg = Counter()
    for r in rows:
        for kk, v in r["stats"].items():
            if kk.startswith("trade_give:"):
                tg[kk[11:]] += v
    if tg:
        p("- 건넨 품목: " + ", ".join(f"{kk} {v / nf:.2f}" for kk, v in tg.most_common()))
    p("")
    p("| 자원 | 판당 구매 횟수 | 판당 구매량 | 판당 판매 횟수 | 판당 판매량 |")
    p("|---|---|---|---|---|")
    for res in ("food", "oil", "coal", "elec"):
        p(f"| {C.RESOURCE_NAMES[res]} | {avg('buy_n:' + res):.1f} | {avg('buy:' + res):.0f} | "
          f"{avg('sell_n:' + res):.1f} | {avg('sell:' + res):.0f} |")
    p("")
    p("### 반란 대응")
    ob = tot("rebel:outbreak")
    p(f"- 반란 발생 {avg('rebel:outbreak'):.2f}회/판 → 요구 수용(지불) {tot('rebel:pay') / max(1, ob) * 100:.0f}%, "
      f"세율 인하 {tot('rebel:tax') / max(1, ob) * 100:.0f}%, 진압 성공 {tot('rebel:suppress') / max(1, ob) * 100:.0f}%, "
      f"진압 실패·독립 {tot('rebel:independence') / max(1, ob) * 100:.0f}%")
    p("")
    # 지도자별 행동 요약
    p("### 지도자별 행동 요약 (판당)")
    p("")
    p("| 지도자 | 호전 | 편입 | 점령(중립) | 점령(타국) | 선전포고 | 당함 | 전투 | 유닛 생산 | 건물 완공 | 평균 세율 |")
    p("|---|---|---|---|---|---|---|---|---|---|---|")
    for wr, k, rs, el, vt in stats:
        n = len(rs)

        def a(key, rs=rs, n=n):
            return sum(r["stats"].get(key, 0) for r in rs) / n
        units = sum(v for r in rs for kk, v in r["stats"].items() if kk.startswith("unit:")) / n
        blds = sum(v for r in rs for kk, v in r["stats"].items() if kk.startswith("build:")) / n
        tx = [r["tax"] for r in rs if r["tax"] is not None]
        p(f"| {LEADER_BY_KEY[k]['name']} | {LEADER_BY_KEY[k]['aggr']} | {a('gain:annex'):.1f} | "
          f"{a('gain:conquer_neutral'):.1f} | {a('gain:conquer_enemy'):.1f} | {a('war:declare'):.2f} | "
          f"{a('war:received'):.2f} | {a('battle'):.1f} | {units:.1f} | {blds:.1f} | "
          f"{sum(tx) / max(1, len(tx)) * 100:.1f}% |")
    print("\n".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--turns", type=int, default=480)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="behavior_runs.jsonl")
    ap.add_argument("--report")
    a = ap.parse_args()
    if a.report:
        report(a.report)
    else:
        simulate(a)


if __name__ == "__main__":
    main()
