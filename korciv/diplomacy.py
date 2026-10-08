"""외교 (기획서 7절): 우호도, 4단계 관계, 거래 판정, 선전포고·강화."""
from __future__ import annotations

import math

from . import config as C
from .leaders import gov_opinion_bias
from .state import NEUTRAL

STAGE_NAMES = {-1: "전쟁", 0: "관계 없음", 1: "우호관계", 2: "통행권·불가침", 3: "동맹", 4: "연합"}
TREATY_NAMES = {"nonaggr": "불가침조약", "passage": "군사통행권", "alliance": "동맹",
                "coalition": "연합", "peace": "강화", "friendship": "우호 선언"}


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
        self.op_temp: dict = {}        # (a, b) -> [[값, 만료 턴], ...] 기한부 우호도(우호 선언)
        self.decl_cd: dict = {}        # (종류, 사용국, 상대) -> 마지막 사용 턴
        self.denounce_log: dict = {}   # 사용국 -> [비난한 턴, ...]
        self.declared: dict = {}       # pair -> 우호 선언이 성립한 턴. 전쟁·비난·우호도 붕괴 전까지 유지


# ------------------------------------------------------------------ 조회
def _dip_attr(g, name):
    """예전 세이브 호환: 나중에 추가된 외교 상태."""
    d = g.dip.__dict__
    if name not in d:
        d[name] = {}
    return d[name]


def opinion(g, a, b) -> float:
    v = g.dip.op.get((a, b), 0.0)
    temps = g.dip.__dict__.get("op_temp")
    if temps:
        for val, until in temps.get((a, b), ()):
            if until > g.turn:
                v += val
    return max(-100.0, min(100.0, v))


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
def coalition_consent(g, a, b, agreed=()):
    """연합 회원 a 가 b 에게 선전포고하려면 연합 전원이 동의해야 한다. (모두 동의?, 동의하지 않은 회원, 답을 기다리는 플레이어).
    이미 b 와 전쟁 중인 회원은 동의로 본다. AI 회원은 ai.coalition_war_consent 로 판단하고,
    플레이어 회원은 agreed 에 없으면 '답을 기다림'."""
    cid = coalition_of(g, a)
    if cid is None:
        return True, [], []
    from . import ai as AI
    refuse, wait = [], []
    for c in sorted(g.dip.coalitions[cid]["members"]):
        if c in (a, b) or c in agreed or not g.factions[c].alive or at_war(g, c, b):
            continue
        if not g.factions[c].is_ai:
            wait.append(c)
        elif not AI.coalition_war_consent(g, c, a, b):
            refuse.append(c)
    return not refuse and not wait, refuse, wait


