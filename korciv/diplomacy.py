"""외교 (기획서 7절): 우호도, 4단계 관계, 거래 판정, 선전포고·강화."""
from __future__ import annotations

import math

from . import config as C
from .leaders import gov_opinion_bias
from .state import NEUTRAL

STAGE_NAMES = {-1: "전쟁", 0: "관계 없음", 1: "우호관계", 2: "통행권·불가침", 3: "동맹", 4: "연합"}
TREATY_NAMES = {"nonaggr": "불가침조약", "passage": "군사통행권", "alliance": "동맹",
                "coalition": "연합", "peace": "강화"}


def pair(a, b):
    return (a, b) if a < b else (b, a)


class DiploState:
    def __init__(self):
        self.op: dict = {}            # (a, b) -> a가 b를 보는 우호도
        self.wars: dict = {}          # pair -> {"start", "declarer", "score": {fid: 점수}}
        self.nonaggr: dict = {}       # pair -> 만료 턴
        self.passage: dict = {}       # pair -> 만료 턴
        self.alliance: dict = {}      # pair -> 체결 턴
        self.friends: set = set()     # 우호관계 pair
        self.coalitions: dict = {}    # cid -> {"members": set, "since": 턴}
        self.no_attack_until: dict = {}   # (선포국, 대상) -> 턴 (의원내각제)
        self.rejected: set = set()    # 이번 턴 거절된 (제안국, 상대)
        self.peace_streak = 0
        self.next_cid = 1
        self.peace_until: dict = {}    # pair -> 강화 불가침 만료 턴


# ------------------------------------------------------------------ 조회
def opinion(g, a, b) -> float:
    return g.dip.op.get((a, b), 0.0)


def add_opinion(g, a, b, delta):
    if a == b or a == NEUTRAL or b == NEUTRAL:
        return
    v = g.dip.op.get((a, b), 0.0) + delta
    g.dip.op[(a, b)] = max(-100.0, min(100.0, v))


def mutual(g, a, b) -> float:
    fa, fb = g.factions[a], g.factions[b]
    if fa.is_ai and fb.is_ai:
        return min(opinion(g, a, b), opinion(g, b, a))
    if fa.is_ai:
        return opinion(g, a, b)
    if fb.is_ai:
        return opinion(g, b, a)
    return 0.0


def at_war(g, a, b) -> bool:
    if a == NEUTRAL or b == NEUTRAL:
        return a != b
    return pair(a, b) in g.dip.wars


def coalition_of(g, a):
    for cid, c in g.dip.coalitions.items():
        if a in c["members"]:
            return cid
    return None


def same_coalition(g, a, b) -> bool:
    c = coalition_of(g, a)
    return c is not None and b in g.dip.coalitions[c]["members"]


def allied(g, a, b) -> bool:
    if a == b:
        return True
    if a == NEUTRAL or b == NEUTRAL:
        return False
    return pair(a, b) in g.dip.alliance or same_coalition(g, a, b)


def has_passage(g, a, b) -> bool:
    """a 가 b 의 영토를 지날 수 있는가."""
    return allied(g, a, b) or pair(a, b) in g.dip.passage


def has_nonaggr(g, a, b) -> bool:
    return pair(a, b) in g.dip.nonaggr or pair(a, b) in g.dip.alliance or same_coalition(g, a, b)


def is_friend(g, a, b) -> bool:
    return pair(a, b) in g.dip.friends or allied(g, a, b)


def stage(g, a, b) -> int:
    if at_war(g, a, b):
        return -1
    if same_coalition(g, a, b):
        return 4
    if pair(a, b) in g.dip.alliance:
        return 3
    if pair(a, b) in g.dip.nonaggr or pair(a, b) in g.dip.passage:
        return 2
    if pair(a, b) in g.dip.friends:
        return 1
    return 0


def peace_left(g, a, b) -> int:
    """강화 후 파기할 수 없는 불가침 남은 턴."""
    return max(0, getattr(g.dip, "peace_until", {}).get(pair(a, b), 0) - g.turn)


