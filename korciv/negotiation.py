"""자원·특산물 거래 협상(v1.3.0).

거래는 '턴당 n개 × 12턴, 개당 값(받는 턴마다 낸다)' 계약이다. 수락·거절만 있던 제의를 FM의 선수 계약·문명 시리즈의
거래처럼 값을 주고받는 협상으로 바꾼다.

- AI는 거래마다 **유보 가격**(팔 때 최저가, 살 때 최고가)을 정한다. 경우별 규칙(남는 양·빈 공장·평균 공장 산출 × 세율,
  행복도·반란 문턱, 재정)에 지도자 성향(호전성)·우호도·작은 무작위가 더해진다.
- 처음 부르는 값은 유보 가격에서 욕심만큼 벌린 값이고, 역제의 때마다 상대 값 쪽으로 양보한다.
- 역제의 횟수(인내)는 1~4회로, 우호도·거래가 급한 정도·성향과 무작위로 정해진다. 인내가 다하면 마지막 제안을 하고,
  그보다 나쁜 값이면 협상이 결렬된다(그 턴에는 같은 거래를 다시 못 한다).
- 무작위는 (판 시드, 턴, 두 나라, 자원, 방향)으로 정해져 같은 턴에 다시 열어도 같다(다시 열어 운을 시험할 수 없다).
"""
from __future__ import annotations

import math
import random

from . import config as C
from . import diplomacy as D
from . import rules as RL
from .state import NEUTRAL
from .text import josa

RES = ("food", "oil", "coal", "elec", "specialty")
RES_NAMES = {"food": "식량", "oil": "석유", "coal": "석탄", "elec": "전기", "specialty": "특산물"}
MAX_ROUNDS = 4
INSULT = 0.6            # 유보 가격의 60%(살 때는 1/0.6배)보다 나쁜 값은 무례한 제안: 인내를 하나 더 잃는다


# ------------------------------------------------------------------ 상황 지표
def _reserve_money(g, fid) -> float:
    f = g.factions[fid]
    spend = sum(p.per_turn for p in g.unique_projects(g.regions_of(fid)))
    return 300 + g.upkeep(fid) * 5 + spend * 3 + abs(min(0.0, f.last.get("net", 0.0))) * 5


def money_urgency(g, fid) -> float:
    """돈이 급한 정도 0~1: 비축이 필요 자금의 2배 이상이면 0, 바닥이면 1, 적자면 더 급하다."""
    f = g.factions[fid]
    u = 1.0 - f.money / (2 * _reserve_money(g, fid))
    if f.last.get("net", 0.0) < 0:
        u += 0.25
    return max(0.0, min(1.0, u))


def money_comfort(g, fid) -> float:
    """돈이 넉넉한 정도 0~1: 필요 자금의 2배면 0, 8배 이상이면 1."""
    f = g.factions[fid]
    return max(0.0, min(1.0, (f.money / _reserve_money(g, fid) - 2.0) / 6.0))


def toughness(g, fid) -> float:
    """지도자 성향: 호전적일수록 값을 세게 부르고 덜 양보한다(−1~1)."""
    from . import ai as AI
    return max(-1.0, min(1.0, (AI.eff_aggression(g, g.factions[fid]) - 5.0) / 5.0))


def op_factor(g, ai, other) -> float:
    return max(-1.0, min(1.0, D.opinion(g, ai, other) / 100.0))


def happy_level(g, fid) -> float:
    """평균 실질 행복도 0(이하)~40(이상) → 0~1."""
    return max(0.0, min(1.0, g.avg_happiness(fid) / 40.0))


def rebel_proximity(g, fid) -> float:
    """반란 문턱이 가까운 정도: 가장 불행한 지역의 반란 판정 행복도 −10 → 0, −50(문턱) → 1."""
    hs = [g.rebel_happy(r) for r in g.regions_of(fid) if not g.resist_phase(r)[0]]
    if not hs:
        return 0.0
    return max(0.0, min(1.0, (-10.0 - min(hs)) / (-10.0 - C.REBEL_THRESHOLD)))


# ------------------------------------------------------------------ 양과 가치
def avg_factory_unit(g, fid) -> float:
    """평균 공장 산출량(연료 1개당) × 현행 세율: 공장에서 연료 하나를 빼면 잃는 턴당 세수."""
    facts = [r for r in g.regions_of(fid) if r.b["factory"] > 0 and not r.occ and not g.resisting(r)]
    if not facts:
        return 0.0
    m = g.mods(fid)
    per = sum(RL.factory_unit(r.b["factory"]) for r in facts) / len(facts)
    return per * m.mult("output_factory") * m.mult("output_prod") * g.factions[fid].tax