def declare_war(g, a, b, reason="선전포고", _joined=None, _role="declare", _agreed=()):
    """a 가 b 에게 선전포고. 동맹(연합 포함)은 당한 쪽을 자동으로 돕고, 연합 회원의 선포는 전원 동의해야 하며
    동의하면 연합 전원이 함께 선포한다.
    _role: declare(직접 선포) / coalition(연합 공동 선포) / ally(방어 동맹 참전: 전쟁 피로는 당한 쪽 기준).
    _agreed: 이미 동의한 연합 회원(플레이어가 제안을 수락한 경우)."""
    if a == b or at_war(g, a, b) or not g.factions[a].alive or not g.factions[b].alive:
        return False, "이미 전쟁 중이거나 대상이 없습니다."
    if has_nonaggr(g, a, b):
        return False, "불가침조약·동맹 중에는 먼저 조약을 파기해야 합니다."
    if _role == "declare":
        ok, refuse, wait = coalition_consent(g, a, b, _agreed)
        if not ok:
            who = ", ".join(g.factions[c].name for c in refuse + wait)
            return False, f"연합 회원 전원이 동의해야 합니다({who}{' 거절' if refuse else ' 답 필요'})."
    joined = _joined if _joined is not None else set()
    pen = warmonger_penalty(g, a) if _role == "declare" else 0.0
    _start_war(g, a, b, aggressor=b if _role == "ally" else a)
    add_opinion(g, b, a, C.OP_WAR_DECLARED)
    for c in g.alive_ids():
        if c not in (a, b) and is_friend(g, c, b):
            if not g.mods(c).value("neutral_diplomacy"):
                add_opinion(g, c, a, C.OP_FRIEND_ATTACKED)
    note = ""
    if _role == "declare":
        # 전쟁광 평판: 대상 외 모든 세력이 선포국을 꺼린다(1년 안에 잇따라 선포하면 더 크게)
        fa = g.factions[a]
        fa.warmonger = fa.warmonger + 1 if pen < C.OP_WARMONGER else 0
        fa.last_declare = g.turn
        for c in g.alive_ids():
            if c not in (a, b):
                add_opinion(g, c, a, pen)
        note = f" (전쟁광 평판: 다른 세력 우호도 {pen:+.0f})"
    g.event("war", f"{g.fname(a)}이(가) {g.fname(b)}에 {reason}했습니다.{note}", fids=(a, b))
    joined.add((a, b))
    # 수비측 동맹·연합 자동 참전
    for c in list(g.alive_ids()):
        if c in (a, b):
            continue
        if allied(g, c, b) and not at_war(g, c, a) and (c, a) not in joined:
            _clear_treaties(g, c, a)
            declare_war(g, c, a, reason="동맹 참전으로 선전포고", _joined=joined, _role="ally")
    # 공격측 연합 회원 공동 참전(직접 선포일 때만: 전원 동의를 받았다)
    cid = coalition_of(g, a) if _role == "declare" else None
    if cid is not None:
        for c in list(g.dip.coalitions[cid]["members"]):
            if c not in (a, b) and not at_war(g, c, b) and (c, b) not in joined and g.factions[c].alive:
                _clear_treaties(g, c, b)
                declare_war(g, c, b, reason="연합 공동 선전포고", _joined=joined, _role="coalition")
    return True, ""


def warmonger_penalty(g, a) -> float:
    """a 가 지금 선전포고하면 다른 세력들이 깎는 우호도: −10, 직전 전쟁 1년 안이면 5씩 더."""
    fa = g.factions[a]
    recent = (g.turn - fa.last_declare <= C.WARMONGER_WINDOW
              or g.turn - fa.last_aggr_end <= C.WARMONGER_WINDOW
              or any(w.get("aggressor") == a for p, w in g.dip.wars.items() if a in p))
    streak = fa.warmonger + 1 if recent else 0
    return C.OP_WARMONGER + C.OP_WARMONGER_STEP * streak


def _clear_treaties(g, a, b):
    p = pair(a, b)
    g.dip.nonaggr.pop(p, None)
    g.dip.passage.pop(p, None)
    g.dip.alliance.pop(p, None)
    g.dip.friends.discard(p)


def _start_war(g, a, b, happiness=True, aggressor=None):
    """전쟁 시작. aggressor(선포한 쪽)는 전쟁 피로 +20·턴당 +1, 상대는 +10·턴당 +0.5. 독립 전쟁은 피로 증가 없음."""
    p = pair(a, b)
    _clear_treaties(g, a, b)
    _dip_attr(g, "declared").pop(p, None)          # 전쟁하면 우호 선언 관계도 끝난다
    _player_dialogue(g, "war", a, b)
    g.dip.wars[p] = {"start": g.turn, "declarer": a, "aggressor": aggressor if happiness else None,
                     "score": {a: 0.0, b: 0.0},
                     "regs0": {a: g.region_count(a), b: g.region_count(b)}, "taken": {a: 0, b: 0}}
    delay = g.mods(a).value("parliament_delay", 0)
    if delay:
        g.dip.no_attack_until[(a, b)] = g.turn + delay
    for f in (a, b) if happiness else ():
        # 직접 선포한 쪽만 +15. 방어 동맹 참전(aggressor = 상대)은 양쪽 모두 +10
        role = "aggressor" if f == a and aggressor in (None, a) else "defender"
        add_war_weary(g, f, C.WAR_WEARY_START[role] * g.mods(f).mult("war_start_weary"),
                      defensive=role == "defender")
    # 통행권으로 상대 영토에 있던 병력은 가장 가까운 자국 영토로
    for army in list(g.armies.values()):
        if army.owner in (a, b) and not g.world.is_sea(army.loc):
            owner = g.regions[army.loc].owner
            other = b if army.owner == a else a
            if owner == other:
                g.teleport_home(army)


