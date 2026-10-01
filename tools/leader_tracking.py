"""지도자 효과 발동·AI 행동 기록 (tools/leader_balance.py 가 시뮬레이션 중에 설치).

- 효과 발동: Game.mods() 가 돌려주는 Mods 를 세력별로 감싸, 실제 게임 처리 중에 그 세력의 효과 키가
  쓰이면 (세력, 키) 별로 '발동한 턴'과 횟수를 센다. AI 가 선택지를 평가하는 계산(선택지 목록·교전 예측·
  전력 추정 등)은 발동으로 치지 않는다. 비용·건설 시간 효과는 실제로 착공한 작업으로, 세율·전쟁 기간처럼
  매 턴 조회만 되는 효과는 실제 조건(세율 구간, 전쟁 중 등)으로 따로 센다.
- 행동: 착공(종류별)·유닛 생산·공격 방식·선전포고·강화·조약·반란·세율·전쟁 피로·승리 목표,
  기습 성공/실패·돌격 방어선 파괴·폭격 건물 파괴·점령 저항·탈환·전쟁광 평판·사기 저하·징집 피로.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

# 실제 조건으로 따로 세는 효과(일반 조회 카운트는 무시)
SPECIAL = {"tax_over10", "tax_over15", "tax_max", "tax_lock", "war_weary_rate", "avg_rebel", "happy_cap",
           "neutral_diplomacy", "start_money", "start_opinion", "treaty_threshold", "trade_m",
           "cost_air", "cost_naval", "cost_tank", "cost_mil", "inf_cost_early", "cost_line", "cost_factory",
           "build_time_prod", "build_time_all", "build_time_factory", "landmark_turns", "occ_time",
           "war_start_weary", "instant_annex_h"}
AIR = {"ftr", "bmb", "stl"}
NAVAL = {"lst", "dd", "cv"}


class Tracker:
    def __init__(self):
        self.plan = 0
        self.turn_hits = defaultdict(set)      # (fid, key) -> {turn}
        self.counts = Counter()                # (fid, key) -> 횟수
        self.beh = defaultdict(Counter)        # fid -> 행동 Counter
        self.goals = defaultdict(Counter)      # fid -> 승리 목표(연 1회 표본)
        self.taxes = defaultdict(list)
        self.weary = defaultdict(list)
        self.eff = defaultdict(list)           # 실질 평균 행복도
        self.alive_turns = Counter()
        self.g = None

    def hit(self, fid, key, n=1):
        if self.g is None:
            return
        self.turn_hits[(fid, key)].add(self.g.turn)
        self.counts[(fid, key)] += n


def install(G, D, A):
    """G=korciv.game, D=diplomacy, A=ai 모듈에 기록용 래퍼를 단다. Tracker 반환."""
    from korciv.leaders import Mods
    T = Tracker()

    class TrackMods(Mods):
        def _rec(self, key):
            if not T.plan and key in self._keys and key not in SPECIAL:
                T.hit(self._fid, key)

        def mult(self, key):
            self._rec(key)
            return Mods.mult(self, key)

        def add(self, key):
            self._rec(key)
            return Mods.add(self, key)

        def value(self, key, default=None):
            self._rec(key)
            return Mods.value(self, key, default)

    orig_mods = G.Game.mods

    def mods(self, fid):
        m = orig_mods(self, fid)
        if fid >= 0 and not isinstance(m, TrackMods):
            m.__class__ = TrackMods
            m._fid = fid
            m._keys = {k for fx in m.fx for k in fx}
        return m
    G.Game.mods = mods

    def planning(obj, name):
        orig = getattr(obj, name)

        def wrapped(*a, **k):
            T.plan += 1
            try:
                return orig(*a, **k)
            finally:
                T.plan -= 1
        setattr(obj, name, wrapped)

    for name in ("options", "annex_targets", "preview_attack", "region_value", "reachable", "unit_cost",
                 "region_output_estimate", "build_time", "start_project", "plan_route", "neutral_turns",
                 "annex_cost", "rebellion_accept_cost", "suppress_chance_preview"):
        if hasattr(G.Game, name):
            planning(G.Game, name)
    for name in ("war_assessment", "_consider_war", "perceived_power", "front_analysis", "choose_victory_goal",
                 "threat_map"):
        planning(A, name)
    for name in ("treaty_check", "evaluate_offer", "trade_m"):
        planning(D, name)

    # 착공: 비용·건설 시간 효과는 실제 착공으로 센다
    orig_start = G.Game.start_project

    def start_project(self, fid, rid, kind, key, border=None, name=None):
        ok, msg = orig_start(self, fid, rid, kind, key, border=border, name=name)
        if ok and fid >= 0:
            b = T.beh[fid]
            b[f"start_{kind}"] += 1
            keys = self.mods(fid)._keys
            fx = []
            if kind == "unit":
                b[f"unit_{key}"] += 1
                fx.append("cost_mil")
                if key == "tank":
                    fx.append("cost_tank")
                if key in AIR:
                    fx.append("cost_air")
                if key in NAVAL:
                    fx.append("cost_naval")
                if key == "inf" and self.turn <= 48:
                    fx.append("inf_cost_early")
            elif kind == "build":
                b[f"build_{key}"] += 1
                fx.append("build_time_all")
                if key in ("farm", "fishery", "factory", "bank", "power", "liquefy", "specialty", "extract"):
                    fx.append("build_time_prod")
                if key == "factory":
                    fx += ["build_time_factory", "cost_factory"]
                if key == "line":
                    fx.append("cost_line")
            elif kind == "annex":
                fx.append("occ_time")
            elif kind == "landmark":
                fx.append("landmark_turns")
            for k in fx:
                if k in keys:
                    T.hit(fid, k)
        return ok, msg
    G.Game.start_project = start_project

    orig_start_war = D._start_war

    def _start_war(g, a, b, happiness=True, aggressor=None):
        if happiness:                     # 선전포고는 AI 판단 함수 안에서 일어나므로 따로 센다
            for x in (a, b):
                if "war_start_weary" in g.mods(x)._keys:
                    T.hit(x, "war_start_weary")
        return orig_start_war(g, a, b, happiness, aggressor)
    D._start_war = _start_war

    orig_complete = G.Game.complete_occupation

    def complete_occupation(self, fid, rid):
        rr = self.regions[rid]
        old = rr.owner
        if old >= 0 and rr.resist and self.resisting(rr) and rr.resist.get("from") == fid:
            T.beh[fid]["retake"] += 1                  # 저항 중인 옛 영토 탈환
        r = orig_complete(self, fid, rid)
        if old >= 0 and fid >= 0:
            T.beh[fid]["resist_start"] += 1
        return r
    G.Game.complete_occupation = complete_occupation

    orig_bombard = G.Game._bombard

    def _bombard(self, a, tgt, units):
        n0 = sum(self.regions[tgt].b.get(k, 0) for k in self.regions[tgt].b) + sum(self.regions[tgt].lines.values())
        owner = a.owner
        kinds = ("gun" if units.get("art") or units.get("dd") else "") + ("air" if units.get("bmb") or units.get("stl") else "")
        r = orig_bombard(self, a, tgt, units)
        n1 = sum(self.regions[tgt].b.get(k, 0) for k in self.regions[tgt].b) + sum(self.regions[tgt].lines.values())
        T.beh[owner][f"bomb_{kinds or 'none'}"] += 1
        if n1 < n0:
            T.beh[owner]["bomb_hit"] += 1
        return r
    G.Game._bombard = _bombard

    orig_begin = G.Game.begin_occupation

    def begin_occupation(self, fid, rid):
        before = self.regions[rid].occ
        old_owner = self.regions[rid].owner
        r = orig_begin(self, fid, rid)
        if old_owner >= 0 and old_owner != fid and self.regions[rid].owner == fid \
                and "instant_annex_h" in self.mods(fid)._keys:
            T.hit(fid, "instant_annex_h")          # 실제 즉시 병합
        occ = self.regions[rid].occ
        if occ and occ is not before and occ["by"] == fid and "occ_time" in self.mods(fid)._keys:
            T.hit(fid, "occ_time")
        return r
    G.Game.begin_occupation = begin_occupation

    orig_order = G.Game.order_army

    def order_army(self, aid, target, mode="assault", force_bombard=False):
        r = orig_order(self, aid, target, mode, force_bombard)
        a = self.armies.get(aid)
        if a and a.order and a.owner >= 0:
            t = a.order["type"]
            T.beh[a.owner][f"order_{t}" + (f"_{a.order.get('mode')}" if t == "attack" else "")] += 1
        return r
    G.Game.order_army = order_army

    orig_peace = D.make_peace

    def make_peace(g, a, b, _done=None):
        if _done is None and D.at_war(g, a, b):
            T.beh[a]["peace"] += 1
            T.beh[b]["peace"] += 1
        return orig_peace(g, a, b, _done)
    D.make_peace = make_peace

    orig_sign = D.sign_treaty

    def sign_treaty(g, a, b, kind):
        for x in (a, b):
            T.beh[x][f"treaty_{kind}"] += 1
            if kind != "peace" and "treaty_threshold" in g.mods(x)._keys:
                T.hit(x, "treaty_threshold")
        return orig_sign(g, a, b, kind)
    D.sign_treaty = sign_treaty

    orig_event = G.Game.event

    def event(self, kind, text, region=None, fids=()):
        if kind in ("rebel", "captured", "famine", "occupy") and fids:
            T.beh[fids[0]][f"ev_{kind}"] += 1
        if kind == "battle" and fids:
            if "기습 성공" in text:
                T.beh[fids[0]]["surprise_win"] += 1
            elif "기습 실패" in text:
                T.beh[fids[0]]["surprise_fail"] += 1
            elif "방어선" in text and "단계" in text:
                T.beh[fids[0]]["line_break"] += 1
            if text.startswith("돌격"):
                T.beh[fids[0]]["assault_battle"] += 1
        if kind == "war" and fids:
            m = re.search(r"우호도 (-\d+)", text)
            if m:
                T.beh[fids[0]]["warmonger_pen"] += -int(m.group(1))
                if int(m.group(1)) < -10:
                    T.beh[fids[0]]["warmonger_repeat"] += 1
        return orig_event(self, kind, text, region, fids)
    G.Game.event = event

    return T


def after_turn(T, g):
    """매 턴 끝: 조회만으로는 알 수 없는 효과를 실제 조건으로 센다."""
    from korciv import config as C
    from korciv import diplomacy as D
    T.g = g
    for f in g.factions:
        if not f.alive:
            continue
        fid = f.id
        T.alive_turns[fid] += 1
        keys = g.mods(fid)._keys
        T.taxes[fid].append(f.tax)
        T.weary[fid].append(getattr(f, "war_weary", 0.0))
        T.eff[fid].append(g.avg_happiness(fid))
        if g.morale(fid) < 1:
            T.beh[fid]["low_morale_turns"] += 1
        regs = g.regions_of(fid)
        T.beh[fid]["conscript_region_turns"] += sum(1 for r in regs if r.conscript > 0)
        T.beh[fid]["resist_region_turns"] += sum(1 for r in regs if g.resisting(r))
        if g.turn % C.TURNS_PER_YEAR == 2 and f.ai.get("victory_goal"):
            T.goals[fid][f.ai["victory_goal"]] += 1
        at_war = bool(D.enemies(g, fid))
        if at_war:
            T.beh[fid]["war_turns"] += 1
        cond = {
            "tax_over10": f.tax > 0.10 + 1e-9,
            "tax_over15": f.tax > 0.15 + 1e-9,
            "tax_max": f.tax >= g.tax_max(fid) - 1e-9,
            "tax_lock": f.tax_locked_until > g.turn,
            "war_weary_rate": at_war,
            "avg_rebel": g.avg_happiness(fid) <= -30,
            "happy_cap": any(r.happy >= g.mods(fid).value("happy_cap", C.HAPPY_MAX) - 0.5 for r in g.regions_of(fid)),
            "start_money": g.turn == 2,
            "start_opinion": g.turn == 2,
        }
        if "neutral_diplomacy" in keys:
            friends = {x for x in g.alive_ids() if x != fid and D.is_friend(g, fid, x)}
            mine = set(D.enemies(g, fid))
            cond["neutral_diplomacy"] = any(
                (set(D.enemies(g, b)) & friends) or ({x for x in friends if D.is_friend(g, b, x)} & mine)
                for b in g.alive_ids() if b != fid)
        for k, on in cond.items():
            if on and k in keys:
                T.hit(fid, k)


def summary(T, fid):
    keys = sorted({k for (f, k) in T.counts if f == fid} | {k for (f, k) in T.turn_hits if f == fid})
    alive = max(1, T.alive_turns[fid])
    fx = {k: {"turns": len(T.turn_hits[(fid, k)]), "rate": len(T.turn_hits[(fid, k)]) / alive,
              "count": T.counts[(fid, k)]} for k in keys}
    tx = T.taxes[fid] or [0]
    ww = T.weary[fid] or [0]
    eh = T.eff[fid] or [0]
    return {"fx": fx, "beh": dict(T.beh[fid]), "goals": dict(T.goals[fid]), "alive_turns": alive,
            "tax_avg": sum(tx) / len(tx), "weary_avg": sum(ww) / len(ww), "weary_max": max(ww),
            "eff_happy_avg": sum(eh) / len(eh)}
