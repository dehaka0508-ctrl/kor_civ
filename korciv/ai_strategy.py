"""AI 2페이즈(경쟁기) 전략: 정세 판단 → 승리 방향·태세·우방.

1페이즈(확장기)가 끝난 나라는 매 턴 국경 정세를 훑고(scan) 태세를 정한다(posture: 위기·경계·평시).
6턴마다(또는 선전포고를 받거나 위기에 빠지면 바로) 나라 사정과 주변 정세를 종합해 승리 방향을 다시 고른다.
고른 방향은 관성이 있어서 새 방향 점수가 지금 방향의 1.25배를 넘어야 바꾼다.
국경을 맞댄 나라가 3곳 이상이거나(2곳 이상인데 위협이 있으면) 한 나라를 '우방'으로 골라
우호 선언·선물로 불가침까지 끌어올려 두 전선에서 싸우지 않게 한다.

ai.py 가 결과(f.ai["p2"])를 읽어 전쟁·강화·건설·외교 판단을 바꾼다. AI 는 플레이어가 볼 수 있는 정보
(시야 안 병력과 기억, 반기 랭킹, 우호도·조약, 관측한 선전포고 이력)만 쓴다.
"""
from __future__ import annotations

import random
from collections import defaultdict

from . import config as C
from . import diplomacy as D
from .state import NEUTRAL

PATHS = ("conquest", "science", "economic", "diplomatic")
PATH_NAMES = {"conquest": "정복", "science": "과학", "economic": "경제", "diplomatic": "외교"}


def _ai():
    from . import ai
    return ai


def state(f) -> dict:
    return f.ai.setdefault("p2", {})


# ------------------------------------------------------------------ 정세 판단
def hostility(g, fid, o) -> float:
    """o 가 나에게 보이는 적대 신호(0~1): 전쟁 1, 나에 대한 우호도가 낮을수록, 최근 선전포고 이력이 있을수록.
    우호 선언·불가침이 있으면 줄고, 동맹이면 0."""
    if D.at_war(g, fid, o):
        return 1.0
    if D.allied(g, fid, o):
        return 0.0
    h = max(0.0, min(0.8, 0.2 - D.opinion(g, o, fid) / 100))
    fo = g.factions[o]
    if g.turn - getattr(fo, "last_declare", -999) <= C.AI_P2_AGGR_MEMORY:
        h += 0.15 + 0.05 * min(3, getattr(fo, "warmonger", 0))
    if D.has_nonaggr(g, fid, o) or D.declared_friends(g, fid, o):
        h *= 0.4
    return min(1.0, h)


def scan(g, f) -> dict:
    """국경을 맞댄 나라마다: 추정 전력 p, 전력비 ratio(나/상대), 적대 host, 내 국경 중 그 나라 몫 share,
    국경 집결 mass(그 나라 국경 병력 / 내 국경 병력), 위협도 T, 지역 수."""
    AI = _ai()
    fid, w = f.id, g.world
    vis = g.visible(fid)
    by_loc = AI._armies_by_loc(g)
    mine = max(10.0, g.mil_power(fid))
    my_side, their_side = defaultdict(set), defaultdict(set)
    for r in g.regions_of(fid):
        for n in w.land_adj[r.id]:
            o = g.regions[n].owner
            if o in (NEUTRAL, fid):
                continue
            my_side[o].add(r.id)
            their_side[o].add(n)
    total = sum(len(v) for v in my_side.values()) or 1
    out = {}
    for o in my_side:
        theirs = sum(g.army_power(a) for n in their_side[o] if n in vis for a in by_loc.get(n, ()) if a.owner == o)
        ours = sum(g.army_power(a) for rid in my_side[o] for a in by_loc.get(rid, ()) if a.owner == fid)
        p = max(10.0, AI.perceived_power(g, fid, o))
        host = hostility(g, fid, o)
        share = len(my_side[o]) / total
        mass = theirs / (ours + 20.0)
        # 위협도: (전력비, 최대 3) × 적대 신호 × (국경 비중 보정) + 국경 집결(내 국경 병력의 1.5배 넘게 모았으면)
        T = min(3.0, p / mine) * host * (0.5 + 0.5 * share) + 0.25 * max(0.0, mass - 1.5) * host
        out[o] = {"p": round(p, 1), "ratio": round(mine / p, 3), "host": round(host, 3), "share": round(share, 3),
                  "mass": round(mass, 3), "T": round(T, 3), "regions": g.region_count(o)}
    return out