def add_war_weary(g, fid, v, defensive=False):
    """전쟁 피로 증감. defensive: 선포당한 전쟁에서 쌓인 피로(war_weary_def 에도 더한다).
    회복(음수)은 두 몫을 같은 비율로 줄인다."""
    f = g.factions[fid]
    old = f.war_weary
    f.war_weary = max(0.0, min(C.WAR_WEARY_MAX, old + v))
    d = getattr(f, "war_weary_def", 0.0)
    if v >= 0:
        if defensive:
            d += f.war_weary - old
    elif old > 0:
        d *= f.war_weary / old
    f.war_weary_def = max(0.0, min(f.war_weary, d))


def war_weary_defensive(g, fid) -> bool:
    """이번 턴 쌓이는 전쟁 피로가 '당한 쪽' 몫인가: 스스로 선포한 전쟁이 하나도 없으면 True(독립 전쟁 포함)."""
    for p, w in g.dip.wars.items():
        if fid in p and w.get("aggressor", w.get("declarer")) == fid:
            return False
    return True


def war_weary_rate(g, fid) -> float:
    """이번 턴 전쟁 피로 증가량: 전쟁 중이면 턴당 0.5(선포·피선포 공통, WAR_WEARY_TURN), 평시 0."""
    rate = 0.0
    for p, w in g.dip.wars.items():
        if fid not in p:
            continue
        aggr = w.get("aggressor", w.get("declarer"))
        if aggr is None:                     # 독립 전쟁: 양쪽 모두 당한 쪽 기준
            rate = max(rate, C.WAR_WEARY_TURN["defender"])
        else:
            rate = max(rate, C.WAR_WEARY_TURN["aggressor" if aggr == fid else "defender"])
    return rate * g.mods(fid).mult("war_weary_rate") if rate else 0.0


def _peace_cede(g, side, other):
    """야율융서 '강동 6주': 강화하면 상대와 맞닿은 내 지역 1곳(수도 제외)을 상대에게 넘긴다."""
    if not g.mods(side).value("peace_cede") or not (g.factions[side].alive and g.factions[other].alive):
        return
    cap = g.factions[side].capital
    cands = sorted(r.id for r in g.regions_of(side)
                   if r.id != cap and any(g.regions[n].owner == other for n in g.world.land_adj[r.id]))
    if not cands:
        return
    rid = g.rng.choice(cands)
    g.transfer_region(rid, other, reason="강화 할양")
    g.event("captured", f"강동 6주: {g.fname(side)}이(가) 강화 조건으로 {g.info(rid).name}을(를) "
                        f"{g.fname(other)}에 넘겼습니다.", region=rid, fids=(side, other))


def peace_relief(w, side, other) -> float:
    """강화 성과로 줄어드는 전쟁 피로: 얻은 지역 > 잃은 지역이면 10, 처치한 유닛 > 처치당한 유닛이면 10."""
    taken, kills = w.get("taken", {}), w.get("kills", {})
    v = 0.0
    if taken.get(side, 0) > taken.get(other, 0):
        v += C.PEACE_WEARY_TERRITORY
    if kills.get(side, 0) > kills.get(other, 0):
        v += C.PEACE_WEARY_KILLS
    return v


def _peace_weary_relief(g, w, a, b):
    for side, other in ((a, b), (b, a)):
        v = peace_relief(w, side, other)
        f = g.factions[side]
        if v <= 0 or not f.alive or f.war_weary <= 0:
            continue
        before = f.war_weary
        add_war_weary(g, side, -v)
        if not f.is_ai:
            g.event("info", f"{g.fname(other)}와(과)의 전쟁 성과로 전쟁 피로가 {before - f.war_weary:.0f} 줄었습니다.",
                    fids=(side,))