def enemies(g, a):
    return [b for b in g.alive_ids() if b != a and at_war(g, a, b)]


def threshold(g, a, b, base):
    t = base + g.mods(a).add("treaty_threshold") + g.mods(b).add("treaty_threshold")
    if g.factions[a].is_ai and g.factions[a].ai.get("victory_goal") == "peace":
        t -= 10                              # 평화승리를 노리는 AI는 조약에 적극적

    if g.hegemon is not None and g.hegemon not in (a, b):
        t -= C.HEGEMON_TREATY_DISCOUNT   # 공동 견제 대상이 있으면 뭉치기 쉽다
    return t


def trade_m(g, ai, proposer) -> float:
    m = C.TRADE_M_BASE - opinion(g, ai, proposer) / C.TRADE_M_DIV
    if is_friend(g, ai, proposer):
        m -= C.FRIEND_M
    m += g.mods(proposer).add("trade_m")
    if g.hegemon == proposer:
        m += C.HEGEMON_TRADE_M
    return max(0.3, m)


# ------------------------------------------------------------------ 전쟁·강화
def declare_war(g, a, b, reason="선전포고", _joined=None):
    """a 가 b 에게 선전포고. 동맹 자동 참전, 연합 공동 결정."""
    if a == b or at_war(g, a, b) or not g.factions[a].alive or not g.factions[b].alive:
        return False, "이미 전쟁 중이거나 대상이 없습니다."
    if has_nonaggr(g, a, b):
        return False, "불가침조약·동맹 중에는 먼저 조약을 파기해야 합니다."
    joined = _joined if _joined is not None else set()
    _start_war(g, a, b)
    add_opinion(g, b, a, C.OP_WAR_DECLARED)
    for c in g.alive_ids():
        if c not in (a, b) and is_friend(g, c, b):
            if not g.mods(c).value("neutral_diplomacy"):
                add_opinion(g, c, a, C.OP_FRIEND_ATTACKED)
    g.event("war", f"{g.fname(a)}이(가) {g.fname(b)}에 {reason}했습니다.", fids=(a, b))
    joined.add((a, b))
    # 수비측 동맹·연합 자동 참전
    for c in list(g.alive_ids()):
        if c in (a, b):
            continue
        if allied(g, c, b) and not at_war(g, c, a) and (c, a) not in joined:
            _clear_treaties(g, c, a)
            declare_war(g, c, a, reason="동맹 참전으로 선전포고", _joined=joined)
    # 공격측 연합 회원 공동 참전
    cid = coalition_of(g, a)
    if cid is not None:
        for c in list(g.dip.coalitions[cid]["members"]):
            if c not in (a, b) and not at_war(g, c, b) and (c, b) not in joined and g.factions[c].alive:
                _clear_treaties(g, c, b)
                declare_war(g, c, b, reason="연합 공동 선전포고", _joined=joined)
    return True, ""


def _clear_treaties(g, a, b):
    p = pair(a, b)
    g.dip.nonaggr.pop(p, None)
    g.dip.passage.pop(p, None)
    g.dip.alliance.pop(p, None)
    g.dip.friends.discard(p)


def _start_war(g, a, b, happiness=True):
    p = pair(a, b)
    _clear_treaties(g, a, b)
    g.dip.wars[p] = {"start": g.turn, "declarer": a, "score": {a: 0.0, b: 0.0},
                     "regs0": {a: g.region_count(a), b: g.region_count(b)}, "taken": {a: 0, b: 0}}
    delay = g.mods(a).value("parliament_delay", 0)
    if delay:
        g.dip.no_attack_until[(a, b)] = g.turn + delay
    for f in (a, b) if happiness else ():
        base = g.mods(f).value("war_start_happy", C.WAR_START_HAPPY)
        base *= g.mods(f).value("war_start_mult", 1.0)
        fac = g.factions[f]
        # 선전포고 행복도 감소는 '전쟁 피로'로 쌓여 종전 후 턴당 0.5씩만 회복된다
        fac.war_weary = min(C.WAR_WEARY_MAX, getattr(fac, "war_weary", 0.0) - base)
    # 통행권으로 상대 영토에 있던 병력은 가장 가까운 자국 영토로
    for army in list(g.armies.values()):
        if army.owner in (a, b) and not g.world.is_sea(army.loc):
            owner = g.regions[army.loc].owner
            other = b if army.owner == a else a
            if owner == other:
                g.teleport_home(army)