def _eval(g, fid):
    return D.energy_eval(g, fid, g.energy_supply(fid))


def surplus(g, fid, res) -> int:
    """자기 발전소·공장에 다 넣고도 남는 턴당 양(특산물은 자기 지역에 공급하고 남는 양)."""
    if res == 'food':
        f = g.factions[fid]
        net = sum(g.food_prod(fid, r) - r.pop * C.FOOD_PER_POP for r in g.regions_of(fid))
        return max(0, int(net + max(0, f.res.get('food', 0) - g.total_pop(fid) * 4) / C.CONTRACT_TURNS))
    if res == "specialty":
        used = sum(len(r.supplied) for r in g.regions_of(fid))
        return max(0, D.spec_supply(g, fid) - used)
    return int(_eval(g, fid)[1][res])


def supply_total(g, fid, res) -> int:
    """팔 수 있는 최대 턴당 양: 확보량(채굴·자체 발전 + 계약), 전기는 발전소 발전량까지."""
    if res == "food":
        return surplus(g, fid, res)
    if res == "specialty":
        return D.spec_supply(g, fid)
    n = g.energy_supply(fid)[res]
    if res == "elec":
        plan = g.auto_energy_plan(fid, g.energy_supply(fid), oil_reserve=0)
        n += int(sum(g.plant_elec(fid, g.regions[rid].b["power"], a["coal"], a["oil"]) for rid, a in plan["p"].items())
                 + 1e-9)
    return int(n)


def factory_room(g, fid) -> int:
    """자기 자원을 다 넣고도 비는 공장 칸."""
    return int(_eval(g, fid)[2])


def buy_unit_value(g, fid, res, n) -> float:
    """res 를 턴당 n개 더 받으면 늘어나는 턴당 세수(공장 산출 증가 × 현행 세율)의 개당 값."""
    if n <= 0:
        return 0.0
    if res == "food":
        return C.MARKET_BUY["food"] * C.MONEY_SCALE
    fac, _ = D.energy_value(g, fid, res, n)
    return max(0.0, fac) / n


def spec_want(g, fid) -> int:
    """특산물을 더 받을 만한 지역 수(실질 행복도 20 미만이고 공급 칸이 남은 곳)."""
    return sum(1 for r in g.regions_of(fid) if g.eff_happy(r) < 20 and len(r.supplied) < C.SPECIALTY_MAX_TYPES
               and not g.resist_phase(r)[0])


def _round_price(p: float) -> float:
    return float(max(1, int(round(p))))