def make_peace(g, a, b, _done=None):
    done = _done if _done is not None else set()
    p = pair(a, b)
    if p not in g.dip.wars or p in done:
        return
    done.add(p)
    w = g.dip.wars[p]
    aggr = w.get("aggressor")
    if aggr in (a, b):
        g.factions[aggr].last_aggr_end = g.turn
    _peace_weary_relief(g, w, a, b)
    del g.dip.wars[p]
    g.dip.nonaggr[p] = max(g.dip.nonaggr.get(p, 0), g.turn + C.PEACE_TREATY_TURNS)
    if not hasattr(g.dip, "peace_until"):
        g.dip.peace_until = {}
    g.dip.peace_until[p] = g.turn + C.PEACE_TREATY_TURNS   # 강화 불가침: 이 기간에는 파기 불가
    g.dip.no_attack_until.pop((a, b), None)
    g.dip.no_attack_until.pop((b, a), None)
    for r in g.regions.values():
        if r.owner == b:
            r.occs.pop(a, None)
        elif r.owner == a:
            r.occs.pop(b, None)
    for army in list(g.armies.values()):
        if army.owner in (a, b) and not g.world.is_sea(army.loc):
            other = b if army.owner == a else a
            if g.regions[army.loc].owner == other:
                g.teleport_home(army)
    g.event("peace", f"{g.fname(a)}와(과) {g.fname(b)}이(가) 강화했습니다. (불가침 {C.PEACE_TREATY_TURNS}턴)", fids=(a, b))
    _player_dialogue(g, "peace", a, b)
    for side, other in ((a, b), (b, a)):
        _peace_cede(g, side, other)
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


# ------------------------------------------------------------------ 우호 선언·비난
def hostile_to(g, x, t) -> bool:
    """x 가 t 와 적대 중인가: 전쟁 중이거나 (AI 라면) 우호도 −30 이하."""
    if at_war(g, x, t):
        return True
    return g.factions[x].is_ai and opinion(g, x, t) <= C.HOSTILE_OP


def decl_cooldown(g, kind, a, b) -> int:
    last = _dip_attr(g, "decl_cd").get((kind, a, b))
    return 0 if last is None else max(0, C.DECL_COOLDOWN - (g.turn - last))


def recent_denounces(g, a) -> int:
    log = _dip_attr(g, "denounce_log").get(a, [])
    return sum(1 for t in log if g.turn - t < C.DENOUNCE_WINDOW)


def friendship_check(g, a, b):
    """a 가 b 에게 우호 선언. (가능 여부, 이유). b 가 AI 면 수락 여부까지 판정한다."""
    if a == b or not g.factions[b].alive:
        return False, "대상이 없습니다."
    cd = decl_cooldown(g, "friend", a, b)
    if cd:
        return False, f"쿨타임 {cd}턴"
    if (a, b) in g.dip.rejected:
        return False, "이번 턴에는 다시 제안할 수 없습니다."
    if at_war(g, a, b):
        return False, "전쟁 중입니다."
    if peace_left(g, a, b):
        return False, f"휴전 불가침 중({peace_left(g, a, b)}턴)"
    if g.factions[b].is_ai:
        op = opinion(g, b, a)
        if op < C.DECL_FRIEND_MIN:
            return False, f"상대 우호도 {op:.0f} / 필요 {C.DECL_FRIEND_MIN}"
        return True, f"상대 우호도 {op:.0f} ≥ {C.DECL_FRIEND_MIN}"
    return True, "상대가 결정"


def friendship_effects(g, a, b) -> list:
    """우호 선언이 받아들여지면 생기는 우호도 변화 [(보는 세력, 대상, 변화, 기한부 여부)]."""
    out = []
    for x, y in ((b, a), (a, b)):
        if g.factions[x].is_ai:
            out.append((x, y, C.DECL_FRIEND_BONUS, True))
    for x in g.alive_ids():
        if x not in (a, b) and g.factions[x].is_ai and hostile_to(g, x, b):
            out.append((x, a, C.DECL_FRIEND_ENEMY, False))
    return out


