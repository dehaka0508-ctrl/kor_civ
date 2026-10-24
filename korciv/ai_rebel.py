"""반군 AI(v1.3.21). 일반 국가와 다른 싸움:
1) 확장: 원 국가 지역을 빠르게 4곳 이상 차지한다(빈 곳·약한 곳부터, 수도는 기회가 오면 바로).
2) 버티기: 4곳을 넘기면 방어와 생존에 치중한다. 지키는 병력·방어선을 먼저 채우고, 지킬 병력이 남을 때만
   비어 있는 땅을 먹는다. 방어에 불리해지는(원 국가와 맞닿는 면이 넓어지는) 무리한 확장은 하지 않는다.
3) 모든 군사 유닛을 잃고 원 국가 병력이 코앞에 있으면 항복한다(원 국가가 플레이어면 항복 제의).
생산은 민병대(1턴·비용 0)와 방어선뿐이다."""
from __future__ import annotations

import math

from . import config as C
from . import diplomacy as D
from .state import NEUTRAL

MIL = "mil"
GUARD_MARGIN = 1.25          # 위협 대비 지킬 병력 여유
ATTACK_MARGIN = 1.2          # 공격: 내 공격력 ≥ 방어력 × 이만큼
CAP_MARGIN = 1.0             # 원 국가 수도(점령하면 즉시 독립)는 이 정도면 시도
EXPAND_EXTRA = 3             # 확장 단계에서 지킬 병력 밖에 더 모을 민병대
UNIT_CAP_PER_REGION = 4      # 위협이 없을 때 지역당 이 정도까지만 민병대를 둔다
LINE_MAX = 3                 # 방어선은 3단계까지
SURRENDER_COOLDOWN = 6       # 플레이어에게 항복 제의를 다시 하기까지


def _units(a) -> int:
    return sum(n for k, n in a.units.items() if C.UNITS[k]["kind"] == "land" and not C.UNITS[k].get("science"))


def _land_armies(g, fid, loc=None):
    return [a for a in g.armies.values() if a.owner == fid and a.domain() == "land" and not g.world.is_sea(a.loc)
            and (loc is None or a.loc == loc) and _units(a) > 0]


def _atk(g, a) -> float:
    return sum(a.spec(k)["atk"] * a.units[k] * g.eff(a, k) for k in a.units if k in C.ASSAULT_UNITS)


def _df(g, a) -> float:
    return sum(g.leader_unit_defense(a, k) * n for k, n in a.units.items() if k not in C.NO_GROUND_COMBAT)


def enemy_power_near(g, fid, rid, foe) -> float:
    """rid 와 맞닿은 원 국가 병력의 공격력(보이는 것)."""
    tot = 0.0
    for n in g.world.land_adj[rid]:
        if not g.is_visible(fid, n):
            continue
        for a in g.armies_at(n):
            if a.owner == foe:
                tot += sum(a.spec(k)["atk"] * c for k, c in a.units.items() if k in C.ASSAULT_UNITS)
    return tot


def target_defense(g, fid, tgt) -> float:
    """공격 대상의 방어력 추정(방어선 반영)."""
    rr = g.regions[tgt]
    d = sum(_df(g, a) for a in g.hostile_units_at(fid, tgt))
    lines = max(rr.lines.values(), default=0) if rr.owner != NEUTRAL else 0
    return d * (1 + C.LINE_BONUS * lines)


def frontier(g, fid, foe) -> set:
    """원 국가(또는 그 병력)와 맞닿은 내 지역."""
    out = set()
    for r in g.regions_of(fid):
        if any(g.regions[n].owner == foe for n in g.world.land_adj[r.id]):
            out.add(r.id)
    return out


def exposure(g, fid, foe, rid) -> int:
    """rid 를 가지면 새로 생기는 원 국가와의 맞닿음 수(내 땅으로 둘러싸인 곳일수록 작다)."""
    return sum(1 for n in g.world.land_adj[rid] if g.regions[n].owner == foe)


def guard_need(g, fid, foe, rid) -> int:
    """지역을 지킬 민병대 수: 맞닿은 원 국가 공격력 ÷ 민병대 방어력 × 여유(최소 1, 후방 0)."""
    near = enemy_power_near(g, fid, rid, foe)
    edge = any(g.regions[n].owner == foe for n in g.world.land_adj[rid])
    if not edge and near <= 0:
        return 1 if rid == g.factions[fid].capital else 0
    lines = max(g.regions[rid].lines.values(), default=0)
    per = C.UNITS[MIL]["df"] * (1 + C.LINE_BONUS * lines)
    n = math.ceil(near * GUARD_MARGIN / per) if near > 0 else 1
    return max(1, n) + (1 if rid == g.factions[fid].capital else 0)