# ------------------------------------------------------------------ 유보 가격
def reserve(g, ai, other, res, n, ai_sells, noise=1.0):
    """AI(ai)가 other 와 res 를 턴당 n개 거래할 때의 유보 가격(팔면 최저가, 사면 최고가).
    반환 (가격 또는 None, 받아들일 수 있는 수량, 이유)."""
    tough, op = toughness(g, ai), op_factor(g, ai, other)
    urg, comfort = money_urgency(g, ai), money_comfort(g, ai)
    f = g.factions[ai]
    if res == 'food':
        if ai_sells:
            n_ok = min(n, surplus(g, ai, res))
            price = C.MARKET_SELL['food'] * C.MONEY_SCALE * (1.05 + .15 * tough - .1 * op)
            return (price if n_ok else None), n_ok, '' if n_ok else '비축 식량이 부족합니다'
        deficit = max(0, g.total_pop(ai) * C.FOOD_PER_POP - sum(g.food_prod(ai, r) for r in g.regions_of(ai)))
        if not deficit:
            return None, 0, '식량이 충분합니다'
        n_ok = min(n, max(1, int(math.ceil(deficit))))
        price = min(C.MARKET_BUY['food'] * C.MONEY_SCALE, f.money / max(1, n_ok * 3))
        return (price if price >= 1 else None), n_ok, '' if price >= 1 else '낼 돈이 없습니다'
    if res == "specialty":
        v = D.spec_price(g, ai)
        happy, prox = happy_level(g, ai), rebel_proximity(g, ai)
        if ai_sells:
            tot = D.spec_supply(g, ai)
            if tot < 1:
                return None, 0, "내줄 특산물이 없습니다"
            n_ok = min(n, tot)
            spare = surplus(g, ai, "specialty")
            if n_ok <= spare:          # 자기 지역에 공급하고 남는 몫: 행복도가 높고 돈이 급할수록 싸게
                mult = 0.7 - 0.25 * urg - 0.2 * happy + 0.2 * tough - 0.15 * max(0.0, op) + 0.3 * max(0.0, -op)
                return v * max(0.15, mult) * noise, n_ok, ""
            if prox > 0.3 or happy < 0.25:
                if spare >= 1:
                    return reserve(g, ai, other, res, spare, ai_sells, noise)[0], spare, "자기 지역에 필요한 몫은 못 판다"
                return None, 0, "우리 지역에도 모자랍니다"
            mult = 1.2 + 0.2 * tough - 0.3 * urg - 0.3 * happy - 0.1 * max(0.0, op)
            return v * max(0.4, mult) * noise, n_ok, ""
        want = spec_want(g, ai)
        interest = (1 - happy) + 0.6 * comfort + 1.2 * prox
        if interest < 0.45 and want == 0:
            return None, 0, "특산물이 아쉽지 않습니다"
        n_ok = min(n, max(want, 2))
        mult = 0.5 + 0.5 * (1 - happy) + 0.8 * prox + 0.3 * comfort + 0.1 * op - 0.1 * tough - 0.3 * urg
        p = v * max(0.2, mult) * noise
        p = min(p, f.money / max(1, n_ok * 3))          # 3턴분은 낼 수 있어야 한다
        return (p if p > 0 else None), n_ok, ("" if p > 0 else "낼 돈이 없습니다")
    if ai_sells:
        tot = supply_total(g, ai, res)
        if tot < 1:
            return None, 0, f"내줄 {josa(RES_NAMES[res], '이/가')} 없습니다"
        n_ok = min(n, tot)
        base = g.sell_price(ai, res) or C.MARKET_SELL[res] * C.MONEY_SCALE
        # 남는 몫: 어차피 시장에 팔릴 양이라 시장 판매가 근처. 돈이 급하거나 우호도가 높을수록 싸게
        mult = 1.3 + 0.25 * tough - 0.35 * urg - 0.3 * max(0.0, op) + 0.4 * max(0.0, -op)
        p = base * max(0.7, mult) * noise
        # 사는 쪽이 얻는 가치(공장 산출 × 세율)의 몫은 받으려 한다: 시장에 헐값으로 넘기지 않는다
        bv = buy_unit_value(g, other, res, n_ok) if other != NEUTRAL else 0.0
        share = 0.45 + 0.15 * tough - 0.15 * urg - 0.1 * max(0.0, op)
        p = max(p, bv * max(0.2, share) * noise)
        if n_ok > surplus(g, ai, res):
            # 남는 양을 넘으면 공장에서 빼야 한다: 평균 공장 산출 × 세율보다 비쌀 때만
            t = avg_factory_unit(g, ai)
            p = max(p, t * (1.05 + 0.1 * tough) * noise)
        return p, n_ok, ""
    room = factory_room(g, ai)
    if room < 1:
        return None, 0, "빈 공장이 없습니다"
    n_ok = min(n, room)
    val = buy_unit_value(g, ai, res, n_ok)
    if val <= 0:
        return None, 0, "들여도 늘어날 산출이 없습니다"
    mult = 0.62 + 0.12 * op - 0.1 * tough + 0.12 * comfort - 0.2 * urg
    p = min(val * 0.99, val * max(0.25, mult) * noise)  # 산출 × 세율보다 비싸면 절대 사지 않는다
    p = min(p, f.money / max(1, n_ok * 3))
    return (p if p > 0 else None), n_ok, ("" if p > 0 else "낼 돈이 없습니다")


# ------------------------------------------------------------------ 협상 상태
def _rng(g, ai, other, res, ai_sells) -> random.Random:
    seed = getattr(g.settings, "seed", 0) or 0
    return random.Random(f"nego:{seed}:{g.turn}:{ai}:{other}:{res}:{int(ai_sells)}")


def blocked(g, ai, other, res, ai_sells) -> bool:
    return (ai, other, res, bool(ai_sells)) in g.dip.__dict__.setdefault("nego_block", set())


def _block(g, st):
    g.dip.__dict__.setdefault("nego_block", set()).add((st["ai"], st["other"], st["res"], st["ai_sells"]))