def declare_friendship(g, a, b, force=False):
    """a 의 우호 선언. 상대가 AI 면 수락 조건을 보고, force 면(플레이어가 AI 제안을 수락) 바로 성립."""
    ok, why = friendship_check(g, a, b)
    if not ok and not force:
        g.dip.rejected.add((a, b))
        return False, f"거절: {why}"
    temps = _dip_attr(g, "op_temp")
    for x, y, v, temp in friendship_effects(g, a, b):
        if temp:
            temps.setdefault((x, y), []).append([v, g.turn + C.DECL_FRIEND_TURNS])
        else:
            add_opinion(g, x, y, v)
    _dip_attr(g, "decl_cd")[("friend", a, b)] = g.turn
    _dip_attr(g, "declared")[pair(a, b)] = g.turn
    g.event("diplo", f"{g.fname(a)}이(가) {g.fname(b)}에 우호를 선언했습니다.", fids=(a, b))
    _player_dialogue(g, "friend", a, b)
    return True, f"우호 선언 성립: {C.DECL_FRIEND_TURNS}턴 동안 우호도 +{C.DECL_FRIEND_BONUS}"


def _player_dialogue(g, kind, a, b):
    """플레이어와 AI 사이의 일이면 AI 지도자의 대사 팝업을 쌓는다."""
    if g.player_id in (a, b):
        g.queue_dialogue(kind, b if a == g.player_id else a)


def declared_friends(g, a, b) -> bool:
    """우호 선언이 성립해(어느 쪽이 선언했든) 아직 유지되는 관계인가."""
    return pair(a, b) in _dip_attr(g, "declared")


def econ_partners(g, fid) -> tuple:
    """경제승리 조건용 관계 수: (우호 선언 이상 관계 국가 수, 동맹 이상 국가 수).
    '우호 선언 이상' = 우호 선언 관계, 또는 통행권·불가침·동맹·연합. 우호도가 높아 저절로 생긴 우호관계는 세지 않는다."""
    n = allies = 0
    for x in g.alive_ids():
        if x == fid:
            continue
        st = stage(g, fid, x)
        if st >= 3:
            allies += 1
        if st >= 2 or declared_friends(g, fid, x):
            n += 1
    return n, allies


def denounce_check(g, a, b):
    if a == b or not g.factions[b].alive:
        return False, "대상이 없습니다."
    cd = decl_cooldown(g, "denounce", a, b)
    if cd:
        return False, f"쿨타임 {cd}턴"
    return True, ""


def denounce_effects(g, a, b) -> list:
    """a 가 b 를 비난할 때의 우호도 변화 [(보는 세력, 대상, 변화, False)]."""
    out = []
    if g.factions[b].is_ai:
        out.append((b, a, C.DENOUNCE_TARGET, False))
    ais = [x for x in g.alive_ids() if g.factions[x].is_ai]
    for x in ais:
        if x not in (a, b):
            out.append((x, b, C.DENOUNCE_OTHERS, False))
    n = recent_denounces(g, a) + 1            # 이번 비난이 최근 24턴 안의 몇 번째인가
    if n >= C.DENOUNCE_SPAM_N:
        for x in ais:
            if x != a:
                out.append((x, a, C.DENOUNCE_SPAM, False))
    else:
        for x in ais:
            if x not in (a, b) and hostile_to(g, x, b):
                out.append((x, a, C.DENOUNCE_ALLY_BONUS, False))
    return out


def denounce(g, a, b):
    ok, why = denounce_check(g, a, b)
    if not ok:
        return False, why
    for x, y, v, _ in denounce_effects(g, a, b):
        add_opinion(g, x, y, v)
    _dip_attr(g, "decl_cd")[("denounce", a, b)] = g.turn
    _dip_attr(g, "declared").pop(pair(a, b), None)   # 비난하면 우호 선언 관계도 끝난다
    if b == g.player_id:
        g.queue_dialogue("denounce", a)                 # AI가 플레이어를 비난
    log = _dip_attr(g, "denounce_log").setdefault(a, [])
    log.append(g.turn)
    del log[:-8]
    g.event("diplo", f"{g.fname(a)}이(가) {g.fname(b)}을(를) 공개적으로 비난했습니다.", fids=(a, b))
    return True, "비난했습니다."