def threat_power(g, f, sc) -> float:
    """국경 너머 위협 전력: 적대 신호와 국경 비중을 반영한 이웃 전력의 최댓값."""
    return max((v["p"] * min(1.0, v["host"] + 0.3) * min(1.0, v["share"] + 0.3) for v in sc.values()), default=0.0)


def shrink(g, fid, e) -> float:
    """e 와의 전쟁이 시작된 뒤 실제로 줄어든 영토 비율(되찾은 땅은 빼고)."""
    w = g.dip.wars.get(D.pair(fid, e))
    if not w:
        return 0.0
    n0 = max(1, w.get("regs0", {}).get(fid, g.region_count(fid)))
    return max(0.0, 1 - g.region_count(fid) / n0)


def posture(g, f, sc, threat=None) -> str:
    """위기(crisis): 전쟁이 시작된 뒤 영토가 실제로 20% 이상 줄었거나, 수도 위협·실질 행복 −45 미만·자금 바닥.
    경계(defend): 위협도 1.2 이상인 이웃, 이웃인 패권국(나 아님), 나와 비슷하거나 강한 나라에게 선전포고를 받아 싸우는 중.
    평시(normal): 그 밖."""
    fid = f.id
    enemies = D.enemies(g, fid)
    if enemies:
        lost = max((shrink(g, fid, e) for e in enemies), default=0.0)
        cap = g.regions.get(f.capital)
        cap_threat = bool(cap) and (any(by != fid for by in cap.occs) or (threat or {}).get(f.capital, 0) >= 1.0)
        if (lost >= C.AI_P2_CRISIS_LOST or cap_threat or g.avg_happiness(fid) < C.AI_P2_CRISIS_HAPPY
                or (f.money < 0 and f.last.get("net", 0) < 0)):
            return "crisis"
    attacked = any((g.dip.wars.get(D.pair(fid, e)) or {}).get("declarer") == e
                   and sc.get(e, {}).get("ratio", 0.0) < C.AI_P2_ATTACKED_RATIO for e in enemies)
    maxT = max((v["T"] for v in sc.values()), default=0.0)
    dominant = g.hegemon is not None and g.hegemon != fid and g.hegemon in sc
    if maxT >= C.AI_P2_DEFEND_T or dominant or attacked:
        return "defend"
    return "normal"


# ------------------------------------------------------------------ 승리 방향
def _ranking(g):
    if not getattr(g, "rankings", None):
        return None
    return g.rankings[max(g.rankings)]


def gdp_rank_k(g, fid):
    """반기 랭킹 GDP 순위 계수: 1위 1 → 꼴찌 0(랭킹이 없으면 0.5)."""
    rows = _ranking(g)
    if not rows:
        return 0.5
    order = sorted(rows, key=lambda r: -r["gdp"])
    idx = next((i for i, r in enumerate(order) if r["fid"] == fid), None)
    return 0.5 if idx is None else 1 - idx / max(1, len(order) - 1)


def poverty(g, fid) -> float:
    """GDP 하위 절반일수록 0 → 1(꼴찌)."""
    return max(0.0, 0.5 - gdp_rank_k(g, fid)) * 2