def make_peace(g, a, b, _done=None):
    done = _done if _done is not None else set()
    p = pair(a, b)
    if p not in g.dip.wars or p in done:
        return
    done.add(p)
    del g.dip.wars[p]
    g.dip.nonaggr[p] = max(g.dip.nonaggr.get(p, 0), g.turn + C.PEACE_TREATY_TURNS)
    if not hasattr(g.dip, "peace_until"):
        g.dip.peace_until = {}
    g.dip.peace_until[p] = g.turn + C.PEACE_TREATY_TURNS   # 강화 불가침: 이 기간에는 파기 불가
    g.dip.no_attack_until.pop((a, b), None)
    g.dip.no_attack_until.pop((b, a), None)
    for r in g.regions.values():
        if r.occ and ((r.occ["by"] == a and r.owner == b) or (r.occ["by"] == b and r.owner == a)):
            r.occ = None
    for army in list(g.armies.values()):
        if army.owner in (a, b) and not g.world.is_sea(army.loc):
            other = b if army.owner == a else a
            if g.regions[army.loc].owner == other:
                g.teleport_home(army)
    g.event("peace", f"{g.fname(a)}와(과) {g.fname(b)}이(가) 강화했습니다. (불가침 {C.PEACE_TREATY_TURNS}턴)", fids=(a, b))
    for side, other in ((a, b), (b, a)):
        cid = coalition_of(g, side)
        if cid is not None:
            for c in list(g.dip.coalitions[cid]["members"]):
                if c != side and at_war(g, c, other):
                    make_peace(g, c, other, done)


def op_baseline(g, a, b) -> float:
    """a 가 b 를 볼 때 우호도가 수렴하는 기본값(정치체제 관계)."""
    return gov_opinion_bias(g.factions[a].gov, g.factions[b].gov)


def war_info(g, a, b) -> dict:
    """전쟁 경과: 시작 이후 턴, a 가 잃은 지역 비율, 서로 빼앗은 지역 수."""
    w = g.dip.wars.get(pair(a, b))
    if not w:
        return {}
    regs0 = w.get("regs0", {})
    taken = w.get("taken", {})
    n0 = max(1, regs0.get(a, g.region_count(a)))
    lost = taken.get(b, 0)
    return {"turns": g.turn - w["start"], "declarer": w["declarer"], "lost": lost, "gained": taken.get(a, 0),
            "lost_frac": lost / n0, "score": war_score(g, a, b)}


def war_score(g, a, b) -> float:
    """a 입장의 전쟁 점수(양수면 a 유리)."""
    w = g.dip.wars.get(pair(a, b))
    if not w:
        return 0.0
    return w["score"].get(a, 0.0) - w["score"].get(b, 0.0)


def add_war_score(g, a, b, v):
    w = g.dip.wars.get(pair(a, b))
    if w:
        w["score"][a] = w["score"].get(a, 0.0) + v


def break_nonaggr(g, a, b):
    p = pair(a, b)
    if peace_left(g, a, b) > 0:
        return False, f"강화 불가침 기간입니다({peace_left(g, a, b)}턴 남음). 파기할 수 없습니다."
    if p in g.dip.alliance or same_coalition(g, a, b):
        return False, "동맹·연합은 먼저 탈퇴해야 합니다."
    if p not in g.dip.nonaggr:
        return False, "불가침조약이 없습니다."
    del g.dip.nonaggr[p]
    for c in g.alive_ids():
        if c != a:
            add_opinion(g, c, a, C.OP_NONAGGR_BROKEN)
    g.event("diplo", f"{g.fname(a)}이(가) {g.fname(b)}과(와)의 불가침조약을 파기했습니다.", fids=(a, b))
    return True, ""