def start(g, ai, other, res, n, ai_sells, init="player"):
    """협상을 연다. AI 의 유보 가격·첫 값·인내(역제의 횟수)·양보 폭을 정한다."""
    rng = _rng(g, ai, other, res, ai_sells)
    noise = rng.uniform(0.92, 1.08)
    st = {"ai": ai, "other": other, "res": res, "n": int(n), "ai_sells": bool(ai_sells), "init": init,
          "turn": g.turn, "noise": noise, "hist": [], "status": "open", "final": False}
    if blocked(g, ai, other, res, ai_sells):
        st.update(status="refused", why="이번 턴에는 이 거래를 다시 이야기하지 않겠답니다(협상 결렬).")
        return st
    if D.at_war(g, ai, other) or D.opinion(g, ai, other) < C.AI_TRADE_MIN_OP:
        st.update(status="refused", why="지금 관계로는 거래하지 않겠답니다.")
        return st
    R, n_ok, why = reserve(g, ai, other, res, n, ai_sells, noise)
    if R is None or n_ok < 1:
        st.update(status="refused", why=why or "거래할 수 없습니다.")
        return st
    tough, op = toughness(g, ai), op_factor(g, ai, other)
    if res == "specialty":
        need = rebel_proximity(g, ai) if not ai_sells else money_urgency(g, ai)
    else:
        need = money_urgency(g, ai) if ai_sells else 0.4
    greed = max(0.08, min(0.45, 0.2 + 0.15 * tough - 0.1 * op + rng.uniform(0.0, 0.1)))
    rounds = int(round(1 + 1.2 * (op + 1) / 2 + 1.2 * need - 0.8 * max(0.0, tough) + rng.uniform(-0.5, 1.0)))
    st.update(R=R, n=n_ok, rounds=max(1, min(MAX_ROUNDS, rounds)), rounds0=max(1, min(MAX_ROUNDS, rounds)),
              c=max(0.2, min(0.65, 0.35 + 0.15 * op - 0.1 * tough + rng.uniform(-0.05, 0.1))),
              price=_round_price(R * (1 + greed) if ai_sells else R * (1 - greed)), rng_state=rng.getstate())
    if init == "ai":
        st["hist"].append(("ai", st["n"], st["price"], _line(st, "open")))
    return st


def _line(st, kind, p=None) -> str:
    """AI 의 말(지도자 이름은 UI 가 붙인다)."""
    x = st["price"] if p is None else p
    sell = st["ai_sells"]
    if kind == "open":
        return f"턴당 {st['n']}개를 개당 {x:,.0f}에 {'팔겠습니다' if sell else '사겠습니다'}."
    if kind == "counter":
        return f"그 값으로는 어렵습니다. 개당 {josa(f'{x:,.0f}', '은/는')} 어떻습니까?"
    if kind == "final":
        return f"개당 {x:,.0f}. 이것이 마지막 제안입니다."
    if kind == "accept":
        return f"좋습니다. 개당 {x:,.0f}에 하지요."
    if kind == "insult":
        return "터무니없는 값이군요. 진지하게 이야기합시다."
    if kind == "broken":
        return "더 이야기할 것이 없군요. 협상은 여기까지입니다."
    if kind == "qty":
        return f"턴당 {st['n']}개까지만 됩니다."
    return ""


def _recompute(g, st, n):
    """수량이 바뀌면 유보 가격을 다시 잡는다(같은 무작위·인내 그대로)."""
    R, n_ok, why = reserve(g, st["ai"], st["other"], st["res"], n, st["ai_sells"], st["noise"])
    if R is None or n_ok < 1:
        return False, why
    old = st["R"]
    st["R"], st["n"] = R, n_ok
    if old > 0:                                         # 지금 부르는 값도 같은 비율로 옮긴다
        st["price"] = _round_price(st["price"] * R / old)
    return True, ""


def _rand(st) -> float:
    rng = random.Random()
    rng.setstate(st["rng_state"])
    v = rng.random()
    st["rng_state"] = rng.getstate()
    return v