def effects_text(g, effects, viewer=None) -> str:
    """미리보기용: 세력별 우호도 변화 요약(한 줄에 한 세력)."""
    rows = {}
    for x, y, v, temp in effects:
        rows.setdefault(x, []).append(f"{g.fname(y)}에 {v:+g}" + (f"({C.DECL_FRIEND_TURNS}턴)" if temp else ""))
    if not rows:
        return "우호도 변화 없음"
    return "\n".join(f"{g.fname(x)}: " + ", ".join(v) for x, v in rows.items())


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
    if kind in ("alliance", "coalition"):
        for x in (ai, proposer):
            if g.mods(x).value("no_alliance"):          # 장보고 '골품의 벽'
                return False, f"{g.fx_source(x, 'no_alliance')}: 동맹·연합을 맺을 수 없습니다."
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
        if not declared_friends(g, ai, proposer):
            return False, "한 단계를 건너뛴 제안입니다(먼저 우호 선언)."
        return (op >= need, f"우호도 {op:.0f} / 필요 {need:.0f}")
    if kind == "alliance":
        if p in g.dip.alliance:
            return False, "이미 동맹입니다."
        if not declared_friends(g, ai, proposer):
            return False, "한 단계를 건너뛴 제안입니다(먼저 우호 선언)."
        if p not in g.dip.nonaggr and p not in g.dip.passage:
            return False, "한 단계를 건너뛴 제안입니다(먼저 조약)."
        need = threshold(g, ai, proposer, C.ALLIANCE_MIN)
        if op < need:
            return False, f"우호도 {op:.0f} / 필요 {need:.0f}"
        return True, f"우호도 {op:.0f} / 필요 {need:.0f}"
    if kind == "coalition":
        if same_coalition(g, ai, proposer):
            return False, "이미 같은 연합입니다."
        if p not in g.dip.alliance:
            return False, "한 단계를 건너뛴 제안입니다(먼저 동맹)."
        if g.turn - g.dip.alliance[p] < C.COALITION_ALLIANCE_TURNS:
            return False, f"동맹 {C.COALITION_ALLIANCE_TURNS}턴 이상이 필요합니다."
        need = threshold(g, ai, proposer, C.COALITION_MIN)
        if op < need:
            return False, f"우호도 {op:.0f} / 필요 {need:.0f}"
        return True, "조건 충족"
    return False, "알 수 없는 제안"


def sign_treaty(g, a, b, kind):
    p = pair(a, b)
    if kind == "friendship":
        declare_friendship(g, a, b, force=True)
        return
    if kind == "peace":
        make_peace(g, a, b)
        return
    if kind == "nonaggr":
        g.dip.nonaggr[p] = g.turn + C.TREATY_TURNS
    elif kind == "passage":
        g.dip.passage[p] = g.turn + C.TREATY_TURNS
    elif kind == "alliance":
        g.dip.alliance[p] = g.turn
        _player_dialogue(g, "alliance", a, b)
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
        gv = gift_value(g, give, proposer)
        return "accept", None, (f"선물 (가치 {gv:,.0f}) → 우호도 +{gift_opinion(g, ai, gv, proposer):.2f}"
                                f" (상대 턴당 세수 {gift_income(g, ai):,.0f}마다 +{gift_rate(g, ai):.2f}, 최대 +{C.OP_GIFT_MAX})")
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


def gift_income(g, fid) -> float:
    """선물 환산 기준 세수: 지난 턴 실제 세수와 GDP × 기준 세율 중 큰 값(지출은 따지지 않는다)."""
    f = g.factions[fid]
    return max(1.0, f.last.get("tax", 0.0), g.gdp(fid) * C.TAX_DEFAULT * f.income_mult)


def gift_aggression(g, fid) -> float:
    """선물 판정용 호전성 = 지도자 호전성 + 정치체제 호전성(AI 목표 호전성, 철인통치·미정 5). 최대 20."""
    from .leaders import GOV_BY_KEY
    f = g.factions[fid]
    gdef = GOV_BY_KEY.get(f.gov) if f.gov else None
    gov = gdef["target"] if gdef and gdef["target"] is not None else C.GIFT_GOV_AGGR_DEFAULT
    return f.aggression + gov


def gift_rate(g, fid) -> float:
    """세수 1턴분 선물당 우호도: 3 − 0.05 × (호전성 − 10). 예) 지도자 6 + 체제 7 → 2.85."""
    return C.GIFT_OP_PER_INCOME - C.GIFT_AGGR_STEP * (gift_aggression(g, fid) - C.GIFT_AGGR_BASE)