def leave_alliance(g, a, b):
    p = pair(a, b)
    if p in g.dip.alliance:
        del g.dip.alliance[p]
        g.dip.nonaggr[p] = g.turn + C.TREATY_TURNS
        g.event("diplo", f"{g.fname(a)}이(가) {g.fname(b)}과(와)의 동맹에서 탈퇴했습니다.", fids=(a, b))


def leave_coalition(g, a):
    cid = coalition_of(g, a)
    if cid is None:
        return
    c = g.dip.coalitions[cid]
    c["members"].discard(a)
    for m in c["members"]:
        add_opinion(g, m, a, C.OP_COALITION_LEAVE)
    if len(c["members"]) < 2:
        del g.dip.coalitions[cid]
    g.event("diplo", f"{g.fname(a)}이(가) 연합에서 탈퇴했습니다.", fids=(a,))


# ------------------------------------------------------------------ 조약
def treaty_check(g, ai, proposer, kind):
    """AI 가 조약 제안을 받을지. (수락 여부, 이유)"""
    if (proposer, ai) in g.dip.rejected:
        return False, "이번 턴에는 다시 제안할 수 없습니다."
    op = opinion(g, ai, proposer) if g.factions[ai].is_ai else 100
    p = pair(ai, proposer)
    if kind == "peace":
        if not at_war(g, ai, proposer):
            return False, "전쟁 중이 아닙니다."
        from . import ai as AI
        a = AI.war_assessment(g, ai, proposer)
        ok = a["desire"] >= C.AI_PEACE_ACCEPT
        return ok, AI.peace_reason(a, ok)
    if at_war(g, ai, proposer):
        return False, "전쟁 중입니다."
    if kind in ("nonaggr", "passage"):
        need = threshold(g, ai, proposer, C.TREATY_MIN)
        if kind == "nonaggr" and g.factions[ai].is_ai:
            # 훨씬 강해 보이는 상대와는 더 낮은 우호도에서도 불가침을 받아들인다(안보)
            from . import ai as AI
            if g.mil_power(ai) < 0.7 * AI.perceived_power(g, ai, proposer):
                need -= C.NONAGGR_FEAR_DISCOUNT
        if kind == "nonaggr" and p in g.dip.nonaggr:
            return False, "이미 체결되어 있습니다."
        if kind == "passage" and p in g.dip.passage:
            return False, "이미 체결되어 있습니다."
        return (op >= need, f"우호도 {op:.0f} / 필요 {need:.0f}")
    if kind == "alliance":
        if p in g.dip.alliance:
            return False, "이미 동맹입니다."
        if p not in g.dip.nonaggr and p not in g.dip.passage:
            return False, "한 단계를 건너뛴 제안입니다(먼저 조약)."
        need = threshold(g, ai, proposer, C.ALLIANCE_MIN)
        if op < need:
            return False, f"우호도 {op:.0f} / 필요 {need:.0f}"
        common = set(enemies(g, ai)) & set(enemies(g, proposer))
        heg = g.hegemon is not None and g.hegemon not in (ai, proposer)
        if not common and not heg:
            return False, "공동의 적이나 견제 대상이 없습니다."
        return True, "공동의 적/견제 대상"
    if kind == "coalition":
        if p not in g.dip.alliance:
            return False, "한 단계를 건너뛴 제안입니다(먼저 동맹)."
        if g.turn - g.dip.alliance[p] < C.COALITION_ALLIANCE_TURNS:
            return False, f"동맹 {C.COALITION_ALLIANCE_TURNS}턴 이상이 필요합니다."
        need = threshold(g, ai, proposer, C.COALITION_MIN)
        if op < need:
            return False, f"우호도 {op:.0f} / 필요 {need:.0f}"
        members = set()
        for x in (ai, proposer):
            cid = coalition_of(g, x)
            if cid is not None:
                members |= g.dip.coalitions[cid]["members"]
        members |= {ai, proposer}
        leader = max(members, key=lambda f: g.power.get(f, 0))
        if g.hegemon is not None and leader == g.hegemon:
            return False, "맹주가 패권 세력입니다."
        return True, "조건 충족"
    return False, "알 수 없는 제안"