def player_offer(g, st, n, price):
    """플레이어가 (턴당 n개, 개당 price)를 부른다. 반환 (결과, AI 의 말).
    결과: accept(성사) · counter(역제의) · final(마지막 제안) · qty(수량 조정 역제의) · broken(결렬) · refused."""
    if st["status"] != "open":
        return st["status"], st.get("why", "")
    price = float(price)
    n = int(n)
    st["hist"].append(("me", n, price, ""))
    want_n = n
    if n != st["n"] or st.get("R") is None:
        ok, why = _recompute(g, st, n)
        if not ok:
            st["status"], st["why"] = "broken", why
            _block(g, st)
            st["hist"].append(("ai", st["n"], st["price"], why))
            return "broken", why
    sell, R, A = st["ai_sells"], st["R"], st["price"]
    if st["n"] < want_n:                                # 그만큼은 안 된다: 가능한 수량으로 역제의
        st["hist"].append(("ai", st["n"], A, _line(st, "qty")))
        return "qty", _line(st, "qty")
    good = (price >= A - 1e-9) if sell else (price <= A + 1e-9)
    ok_zone = (price >= R) if sell else (price <= R)
    if good or (ok_zone and st["rounds"] <= 0):
        return _accept(g, st, price)
    if ok_zone:
        gap = (A - price) / max(1e-6, A - R) if sell else (price - A) / max(1e-6, R - A)
        if _rand(st) < 0.35 + 0.65 * (1 - max(0.0, min(1.0, gap))):
            return _accept(g, st, price)
    insult = (price < R * INSULT) if sell else (price > R / INSULT)
    if insult:
        st["rounds"] -= 1
        D.add_opinion(g, st["ai"], st["other"], -0.5)
    if st["rounds"] <= 0 and not ok_zone:
        st["status"], st["why"] = "broken", _line(st, "broken")
        _block(g, st)
        D.add_opinion(g, st["ai"], st["other"], -0.5)
        st["hist"].append(("ai", st["n"], A, (_line(st, "insult") + " " if insult else "") + _line(st, "broken")))
        return "broken", st["why"]
    # 역제의: 상대 값 쪽으로 양보하되 유보 가격은 넘지 않는다
    new = A - st["c"] * (A - price) if sell else A + st["c"] * (price - A)
    new = max(R, new) if sell else min(R, new)
    new = _round_price(new)
    if (new <= price + 1e-9) if sell else (new >= price - 1e-9):
        return _accept(g, st, price)
    st["price"] = new
    st["rounds"] -= 1
    kind = "final" if st["rounds"] <= 0 else "counter"
    st["final"] = kind == "final"
    st["hist"].append(("ai", st["n"], new, (_line(st, "insult") + " " if insult else "") + _line(st, kind)))
    return kind, st["hist"][-1][3]


def _accept(g, st, price):
    st["price"] = _round_price(price) if price >= 1 else float(price)
    text = _line(st, "accept", st["price"])
    st["hist"].append(("ai", st["n"], st["price"], text))
    _execute(g, st)
    return "accept", text


def accept_ai_price(g, st):
    """플레이어가 AI 가 지금 부른 값을 받아들인다."""
    if st["status"] != "open":
        return False, st.get("why", "")
    st["hist"].append(("me", st["n"], st["price"], "그 값에 하지요."))
    _execute(g, st)
    return True, f"거래 성사: {RES_NAMES[st['res']]} 턴당 {st['n']}개 × {C.CONTRACT_TURNS}턴, 개당 {st['price']:,.0f}"


def walk_away(g, st):
    """플레이어가 협상을 그만둔다(AI 가 먼저 낸 제의면 거절)."""
    if st["status"] == "open":
        st["status"] = "closed"


def _execute(g, st):
    st["status"] = "done"
    ai, other = st["ai"], st["other"]
    seller, buyer = (ai, other) if st["ai_sells"] else (other, ai)
    proposer = ai if st["init"] == "ai" else other
    D.make_trade(g, seller, buyer, st["res"], st["n"], st["price"], proposer)


def mood(st) -> str:
    """AI 의 인내(남은 역제의)를 말로."""
    if st["status"] != "open":
        return ""
    r = st.get("rounds", 0)
    if r <= 0 or st.get("final"):
        return "마지막 제안"
    return {1: "인내가 거의 바닥", 2: "조금 조바심", 3: "여유 있음"}.get(r, "느긋함")


# ------------------------------------------------------------------ AI 끼리
def ai_deal(g, seller, buyer, res, n):
    """AI 끼리는 서로의 유보 가격이 겹치면 가운데 값으로 바로 맺는다. 반환 계약 또는 None."""
    rs, ns, _ = reserve(g, seller, buyer, res, n, True)
    rb, nb, _ = reserve(g, buyer, seller, res, n, False)
    if rs is None or rb is None:
        return None
    q = min(ns, nb)
    if q < 1:
        return None
    if q != n:
        rs, _, _ = reserve(g, seller, buyer, res, q, True)
        rb, _, _ = reserve(g, buyer, seller, res, q, False)
        if rs is None or rb is None:
            return None
    if rs > rb:
        return None
    return D.make_trade(g, seller, buyer, res, q, _round_price((rs + rb) / 2), seller)