def plan_turn(g, fid):
    f = g.factions[fid]
    if not f.alive or not getattr(f, "rebel", False):
        return
    foe = f.rebel_of
    f.auto_food = True
    if g.can_surrender(fid):
        if _hopeless(g, fid, foe):
            _surrender(g, f, foe)
            if not f.alive:
                return
    held = g.rebel_hold_count(fid)
    expand = held < C.REBEL_INDEP_REGIONS
    _armies(g, f, foe, expand)
    _production(g, f, foe, expand)


def _hopeless(g, fid, foe) -> bool:
    """모든 군사 유닛을 잃었고 원 국가 병력이 내 땅 안이나 바로 옆에 있다."""
    mine = {r.id for r in g.regions_of(fid)}
    near = mine | {n for r in mine for n in g.world.land_adj[r]}
    return any(a.owner == foe and a.loc in near and a.domain() == "land" for a in g.armies.values())


def _surrender(g, f, foe):
    if foe == g.player_id and not g.factions[foe].is_ai and not g.settings.all_ai:
        if g.turn - f.ai.get("surrender_offer", -99) < SURRENDER_COOLDOWN:
            return
        f.ai["surrender_offer"] = g.turn
        if not any(p.get("from") == f.id and p.get("kind") == "surrender" for p in g.pending_proposals):
            g.pending_proposals.append({"from": f.id, "kind": "surrender"})
        return
    g.rebel_surrender(f.id)


# ------------------------------------------------------------------ 부대
def _armies(g, f, foe, expand):
    fid = f.id
    regs = {r.id for r in g.regions_of(fid)}
    need = {rid: guard_need(g, fid, foe, rid) for rid in regs}
    have = {rid: sum(_units(a) for a in _land_armies(g, fid, rid)) for rid in regs}
    # 1) 공격: 원 국가 수도 → (확장 단계) 약한 원 국가 지역 → (버티기 단계) 빈 원 국가 지역 → 빈 중립 땅
    targets = _targets(g, fid, foe, regs, expand)
    used = set()
    for tgt, kind in targets:
        srcs = [r for r in g.world.land_adj[tgt] if r in regs]
        if not srcs:
            continue
        D_ = target_defense(g, fid, tgt)
        empty = D_ <= 0
        # 지킬 병력을 남기고 보낼 수 있는 부대(확장 단계나 수도 공격은 1만 남기고)
        pool = []
        for s in srcs:
            keep = need[s] if not (expand or kind == "capital") else min(need[s], 1)
            spare = have[s] - keep
            for a in sorted(_land_armies(g, fid, s), key=lambda a: -_units(a)):
                if a.id in used or a.order or spare <= 0:
                    continue
                take = min(spare, _units(a))
                if take < _units(a):
                    a = _split(g, a, take)
                    if a is None:
                        continue
                pool.append(a)
                spare -= _units(a)
        if not pool:
            continue
        A = sum(_atk(g, a) for a in pool)
        margin = CAP_MARGIN if kind == "capital" else ATTACK_MARGIN
        if not empty and A < D_ * margin:
            for a in pool:                       # 모자라면 공격하지 않고 다시 합친다
                _rejoin(g, fid, a)
            continue
        if empty:
            pool = pool[:1]                      # 빈 땅은 한 부대만
        line = max(g.regions[tgt].lines.values(), default=0) if g.regions[tgt].owner != NEUTRAL else 0
        mode = "surprise" if line == 0 and not empty else "assault"
        for a in pool:
            ok, _ = g.order_army(a.id, tgt, mode)
            if ok:
                used.add(a.id)
                have[a.loc] = have.get(a.loc, 0) - _units(a)
    # 2) 남는 병력: 모자란 지역(위협이 큰 곳)부터 채운다. 확장 단계면 공격할 곳 옆으로 모은다
    deficit = {rid: need[rid] - have.get(rid, 0) for rid in regs if need[rid] > have.get(rid, 0)}
    stage = None
    if expand and targets:
        tgt = targets[0][0]
        stage = next((r for r in g.world.land_adj[tgt] if r in regs), None)
    for a in sorted(_land_armies(g, fid), key=lambda a: a.id):
        if a.id in used or a.order or a.id not in g.armies:
            continue
        spare = have.get(a.loc, 0) - need.get(a.loc, 0)
        if spare <= 0:
            continue
        dest = None
        if deficit:
            dest = max(deficit, key=lambda r: (deficit[r], r))
        elif stage is not None and stage != a.loc:
            dest = stage
        if dest is None or dest == a.loc:
            continue
        n = min(spare, _units(a))
        b = _split(g, a, n) if n < _units(a) else a
        if b is None:
            continue
        if _go(g, fid, b, dest):
            have[a.loc] = have.get(a.loc, 0) - n
            if dest in deficit:
                deficit[dest] -= n
                if deficit[dest] <= 0:
                    del deficit[dest]
        elif b is not a:
            g.merge_armies(a.id, b.id)