def sign_treaty(g, a, b, kind):
    p = pair(a, b)
    if kind == "peace":
        make_peace(g, a, b)
        return
    if kind == "nonaggr":
        g.dip.nonaggr[p] = g.turn + C.TREATY_TURNS
    elif kind == "passage":
        g.dip.passage[p] = g.turn + C.TREATY_TURNS
    elif kind == "alliance":
        g.dip.alliance[p] = g.turn
    elif kind == "coalition":
        ca, cb = coalition_of(g, a), coalition_of(g, b)
        if ca is None and cb is None:
            cid = g.dip.next_cid
            g.dip.next_cid += 1
            g.dip.coalitions[cid] = {"members": {a, b}, "since": g.turn}
        elif ca is not None and cb is None:
            g.dip.coalitions[ca]["members"].add(b)
        elif cb is not None and ca is None:
            g.dip.coalitions[cb]["members"].add(a)
        elif ca != cb:
            g.dip.coalitions[ca]["members"] |= g.dip.coalitions[cb]["members"]
            del g.dip.coalitions[cb]
        # 연합 가입 시점 기준으로 평화승리 카운트가 다시 시작된다
        cid = coalition_of(g, a)
        g.dip.coalitions[cid]["since"] = g.turn
    g.event("diplo", f"{g.fname(a)}와(과) {g.fname(b)}이(가) {TREATY_NAMES[kind]}을(를) 맺었습니다.", fids=(a, b))


def propose_treaty(g, proposer, target, kind):
    """proposer 가 target(AI) 에게 조약 제안. (성사 여부, 메시지)"""
    ok, why = treaty_check(g, target, proposer, kind)
    if ok:
        sign_treaty(g, proposer, target, kind)
        return True, f"{TREATY_NAMES[kind]} 체결: {why}"
    g.dip.rejected.add((proposer, target))
    return False, f"거절: {why}"


# ------------------------------------------------------------------ 거래
TRADE_KEYS = ("money", "food", "oil", "coal", "elec", "specialty")


def empty_offer():
    return {"give": {k: 0 for k in TRADE_KEYS} | {"passage": False, "regions": []},
            "take": {k: 0 for k in TRADE_KEYS} | {"passage": False, "regions": []}}


def items_value(g, side: dict, giver_is_ai: bool, ai, proposer) -> float:
    v = side.get("money", 0)
    for k in ("food", "oil", "coal", "elec"):
        v += C.MARKET_BUY[k] * side.get(k, 0)
    v += C.SPECIALTY_VALUE * side.get("specialty", 0)
    if side.get("passage"):
        if giver_is_ai:
            v += 0 if opinion(g, ai, proposer) >= C.PASSAGE_FREE_OPINION else C.PASSAGE_VALUE
        else:
            v += 100
    for rid in side.get("regions", []):
        y = g.region_output_estimate(rid)
        v += y * C.TERRITORY_TURNS * (C.TERRITORY_WEIGHT if giver_is_ai else 1)
    return v


def is_empty(side) -> bool:
    return (not any(side.get(k, 0) for k in TRADE_KEYS) and not side.get("passage")
            and not side.get("regions"))