def path_scores(g, f, sc, rng=None) -> dict:
    """방향별 점수 = 성격(Fit) × 조건(Feas) × 진척(Prospect) [× 경쟁 보정]. 이유도 함께 남긴다."""
    AI = _ai()
    fid = f.id
    a = AI.eff_aggression(g, f) / 10
    bias = lambda k: AI.leader_bias(g, fid, k)
    regs = g.regions_of(fid)
    R = max(1, len(regs))
    rows = _ranking(g)
    me_row = next((r for r in rows if r["fid"] == fid), None) if rows else None
    others = [r for r in rows if r["fid"] != fid] if rows else []
    why = {}
    # 정복: 나보다 약한 이웃이 있으면 전력 차이에 비례, 강하고 적대적인 이웃이 있으면 감점
    cands = [v for o, v in sc.items() if not D.allied(g, fid, o)]
    best = max(cands, key=lambda v: v["ratio"], default=None)
    adv = best["ratio"] if best else 0.0
    if adv >= 1.0:
        feas = 0.25 + 0.35 * min(2.0, adv - 1.0) + 0.1 * min(1.5, best["regions"] / R)
    else:
        feas = 0.12
    stronger = any(v["ratio"] < 0.7 and v["host"] >= 0.3 for v in sc.values())
    if stronger:
        feas *= 0.6
    feas *= 1 - min(0.5, f.war_weary / 100)
    if g.avg_happiness(fid) < -10:
        feas *= 0.8
    conquest = (0.3 + 0.9 * a) * bias("war") * feas * (1 + 0.6 * min(1.0, R / 284))
    why["conquest"] = f"최약 이웃 대비 {adv:.1f}배" + (", 강한 적대 이웃" if stronger else "")
    # 과학: 석유·해안·산맥·공장·은행, GDP 순위, 진척. 같은 길에서 크게 앞선 나라가 있으면 감점
    infos = [g.info(r.id) for r in regs]
    has_oil = any(i.is_oil for i in infos)
    has_coast = any(i.coastal for i in infos)
    has_mtn = any(r.id in g.world.mountain_regions for r in regs)
    fac = sum(1 for r in regs if r.b["factory"] >= 4)
    bank_hi = any(r.b["bank"] >= 4 for r in regs)
    if rows and me_row:
        order = sorted(rows, key=lambda r: -r["gdp"])
        rank = next(i for i, r in enumerate(order) if r["fid"] == fid) + 1
        n = len(order)
    else:
        rank, n = None, 0
    rank_k = (1 - (rank - 1) / max(1, n - 1)) if rank else 0.5
    # 해안·산맥은 거의 모든 나라에 있어 가점이 작다. 석유(6곳, 흩어져 있음)는 조금 더. 공장·은행은 4단계 이상부터
    feas = (0.1 + 0.25 * has_oil + C.AI_P2_SCI_GEO * (has_coast + has_mtn) + 0.15 * min(1.0, fac / 2)
            + 0.08 * bank_hi + 0.25 * rank_k)
    k_sci = len(f.science)
    ahead = max((r["science"] for r in others), default=0) - k_sci >= 2
    poor = max(0.0, 0.5 - rank_k) * 2 if rank else 0.0      # GDP 하위권: 과학·경제는 조금 덜, 외교는 조금 더
    science = ((0.3 + 0.9 * (1 - a)) * bias("science") * feas * (1 + 0.8 * k_sci / 7) * (0.75 if ahead else 1.0)
               * (1 - C.AI_P2_POOR_SCI * poor))
    why["science"] = ("석유 " if has_oil else "") + f"GDP {rank or '?'}위" + (", 앞선 나라 있음" if ahead else "")
    # 경제: '돈만 있으면 된다' — 반기 랭킹 GDP 순위(계단 + 연속), 수도 주변 금융 권역 가능성,
    # 수도 2칸 안 은행 4단계(과학보다 큰 가점), 우호 관계, 진척
    inc = 0.35 if rank and rank <= 2 else 0.2 if rank and rank <= max(2, n // 2) else 0.05
    near = sum(1 for rid in g.near_capital(fid, 1) if rid in g.regions and g.regions[rid].owner == fid)
    cluster = 0.25 if near >= C.ECON_CLUSTER else 0.15 if near >= 3 else 0.05
    near2 = g.near_capital(fid, 2)
    bank_cap = any(r.b["bank"] >= 4 for r in regs if r.id in near2)
    partners, _ = D.econ_partners(g, fid)
    stage = g.econ_stage(fid)
    feas = 0.08 + inc + cluster + 0.08 * min(3, partners) + C.AI_P2_ECON_BANK_CAP * bank_cap
    feas *= C.AI_P2_ECON_RANK_BASE + C.AI_P2_ECON_RANK_K * rank_k     # 돈: GDP 1위 ×1.2 → 꼴찌 ×0.4
    ahead = max((r["econ"] for r in others), default=0) - stage >= 2
    economic = ((0.3 + 0.9 * (1 - a)) * bias("bank") * feas * (1 + 0.8 * stage / 5) * (0.75 if ahead else 1.0)
                * (1 - C.AI_P2_POOR_SCI * poor))
    # GDP 1~2위가 다음 단계를 순수입으로 감당할 수 있으면 경제를 확실히 노린다(과학보다 돈은 더 들어도 최소 턴 수가 적다)
    step = C.ECON[C.ECON_STEPS[max(0, min(len(C.ECON_STEPS) - 1, stage - 1))]]
    net = f.last.get("tax", 0) - f.last.get("upkeep", 0)
    rich = bool(rank and rank <= 2 and net >= C.AI_P2_ECON_RICH_NET * step["per_turn"] * C.MONEY_SCALE)
    if rich:
        economic *= C.AI_P2_ECON_RICH
    why["economic"] = (f"GDP {rank or '?'}위" + ("(감당 가능)" if rich else "") + f", 수도 주변 {near}곳, 관계 {partners}"
                       + (", 앞선 나라 있음" if ahead else ""))
    # 외교: 지금 규칙(생존국 전원 한 연합)은 어렵다. 우호적인 나라가 많을 때만
    if g.mods(fid).value("no_alliance"):
        diplomatic = 0.0
    else:
        alive = [x for x in g.alive_ids() if x != fid]
        friendly = sum(1 for x in alive if D.allied(g, fid, x) or D.opinion(g, x, fid) >= 30) / max(1, len(alive))
        diplomatic = (0.2 + 0.6 * (1 - a)) * bias("ally") * 0.4 * friendly ** 2 * (1 + C.AI_P2_POOR_DIP * poor)
    why["diplomatic"] = "우호국 비율"
    scores = {"conquest": conquest, "science": science, "economic": economic, "diplomatic": diplomatic}
    if rng is not None:
        scores = {k: v * (1 + rng.uniform(-C.AI_P2_NOISE, C.AI_P2_NOISE)) for k, v in scores.items()}
    return {"scores": {k: round(v, 4) for k, v in scores.items()}, "why": why}


def choose_path(g, f, sc, reason="정기") -> str:
    s = state(f)
    res = path_scores(g, f, sc, g.rng)
    scores = res["scores"]
    best = max(PATHS, key=lambda k: scores[k])
    cur = s.get("path")
    # 어느 쪽도 유리하지 않으면 자포자기하지 않고 강국에 기대 외교승리를 노린다(동맹을 맺을 수 있는 지도자만)
    other = max(scores[k] for k in ("conquest", "science", "economic"))
    limit = C.AI_P2_HOPELESS * (C.AI_P2_HOPELESS_EXIT if s.get("hopeless") else 1.0)
    # 강국에 기대기로 했으면 최소 48턴은 그대로(관계를 쌓을 시간). 그 뒤 최고점이 문턱×1.25를 넘으면 벗어난다
    committed = s.get("hopeless") and g.turn - s.get("hopeless_turn", -999) < C.AI_P2_HOPELESS_MIN
    if (other < limit or committed) and not g.mods(f.id).value("no_alliance"):
        if not s.get("hopeless") or cur != "diplomatic":
            log = s.setdefault("log", [])
            log.append([g.turn, cur, "diplomatic", reason, "어느 방향도 유리하지 않음: 강국에 기대 외교"])
            del log[:-C.AI_P2_LOG]
            s["path_turn"] = g.turn
            s["hopeless_turn"] = g.turn
        s.update(hopeless=True, path="diplomatic", scores=scores, last_eval=g.turn)
        p = s.get("patron")
        if p is None or not g.factions[p].alive or D.at_war(g, f.id, p):
            s["patron"] = choose_patron(g, f)       # 정한 강국은 바꾸지 않는다(멸망·전쟁이면 다시)
        return "diplomatic"
    was_hopeless = s.get("hopeless", False)
    s["hopeless"] = False
    s.pop("patron", None)
    prev = cur
    if was_hopeless:
        cur = None                                 # 기댈 이유가 사라졌다: 관성 없이 다시 고른다
    # 바꾼 지 24턴이 안 됐으면 정기 재검토로는 바꾸지 않는다(선전포고를 받았거나 위기면 예외)
    settled = reason == "정기" and g.turn - s.get("path_turn", -99) < C.AI_P2_MIN_DWELL
    if cur is None or (not settled and (scores[best] >= C.AI_P2_SWITCH * scores.get(cur, 0.0)
                                        or scores.get(cur, 0.0) < C.AI_P2_MIN_SCORE)):
        if prev != best:
            log = s.setdefault("log", [])
            log.append([g.turn, prev, best, reason, res["why"][best]])
            del log[:-C.AI_P2_LOG]
            s["path_turn"] = g.turn
        cur = best
    s["path"] = cur
    s["scores"] = scores
    s["last_eval"] = g.turn
    return cur


# ------------------------------------------------------------------ 우방(전선 이중화 방지)
def choose_anchor(g, f, sc):
    """국경을 맞댄 나라가 2곳 이상이면(약소국이 아니어도) 우방 1곳을 둔다: 적에게 둘러싸이지 않는 것 자체가 이득.
    이미 우호 선언 + 불가침(또는 동맹)인 이웃이 있으면 그 나라. 없으면 강하고(뒤를 맡길 만하고) 나를 덜 싫어하는 이웃."""
    fid = f.id
    s = state(f)
    if len(sc) < C.AI_P2_ANCHOR_BORDERS:
        return None
    secured = [o for o in sc if D.declared_friends(g, fid, o) and (D.has_nonaggr(g, fid, o) or D.allied(g, fid, o))]
    if s.get("anchor") in secured:
        return s["anchor"]
    if secured:
        return max(secured, key=lambda o: sc[o]["p"])
    mine = max(10.0, g.mil_power(fid))
    cands = [o for o in sc if not D.at_war(g, fid, o) and o != s.get("target")]
    # 상대가 나를 몹시 싫어하면(−50 미만) 관계 회복이 어렵다: 다른 후보가 있으면 뺀다
    ok = [o for o in cands if D.opinion(g, o, fid) >= C.AI_P2_ANCHOR_MIN_OP]
    cands = ok or cands
    if not cands:
        return None
    # 서로의 우호도를 가장 크게 보고, 뒤를 맡길 만큼 강한 이웃을 조금 더 친다
    return max(cands, key=lambda o: ((D.opinion(g, o, fid) + D.opinion(g, fid, o)) / 50
                                     + 0.4 * min(2.0, sc[o]["p"] / mine) - sc[o]["host"], -o))


def choose_patron(g, f):
    """의지할 강국: 만나 본(시야에 들어온 영토의 주인이거나 국경을 맞댄) 나라 가운데 전쟁 중이 아니고 동맹을 맺을 수 있는,
    추정 군사력이 가장 큰 나라."""
    AI = _ai()
    fid = f.id
    known = {g.regions[v].owner for v in g.visible(fid) if v in g.regions}
    known |= set(state(f).get("scan", {}))
    cands = [x for x in known - {NEUTRAL, fid}
             if g.factions[x].alive and not D.at_war(g, fid, x) and not g.mods(x).value("no_alliance")]
    if not cands:
        return None
    return max(cands, key=lambda x: (AI.perceived_power(g, fid, x), -x))


def secured(g, fid, o) -> bool:
    return D.declared_friends(g, fid, o) and (D.has_nonaggr(g, fid, o) or D.allied(g, fid, o))


# ------------------------------------------------------------------ 매 턴 갱신
def update(g, f, threat=None):
    """2페이즈 이상인 AI 에 매 턴: 정세·태세 갱신, 6턴마다(또는 사건이 생기면) 승리 방향·우방 재검토."""
    s = state(f)
    sc = scan(g, f)
    s["scan"] = sc
    old_posture = s.get("posture")
    s["posture"] = posture(g, f, sc, threat)
    tp = threat_power(g, f, sc)
    s["mil_ok"] = g.mil_power(f.id) >= C.AI_P2_MIL_OK * tp
    enemies = set(D.enemies(g, f.id))
    new_enemy = bool(enemies - set(s.get("enemies", ())))
    s["enemies"] = sorted(enemies)
    reason = None
    if "path" not in s:
        reason = "2페이즈 시작"
    elif g.turn - s.get("last_eval", -99) >= C.AI_P2_EVAL_TURNS:
        reason = "정기"
    elif new_enemy:
        reason = "선전포고 받음"
    elif s["posture"] == "crisis" and old_posture != "crisis":
        reason = "위기"
    if reason:
        choose_path(g, f, sc, reason)
        s["anchor"] = choose_anchor(g, f, sc)
    p = s.get("patron")
    if p is not None and (not g.factions[p].alive or D.at_war(g, f.id, p)):
        s["patron"] = choose_patron(g, f) if s.get("hopeless") else None
    cnt = s.setdefault("posture_n", {})
    cnt[s["posture"]] = cnt.get(s["posture"], 0) + 1
    return s


def path_of(f):
    p = f.ai.get("p2")
    return p.get("path") if p else None


def posture_of(f) -> str:
    p = f.ai.get("p2")
    return p.get("posture", "normal") if p else "normal"