def _split(g, a, n):
    """a 에서 지상 유닛 n 개를 떼어 낸 새 부대(못 나누면 None)."""
    take, left = {}, n
    for k in (MIL, "inf", "tank"):
        t = min(left, a.units.get(k, 0))
        if t > 0:
            take[k] = t
            left -= t
    if left > 0 or not take:
        return None
    b, _ = g.split_army(a.id, take)
    return b


def _rejoin(g, fid, a):
    for b in _land_armies(g, fid, a.loc):
        if b.id != a.id and not b.order:
            g.merge_armies(b.id, a.id)
            return


def _go(g, fid, a, dest) -> bool:
    reach = g.reachable(a)
    if reach.get(dest, {}).get("action") == "move":
        return g.order_army(a.id, dest)[0]
    route = g.plan_route(a, dest)
    return bool(route) and g.order_army(a.id, dest)[0]


def _targets(g, fid, foe, regs, expand):
    """공격·점령할 곳 [(지역, 종류)] 우선순위 순."""
    w = g.world
    cap = g.factions[foe].capital if foe is not None and g.factions[foe].alive else None
    cands = {n for r in regs for n in w.land_adj[r] if n not in regs}
    out = []
    for n in cands:
        rr = g.regions[n]
        o = rr.owner
        if o == foe:
            if not D.at_war(g, fid, foe) or not g.can_attack_now(fid, foe):
                continue
            d = target_defense(g, fid, n)
            touch = sum(1 for x in w.land_adj[n] if x in regs)
            exp = exposure(g, fid, foe, n)
            if n == cap:
                out.append((0, -touch, n, "capital"))
            elif expand:
                out.append((1 if d <= 0 else 2, d / (1 + touch) + 0.5 * exp, n, "foe"))
            elif d <= 0 and (touch >= 2 or exp <= 2):
                out.append((3, exp - touch, n, "foe"))    # 버티기: 빈 땅이고 전선을 넓히지 않는 곳만
        elif o == NEUTRAL and not g.hostile_units_at(fid, n) and fid not in rr.occs:
            if exposure(g, fid, foe, n) <= (2 if expand else 1):
                out.append((4, exposure(g, fid, foe, n), n, "neutral"))   # 빈 중립 땅
    out.sort(key=lambda x: (x[0], x[1], x[2]))
    return [(n, k) for _, _, n, k in out]


# ------------------------------------------------------------------ 생산
def _production(g, f, foe, expand):
    fid = f.id
    regs = g.regions_of(fid)
    total = sum(_units(a) for a in _land_armies(g, fid))
    need = sum(guard_need(g, fid, foe, r.id) for r in regs)
    threatened = any(enemy_power_near(g, fid, r.id, foe) > 0 for r in regs)
    cap = max(need + (EXPAND_EXTRA if expand else 0), UNIT_CAP_PER_REGION * len(regs) if threatened else need + 2)
    front = frontier(g, fid, foe)
    for r in sorted(regs, key=lambda r: (-enemy_power_near(g, fid, r.id, foe), r.id)):
        if r.project is not None or g.resisting(r) or r.occ:
            continue
        here = sum(_units(a) for a in _land_armies(g, fid, r.id))
        near = enemy_power_near(g, fid, r.id, foe)
        # 버티기 단계: 지킬 병력이 찬 전선 지역은 방어선을 올린다(돈이 있으면)
        if not expand and r.id in front and here >= guard_need(g, fid, foe, r.id) and _line(g, f, foe, r):
            continue
        if total >= cap and near <= 0:
            continue
        ok, _ = g.start_project(fid, r.id, "unit", MIL)
        if ok:
            total += 1


def _line(g, f, foe, r) -> bool:
    """원 국가와 맞닿은 경계 중 가장 위협적인 곳에 방어선 한 단계(LINE_MAX 까지)."""
    borders = [n for n in g.world.land_adj[r.id] if g.regions[n].owner == foe]
    borders.sort(key=lambda n: (-sum(_atk(g, a) for a in g.armies_at(n) if a.owner == foe), r.lines.get(n, 0), n))
    for b in borders:
        if r.lines.get(b, 0) >= LINE_MAX:
            continue
        opt = next((o for o in g.options(f.id, r.id) if o["kind"] == "build" and o["key"] == "line"
                    and o.get("border") == b), None)
        if opt is None or not opt["ok"] or opt["cost"] > f.money * 0.6:
            continue
        ok, _ = g.start_project(f.id, r.id, "build", "line", border=b)
        if ok:
            return True
    return False