def evaluate_offer(g, ai, proposer, offer):
    """offer: proposer 기준 give(내가 줌)/take(내가 받음).
    반환: (결과 "accept"/"counter"/"reject", 수정안 또는 None, 설명)"""
    if (proposer, ai) in g.dip.rejected:
        return "reject", None, "이번 턴에는 다시 제안할 수 없습니다."
    give, take = offer["give"], offer["take"]
    recv = items_value(g, give, False, ai, proposer)     # AI 가 받는 가치
    cost = items_value(g, take, True, ai, proposer)      # AI 가 주는 가치
    if is_empty(take) and is_empty(give):
        return "reject", None, "빈 제안입니다."
    if is_empty(take):
        return "accept", None, f"선물 (가치 {recv:,.0f})"
    if is_empty(give):
        only_passage = take.get("passage") and not take.get("regions") and not any(
            take.get(k, 0) for k in TRADE_KEYS)
        if only_passage and opinion(g, ai, proposer) >= C.PASSAGE_FREE_OPINION:
            return "accept", None, "우호국의 통행권 요구"
        if g.power.get(proposer, 0) >= 2 * g.power.get(ai, 0.01):
            return "accept", None, "국력 차이 때문에 요구를 수락"
        return "reject", None, "요구 거절 (국력 2배 미만)"
    m = trade_m(g, ai, proposer)
    info = f"받는 가치 {recv:,.0f} / 주는 가치 {cost:,.0f} × m {m:.2f}"
    if recv >= cost * m:
        return "accept", None, info
    if recv >= cost * m * C.COUNTER_RATIO:
        need = math.ceil(cost * m - recv)
        counter = {"give": dict(give), "take": dict(take)}
        counter["give"]["money"] = give.get("money", 0) + need
        if counter["give"]["money"] <= g.factions[proposer].money:
            return "counter", counter, info + f" → 돈 {need:,}을 더 요구"
    return "reject", None, info


def execute_offer(g, proposer, ai, offer):
    """거래 실행. 수량이 모자라면 가능한 만큼만."""
    fp, fa = g.factions[proposer], g.factions[ai]
    for src, dst, side in ((fp, fa, offer["give"]), (fa, fp, offer["take"])):
        amt = min(side.get("money", 0), max(0, src.money))
        src.money -= amt
        dst.money += amt
        for k in ("food", "oil", "coal", "elec"):
            q = min(side.get(k, 0), src.res.get(k, 0))
            src.res[k] -= q
            dst.res[k] = dst.res.get(k, 0) + q
        n = side.get("specialty", 0)
        while n > 0 and any(v > 0 for v in src.specialty.values()):
            kind = max(src.specialty, key=lambda s: src.specialty[s])
            src.specialty[kind] -= 1
            dst.specialty[kind] = dst.specialty.get(kind, 0) + 1
            n -= 1
        if side.get("passage"):
            g.dip.passage[pair(proposer, ai)] = g.turn + C.TREATY_TURNS
        for rid in side.get("regions", []):
            if g.regions[rid].owner == src.id:
                g.transfer_region(rid, dst.id, reason="거래")


def respond_offer(g, ai, proposer, offer, execute=True):
    """AI 판정 후 수락이면 실행. (결과, 수정안, 설명)"""
    res, counter, info = evaluate_offer(g, ai, proposer, offer)
    give, take = offer["give"], offer["take"]
    if res == "accept" and execute:
        value = items_value(g, give, False, ai, proposer)
        if is_empty(take):
            net = max(1.0, g.factions[ai].last.get("net", 100))
            add_opinion(g, ai, proposer, min(C.OP_GIFT_MAX, 10 * value / (net * 2)))
        elif is_empty(give):
            only_passage = take.get("passage") and not take.get("regions") and not any(
                take.get(k, 0) for k in TRADE_KEYS)
            if not (only_passage and opinion(g, ai, proposer) >= C.PASSAGE_FREE_OPINION):
                add_opinion(g, ai, proposer, C.OP_DEMAND_ACCEPT)
        else:
            add_opinion(g, ai, proposer, C.OP_TRADE_DONE)
        execute_offer(g, proposer, ai, offer)
        g.event("diplo", f"{g.fname(proposer)} ↔ {g.fname(ai)} 거래 성사", fids=(proposer, ai))
    elif res == "reject" and execute:
        if is_empty(give) and not is_empty(take):
            add_opinion(g, ai, proposer, C.OP_DEMAND_REJECT)
        g.dip.rejected.add((proposer, ai))
    return res, counter, info