def gift_value(g, side: dict, giver) -> float:
    """선물의 가치: 돈은 그대로, 자원은 주는 쪽의 시장 판매가(내정 탭), 그 밖(특산물·통행권·지역)은 거래 가치."""
    v = side.get("money", 0)
    for k in ("food", "oil", "coal", "elec"):
        v += g.sell_price(giver, k) * side.get(k, 0)
    rest = {"specialty": side.get("specialty", 0), "passage": side.get("passage", False),
            "regions": side.get("regions", [])}
    return v + items_value(g, rest, False, None, giver)


def gift_opinion(g, ai, value, giver=None) -> float:
    """선물 가치 → 받는 쪽 우호도 상승: 세수 1턴분마다 gift_rate, 소수 둘째 자리 아래 절사, 1회 최대 +25.
    주는 쪽이 국제금융센터를 가졌으면 +10%."""
    raw = gift_rate(g, ai) * value / gift_income(g, ai)
    if giver is not None and g.econ_buildings(giver, "ifc"):
        raw *= 1 + C.IFC_GIFT_BONUS
    return min(C.OP_GIFT_MAX, math.floor(raw * 100 + 1e-6) / 100)


def ai_gift(g, giver, receiver, amount) -> float:
    """AI 끼리 돈 선물: 보내고, 받는 쪽 우호도를 선물 공식대로 올린다. 오른 우호도를 돌려준다."""
    amount = max(0.0, min(amount, g.factions[giver].money))
    if amount <= 0:
        return 0.0
    g.factions[giver].money -= amount
    g.factions[receiver].money += amount
    v = gift_opinion(g, receiver, amount, giver)
    add_opinion(g, receiver, giver, v)
    return v


def gift_needed(g, receiver, delta, giver=None) -> float:
    """받는 쪽 우호도를 delta 만큼 올리는 데 드는 돈(1회 최대 OP_GIFT_MAX 기준)."""
    delta = min(delta, C.OP_GIFT_MAX)
    rate = gift_rate(g, receiver)
    if giver is not None and g.econ_buildings(giver, "ifc"):
        rate *= 1 + C.IFC_GIFT_BONUS
    return delta / max(1e-6, rate) * gift_income(g, receiver) + 1.0


def respond_offer(g, ai, proposer, offer, execute=True):
    """AI 판정 후 수락이면 실행. (결과, 수정안, 설명)"""
    res, counter, info = evaluate_offer(g, ai, proposer, offer)
    give, take = offer["give"], offer["take"]
    if res == "accept" and execute:
        if is_empty(take):
            add_opinion(g, ai, proposer, gift_opinion(g, ai, gift_value(g, give, proposer), proposer))
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
                # 승리에 가까워지는 나라 견제(우호 선언·조약 이상 관계가 아니면)
                t = g.victory_threat(b)
                if t > 0 and stage(g, a, b) < 2 and not declared_friends(g, a, b):
                    delta -= C.VICTORY_THREAT_OP * t
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
    # 우호 선언 관계: 한쪽이 사라지거나 우호도가 수락 문턱(−30) 아래로 떨어지면 끝난다
    decl = _dip_attr(g, "declared")
    for p in list(decl):
        a, b = p
        if not (g.factions[a].alive and g.factions[b].alive) or mutual(g, a, b) < C.DECL_FRIEND_MIN:
            del decl[p]
    # AI 동맹 파기(우호도 30 이하)
    from . import ai as AI
    for p in list(d.alliance):
        a, b = p
        for x, y in ((a, b), (b, a)):
            if (g.factions[x].is_ai and opinion(g, x, y) <= C.ALLIANCE_LEAVE and p in d.alliance
                    and not AI.loyal(g, x, y)):       # 강국과 거기 기댄 나라는 서로 등을 돌리지 않는다
                leave_alliance(g, x, y)
    d.rejected.clear()
    temps = d.__dict__.get("op_temp")
    if temps:
        for k in list(temps):
            temps[k] = [x for x in temps[k] if x[1] > g.turn]
            if not temps[k]:
                del temps[k]