# ------------------------------------------------------------------ 턴 갱신
def update_turn(g):
    """우호도 증감·감쇠, 우호관계 자동 체결·해지, 조약 만료."""
    alive = g.alive_ids()
    d = g.dip
    border_power = g.border_power_matrix()
    for a in alive:
        fa = g.factions[a]
        my_enemies = set(enemies(g, a))
        my_friends = {x for x in alive if x != a and is_friend(g, a, x)}
        for b in alive:
            if a == b:
                continue
            delta = 0.0
            b_enemies = set(enemies(g, b))
            b_friends = {x for x in alive if x != b and is_friend(g, b, x)}
            if my_enemies & b_enemies:
                delta += C.OP_SAME_ENEMY
            if (my_friends & b_friends) - {a, b}:
                delta += C.OP_SAME_FRIEND
            neutral_dip = g.mods(a).value("neutral_diplomacy")
            if not neutral_dip:
                if b_enemies & my_friends:
                    delta += C.OP_WAR_WITH_FRIEND
                if b_friends & my_enemies:
                    delta += C.OP_FRIEND_OF_ENEMY
            # 국경 긴장: 우리보다 많은 병력을 국경에 모아 두면 서서히 악화
            bp = border_power.get((b, a), 0.0)
            if bp > 0 and not at_war(g, a, b):
                ratio = bp / (border_power.get((a, b), 0.0) + 20)
                pen = min(C.OP_BORDER_MAX, C.OP_BORDER_K * max(0.0, ratio - C.OP_BORDER_FREE))
                if pair(a, b) in d.friends:
                    pen *= 0.5
                delta -= pen
            if pair(a, b) in d.nonaggr or pair(a, b) in d.passage:
                delta += C.OP_TREATY_TURN
            if fa.is_ai:
                if g.hegemon == b and g.hegemon_share > 0:
                    s = g.hegemon_share
                    delta -= min(C.HEGEMON_OP_MAX, C.HEGEMON_OP_BASE + C.HEGEMON_OP_K * (s - C.HEGEMON_SHARE))
                if g.hegemon is not None and g.hegemon not in (a, b):
                    if at_war(g, b, g.hegemon):
                        delta += C.OP_HEGEMON_FIGHTER
                    # 나머지 세력끼리는 가까워진다
                    s = g.hegemon_share
                    delta += C.HEGEMON_BALANCE_K * min(
                        C.HEGEMON_OP_MAX, C.HEGEMON_OP_BASE + C.HEGEMON_OP_K * (s - C.HEGEMON_SHARE))
                delta += g.mods(b).add("ai_opinion_turn")
            base = op_baseline(g, a, b)
            v = base + (d.op.get((a, b), base) + delta - base) * C.OPINION_DECAY
            d.op[(a, b)] = max(-100.0, min(100.0, v))
    # 우호관계 자동
    for i, a in enumerate(alive):
        for b in alive[i + 1:]:
            p = pair(a, b)
            m = mutual(g, a, b)
            if at_war(g, a, b):
                d.friends.discard(p)
            elif p in d.friends:
                if m < C.FRIEND_OFF:
                    d.friends.discard(p)
            elif m >= C.FRIEND_ON:
                d.friends.add(p)
    # 조약 만료: AI 는 우호도 35 미만이면 갱신 거부
    for store in (d.nonaggr, d.passage):
        for p, exp in list(store.items()):
            if g.turn >= exp:
                a, b = p
                if mutual(g, a, b) >= C.TREATY_RENEW_MIN:
                    store[p] = g.turn + C.TREATY_TURNS
                else:
                    del store[p]
                    g.event("diplo", f"{g.fname(a)}–{g.fname(b)} 조약이 만료되었습니다.", fids=p)
    # AI 동맹 탈퇴
    for p in list(d.alliance):
        a, b = p
        for x, y in ((a, b), (b, a)):
            if g.factions[x].is_ai and opinion(g, x, y) < C.ALLIANCE_LEAVE and p in d.alliance:
                leave_alliance(g, x, y)
    d.rejected.clear()
