"""광역시(v1.2.19): 중심 지역에서 육상 3칸 안의 내 지역들(최대 25곳)을 묶어 하나의 지역처럼 다룬다.

지도·소유·부대 위치는 지역 단위 그대로 두고, 그 위에 묶음을 얹는다.
- 슬롯 1개: 구성 지역 모두가 같은 작업(Project) 하나를 가리킨다.
- 생산·방어 건물(농장·어장·공장·은행·발전소·특산물 시설·탄광·정유·방공호·대공포): 지을 수 있는 구성 지역들의 평균 단계(내림)를
  그 지역들에 실제로 적용한다(→ 산출·연료 소비가 '평균 단계 × 지역 수'). 광역시에서 한 단계 올리면 모두 함께 오른다.
  농장·어장·공장·은행은 6단계까지(광역시 전용).
- 특산물 시설은 특산물이 있는 구성 지역들끼리 통합(v1.2.27), 방어선만 지역마다 따로(행동 탭에 지역별로 나열).
- 항구·공항·사관학교: 하나라도 있으면 광역시 전체에 있는 것으로(항구는 해안 지역마다).
- 행복도는 중심 값 하나(구성 지역은 같은 값), 특산물 배분·반란 판정도 한 지역처럼.
- 군 유닛은 하나를 생산하면 지역 수만큼 나온다. 공격받으면 광역시 안의 병력이 함께 방어하고(방어력 ×(1 − 0.02(n − 1))),
  점령되면 통째로 넘어간다(저항 기간이 끝나면 지정 해제).
- 해제하면 건물 단계 = 묶기 전 단계 + (지금 단계 − 묶은 시점 평균 단계), 유일 건물은 중심(항구는 해안 지역), 부대는 중심으로.
"""
from __future__ import annotations

import math

from . import config as C
from . import rules as R
from .state import NEUTRAL, Project

# (통합 종류, 건물 키). 탄광·정유는 같은 '채굴 시설' 키지만 지을 수 있는 지역이 달라 따로 묶는다
POOLS = (("farm", "farm"), ("fishery", "fishery"), ("factory", "factory"), ("bank", "bank"),
         ("power", "power"), ("specialty", "specialty"), ("coal", "extract"), ("oil", "extract"),
         ("shelter", "shelter"), ("aa", "aa"))
POOL_KEY = dict(POOLS)
SINGLES = ("port", "airport", "academy")
SNAP_KEYS = ("farm", "fishery", "factory", "bank", "power", "specialty", "extract", "shelter", "aa") + SINGLES
POOL_NAMES = {"farm": "광역 경작지", "fishery": "광역 어장", "factory": "광역 공업 지구", "bank": "광역 금융 지구",
              "power": "광역 발전소", "specialty": "광역 특산물 시설", "coal": "광역 탄광", "oil": "광역 정유공장",
              "shelter": "광역 방공호", "aa": "광역 대공포"}


# ------------------------------------------------------------------ 조회
def metros(g) -> dict:
    return g.__dict__.setdefault("metros", {})


def get(g, mid):
    return metros(g).get(mid) if mid is not None else None


def of(g, rid):
    rr = g.regions.get(rid)
    return get(g, getattr(rr, "metro", None)) if rr is not None else None


def members(g, rid) -> list:
    m = of(g, rid)
    return list(m["members"]) if m else [rid]


def center_of(g, rid) -> str:
    m = of(g, rid)
    return m["center"] if m else rid


def eligible(g, pool, rid) -> bool:
    info = g.info(rid)
    if pool == "fishery":
        return g.can_fish(rid)
    if pool == "coal":
        return info.is_coal
    if pool == "oil":
        return info.is_oil
    if pool == "specialty":
        return bool(info.specialty)
    return True


def pool_members(g, m, pool) -> list:
    return [r for r in m["members"] if eligible(g, pool, r)]


def pool_level(g, m, pool) -> int:
    """지을 수 있는 구성 지역들의 평균 단계(내림)."""
    el = pool_members(g, m, pool)
    if not el:
        return 0
    key = POOL_KEY[pool]
    return int(math.floor(sum(g.regions[r].b[key] for r in el) / len(el) + 1e-9))


def max_level(key) -> int:
    if key in C.METRO_L6_KEYS:
        return 6
    if key in C.PROD_BUILDINGS:
        return C.PROD_BUILDINGS[key]["max"]
    return C.DEF_BUILDINGS[key]["max"]


def pool_name(g, pool, level) -> str:
    """'광역 경작지 3단계 (농장)' 처럼. 6단계는 고유 이름."""
    key = POOL_KEY[pool]
    if key in C.PROD_LEVEL_NAMES and level >= 6:
        return C.PROD_LEVEL_NAMES[key][5]
    return f"{POOL_NAMES[pool]} {level}단계"


def def_mult(g, rid) -> float:
    """넓을수록 지키기 어렵다: 지역 n곳을 묶은 광역시는 방어력 ×(1 − 0.02(n − 1))."""
    m = of(g, rid)
    if not m:
        return 1.0
    return max(0.0, 1.0 - C.METRO_DEF_PER_REGION * (len(m["members"]) - 1))


def river_farm(g, rid) -> bool:
    """구성 지역 중 하나라도 하천 농장이면 광역시 농장 전체가 하천 농장."""
    return any(g.river_farm(r) for r in members(g, rid))


def fish_mult(g, fid, rid) -> float:
    """구성 지역 중 하나라도 바다 어장이면 광역시 어장 전체가 그 배수(가장 좋은 어장 기준)."""
    el = [r for r in members(g, rid) if g.can_fish(r)] or [rid]
    return max(g._fish_mult_one(fid, r) for r in el)


def label(g, rid) -> str:
    m = of(g, rid)
    return m["name"] if m else g.info(rid).name


def exchange_weight(g, fid) -> tuple:
    """증권거래소 수(광역시에 있으면 그 광역시 지역 수만큼)와 수도(또는 수도가 든 광역시)에 있는지."""
    cap = g.factions[fid].capital
    seen, n, cap_ok = set(), 0, False
    for r in g.regions_of(fid):
        if "exchange" not in r.econ:
            continue
        m = of(g, r.id)
        if m:
            if m["id"] in seen:
                continue
            seen.add(m["id"])
            n += len(m["members"])
            cap_ok = cap_ok or cap in m["members"]
        else:
            n += 1
            cap_ok = cap_ok or r.id == cap
    return n, cap_ok


# ------------------------------------------------------------------ 지정
def distances(g, center, k) -> dict:
    dist, frontier = {center: 0}, [center]
    for d in range(1, k + 1):
        nxt = []
        for u in frontier:
            for v in g.world.land_adj[u]:
                if v not in dist:
                    dist[v] = d
                    nxt.append(v)
        frontier = nxt
    return dist


def can_center(g, fid, rid) -> tuple:
    rr = g.regions.get(rid)
    if rr is None or rr.owner != fid:
        return False, "내 지역이 아닙니다."
    if getattr(rr, "metro", None) is not None:
        return False, "이미 광역시입니다."
    if rr.occ or g.resisting(rr):
        return False, "점령당하는 중이거나 저항 중인 지역입니다."
    return True, ""


def candidates(g, fid, center) -> list:
    """중심에서 육상 3칸(METRO_RANGE) 안의 내 지역(광역시가 아니고 점령당하는 중·저항 중이 아닌 곳). 중심이 맨 앞, 가까운 순."""
    dist = distances(g, center, C.METRO_RANGE)
    out = []
    for r, d in sorted(dist.items(), key=lambda x: (x[1], x[0])):
        rr = g.regions[r]
        if rr.owner == fid and getattr(rr, "metro", None) is None and not rr.occ and not g.resisting(rr):
            out.append(r)
    return out


def auto_pick(g, fid, center) -> list:
    """[모두]: 중심과 이어진 후보를 가까운 순(같은 거리면 인구 많은 순)으로 최대 25곳(중심 포함)."""
    cands = set(candidates(g, fid, center))
    out, seen, layer = [center], {center}, [center]
    while layer and len(out) < C.METRO_MAX_REGIONS:
        nxt = sorted({v for u in layer for v in g.world.land_adj[u] if v in cands and v not in seen},
                     key=lambda r: (-g.regions[r].pop, r))
        nxt = nxt[:C.METRO_MAX_REGIONS - len(out)]
        seen.update(nxt)
        out += nxt
        layer = nxt
    return out


def _connected(g, center, sel) -> bool:
    sel = set(sel)
    seen, stack = {center}, [center]
    while stack:
        u = stack.pop()
        for v in g.world.land_adj[u]:
            if v in sel and v not in seen:
                seen.add(v)
                stack.append(v)
    return seen == sel


def normalize(center, sel) -> list:
    return [center] + sorted(set(sel) - {center})


def check(g, fid, center, sel) -> tuple:
    """지정 조건 검사. (충족 여부, [(항목, 충족, 설명)])."""
    sel = normalize(center, sel)
    ok_c, why = can_center(g, fid, center)
    cand = set(candidates(g, fid, center)) if ok_c else set()
    bad = [r for r in sel if r not in cand]
    items = []
    n_max = C.METRO_MAX_REGIONS
    if not ok_c:
        desc = why
    elif bad:
        desc = f"고를 수 없는 지역: {', '.join(g.info(r).name for r in bad)}"
    elif len(sel) > n_max:
        desc = f"{len(sel)}곳 — {len(sel) - n_max}곳을 빼야 함"
    else:
        desc = f"{len(sel)}곳"
    items.append((f"구성 지역(2~{n_max}곳)", ok_c and 2 <= len(sel) <= n_max and not bad, desc))
    conn = _connected(g, center, sel)
    items.append(("서로 이어짐", conn, "중심과 육로로 이어진 지역만" if not conn else "이어짐"))
    regs = [g.regions[r] for r in sel]
    pop = sum(r.pop for r in regs)
    items.append(("인구 100만 이상", pop >= C.METRO_MIN_POP, f"{pop:,.1f}만"))
    fac = any(r.b["factory"] >= 5 for r in regs)
    bank = any(r.b["bank"] >= 5 for r in regs)
    items.append(("공업 단지(공장 5단계)", fac, "있음" if fac else "없음"))
    items.append(("금융 단지(은행 5단계)", bank, "있음" if bank else "없음"))
    prod = sum(g.food_prod(fid, r) for r in regs)
    cons = pop * C.FOOD_PER_POP
    items.append(("식량 생산 > 소비", prod > cons, f"{prod:,.1f} / {cons:,.1f}"))
    h = sum(r.happy for r in regs) / max(1, len(regs))
    items.append(("평균 행복도 0 이상", h >= 0, f"{h:+.1f}"))
    return all(it[1] for it in items), items


def feasible(g, fid, center) -> tuple:
    """이 지역을 중심으로 광역시를 지정할 길이 있는가(v1.2.24: 행동 탭 버튼 활성 여부). (가능 여부, [이유]).
    중심과 이어진 후보를 모두 고른 경우로 인구·공업 단지·금융 단지를 보고, 식량·행복도는 유리한 지역만
    골랐을 때도 못 채우면 불가능으로 본다(필요조건만 본다 — 실제 조합은 지정 화면에서 고른다)."""
    ok_c, why = can_center(g, fid, center)
    if not ok_c:
        return False, [why]
    cands = set(candidates(g, fid, center))
    comp, stack = {center}, [center]
    while stack:
        u = stack.pop()
        for v in g.world.land_adj[u]:
            if v in cands and v not in comp:
                comp.add(v)
                stack.append(v)
    reasons = []
    if len(comp) < 2:
        reasons.append(f"육상 {C.METRO_RANGE}칸 안에 함께 묶을 내 지역이 없습니다.")
    regs = [g.regions[r] for r in comp]
    # 인구: 최대 25곳까지만 묶으므로 인구가 많은 25곳(중심 포함)의 합으로 본다
    top = sorted((r.pop for r in regs if r.id != center), reverse=True)[:C.METRO_MAX_REGIONS - 1]
    pop = g.regions[center].pop + sum(top)
    if pop < C.METRO_MIN_POP:
        most = "모두" if len(regs) <= C.METRO_MAX_REGIONS else f"인구가 많은 {C.METRO_MAX_REGIONS}곳을"
        reasons.append(f"묶을 수 있는 지역을 {most} 합쳐도 인구 {pop:,.1f}만(100만 이상 필요).")
    if not any(r.b["factory"] >= 5 for r in regs):
        reasons.append("묶을 수 있는 지역에 공업 단지(공장 5단계)가 없습니다.")
    if not any(r.b["bank"] >= 5 for r in regs):
        reasons.append("묶을 수 있는 지역에 금융 단지(은행 5단계)가 없습니다.")
    surplus = {r.id: g.food_prod(fid, r) - r.pop * C.FOOD_PER_POP for r in regs}
    if surplus[center] + sum(max(0.0, v) for k, v in surplus.items() if k != center) <= 0:
        reasons.append("식량이 남는 지역만 골라도 식량 생산이 소비보다 적습니다.")
    happy = g.regions[center].happy + sum(max(0.0, r.happy) for r in regs if r.id != center)
    if happy < 0:
        reasons.append("행복도가 높은 지역만 골라도 평균 행복도가 0보다 낮습니다.")
    return not reasons, reasons


def default_name(g, fid, center) -> str:
    short = g.info(center).short
    return short + ("특별시" if g.factions[fid].capital == center else "광역시")


def full_name(g, fid, center, name) -> str:
    """플레이어가 '○○'만 써도 되고 '○○광역시'로 써도 된다. 비우면 중심 지역 이름."""
    name = (name or "").strip()
    if not name:
        return default_name(g, fid, center)
    suffix = "특별시" if g.factions[fid].capital == center else "광역시"
    if name.endswith("광역시") or name.endswith("특별시"):
        return name
    return name + suffix


def preview(g, center, sel) -> dict:
    """지정했을 때의 통합 단계 {통합 종류: (단계, 지역 수)} 와 유일 건물."""
    m = {"members": normalize(center, sel)}
    out = {}
    for pool, key in POOLS:
        el = pool_members(g, m, pool)
        if el:
            out[pool] = (pool_level(g, m, pool), len(el))
    singles = {k: any(g.regions[r].b[k] for r in m["members"]) for k in SINGLES}
    stopped = [r for r in m["members"] if g.regions[r].project is not None]
    return {"pools": out, "singles": singles, "stopped": stopped}


def create(g, fid, center, sel, name=None) -> tuple:
    ok, items = check(g, fid, center, sel)
    if not ok:
        return False, " · ".join(f"{k}: {d}" for k, o, d in items if not o)
    sel = normalize(center, sel)
    f = g.factions[fid]
    g.metro_seq = getattr(g, "metro_seq", 0) + 1
    mid = g.metro_seq
    m = {"id": mid, "owner": fid, "founder": fid, "center": center, "members": sel,
         "name": full_name(g, fid, center, name), "special": f.capital == center, "turn": g.turn,
         "pre": {r: {k: g.regions[r].b[k] for k in SNAP_KEYS} for r in sel}, "merge": {}}
    # 진행 중이던 작업은 모두 중단(일반 취소처럼 50% 환급, 다른 묶음 공사의 대상이면 그 지역만 빠진다)
    stopped = 0
    for r in sel:
        rr = g.regions[r]
        p = rr.project
        if p is None:
            continue
        stopped += 1
        if p.group is not None:
            f.money += g._line_group_drop(p, r) * C.PROJECT_REFUND
            rr.project = None
        else:
            g.cancel_project(fid, r)
    metros(g)[mid] = m
    for r in sel:
        g.regions[r].metro = mid
    for pool, key in POOLS:
        el = pool_members(g, m, pool)
        if not el:
            continue
        lv = pool_level(g, m, pool)
        m["merge"][pool] = lv
        for r in el:
            g.regions[r].b[key] = lv
    for k in SINGLES:
        if any(g.regions[r].b[k] for r in sel):
            for r in sel:
                if k != "port" or g.info(r).coastal:
                    g.regions[r].b[k] = 1
    # 행복도는 평균 하나로, 특산물 공급·징집 피로도 중심 기준으로 맞춘다
    regs = [g.regions[r] for r in sel]
    h = sum(r.happy for r in regs) / len(regs)
    hd = sum(r.h_delta for r in regs) / len(regs)
    c = g.regions[center]
    for r in regs:
        r.happy, r.h_delta = h, 0.0
        r.focus = r.pop_focus = False
    c.h_delta = hd
    sync(g, m)
    g.event("info", f"{f.name}: {m['name']} 지정 — {len(sel)}개 지역을 하나로"
            + (f" (진행 중이던 작업 {stopped}건 중단, 50% 환급)" if stopped else ""), region=center, fids=(fid,))
    return True, f"{m['name']} 지정 ({len(sel)}개 지역)"


def sync(g, m):
    """구성 지역의 행복도·특산물 공급·징집 기록을 중심에 맞춘다."""
    c = g.regions[m["center"]]
    for r in m["members"]:
        rr = g.regions[r]
        if rr is c:
            continue
        rr.happy = c.happy
        rr.supplied = set(c.supplied)
        rr.mil_hist = c.mil_hist
        rr.conscript = c.conscript


# ------------------------------------------------------------------ 해제
def shared_project(g, m):
    for r in m["members"]:
        p = g.regions[r].project
        if p is not None and p.metro == m["id"]:
            return p
    return None


def dissolve(g, mid, why="") -> bool:
    m = metros(g).pop(mid, None)
    if m is None:
        return False
    sel = [r for r in m["members"] if r in g.regions]
    center = m["center"]
    owner = g.regions[center].owner
    # 작업: 통합 건물은 이어서 지을 수 없어 취소(50% 환급), 나머지는 그 지역(site)에서 이어서
    p = shared_project(g, m)
    if p is not None:
        for r in sel:
            if g.regions[r].project is p:
                g.regions[r].project = None
        site = p.site if p.site in sel else center
        if p.pool is not None or g.regions[site].owner != owner:
            if owner != NEUTRAL:
                refund = p.paid * C.PROJECT_REFUND
                g.factions[owner].money += refund
        else:
            p.metro = None
            g.regions[site].project = p
    # 건물: 묶기 전 단계 + (지금 단계 − 묶은 시점 평균 단계), 0~최대 단계(6단계는 광역시 전용이라 5단계로)
    for pool, key in POOLS:
        base = m["merge"].get(pool)
        if base is None:
            continue
        top = (C.PROD_BUILDINGS if key in C.PROD_BUILDINGS else C.DEF_BUILDINGS)[key]["max"]
        for r in pool_members(g, m, pool):
            rr = g.regions[r]
            pre = m["pre"].get(r, {}).get(key, 0)
            rr.b[key] = max(0, min(top, pre + rr.b[key] - base))
    # 유일 건물: 중심에(항구는 중심이 내륙이면 인구가 가장 많은 해안 지역에)
    port_site = None
    for k in SINGLES:
        had = any(g.regions[r].b[k] for r in sel)
        for r in sel:
            g.regions[r].b[k] = 0
        if not had:
            continue
        site = center
        if k == "port" and not g.info(center).coastal:
            coast = [r for r in sel if g.info(r).coastal]
            site = max(coast, key=lambda r: (g.regions[r].pop, r)) if coast else None
        if site is not None:
            g.regions[site].b[k] = 1
            if k == "port":
                port_site = site
    # 부대: 주인의 육군·공군은 중심으로, 정박한 함대는 새 항구로
    if owner != NEUTRAL:
        for a in list(g.armies.values()):
            if a.owner != owner or a.loc not in sel:
                continue
            if a.domain() == "naval":
                if port_site is not None and a.loc != port_site:
                    a.loc = port_site
            elif a.loc != center:
                a.loc = center
                a.goto = None
                if a.order and a.order.get("type") == "move":
                    a.order = None
    for r in sel:
        g.regions[r].metro = None
    if owner != NEUTRAL:
        g.event("info", f"{m['name']} 지정 해제" + (f" — {why}" if why else ""), region=center, fids=(owner,))
    return True


# ------------------------------------------------------------------ 슬롯(작업)
def options(g, fid, mid) -> list:
    """광역시 슬롯에 넣을 수 있는 선택지. 각 선택지에 site(짓는 지역)·pool(통합 건물 종류)이 붙는다."""
    m = get(g, mid)
    if m is None:
        return []
    sel = m["members"]
    center = m["center"]
    cr = g.regions[center]
    mods = g.mods(fid)
    resisting = g.resisting(cr)
    frozen = g.order_frozen(fid)
    n = len(sel)
    opts = []

    def add(kind, key, name, cost, turns, ok=True, why="", level=0, border=None, oil=0, site=None, pool=None):
        turns = max(1, turns)
        if resisting:
            ok, why = False, "점령 저항 중"
        elif frozen and kind != "annex":
            ok, why = False, frozen
        opts.append({"kind": kind, "key": key, "name": name, "cost": cost, "turns": turns,
                     "per_turn": cost / turns, "ok": ok, "why": why, "level": level,
                     "border": border, "oil": oil, "site": site or center, "pool": pool})

    raw = {r: g.options(fid, r, raw=True) for r in sel}
    # 통합 건물: 한 단계 올리면 지을 수 있는 구성 지역 모두가 함께 오른다(비용 = 한 지역 비용 × 지역 수)
    for pool, key in POOLS:
        el = pool_members(g, m, pool)
        if not el:
            continue
        lv = pool_level(g, m, pool) + 1
        if lv > max_level(key):
            continue
        if key in C.PROD_BUILDINGS:
            cost = R.prod_building_cost(key, lv, any(g.info(r).power_site for r in el))
            if key == "factory":
                cost *= mods.mult("cost_factory")
            turns = g.build_time(fid, key, R.prod_building_turns(lv))
        else:
            cost = R.def_building_cost(key, lv)
            turns = g.build_time(fid, key, R.def_building_turns(lv))
        add("build", key, pool_name(g, pool, lv), cost * len(el), turns, level=lv, pool=pool)
    seen = set()
    for r in sel:
        for o in raw[r]:
            k, key = o["kind"], o["key"]
            if k == "build" and key == "specialty":
                continue                         # 특산물 시설은 통합 건물로(v1.2.27)
            if k == "build" and key == "line" and o["border"] not in sel:
                add(k, key, f"{g.info(r).short} {o['name']}", o["cost"], o["turns"], o["ok"], o["why"],
                    o["level"], border=o["border"], site=r)
            elif k == "annex" and ("annex", key) not in seen:
                seen.add(("annex", key))
                add(k, key, o["name"], o["cost"], o["turns"], o["ok"], o["why"], o["level"], site=r)
                opts[-1]["eff_turns"] = o.get("eff_turns", o["turns"])     # 구성 지역 수만큼 줄어든 턴
            elif k in ("science", "econ") and (k, key) not in seen:
                if k == "econ" and key == "exchange" and any("exchange" in g.regions[x].econ for x in sel):
                    continue                     # 증권거래소는 광역시에 하나
                seen.add((k, key))
                add(k, key, o["name"] + ("" if r == center else f" ({g.info(r).short})"), o["cost"], o["turns"],
                    o["ok"], o["why"], o["level"], site=r)
    # 유일 건물(항구·공항·사관학교): 광역시에 하나도 없을 때만. 항구는 해안 지역에
    for key, spec in C.SINGLE_BUILDINGS.items():
        if any(g.regions[r].b[key] for r in sel):
            continue
        site = center
        if key == "port":
            coast = [r for r in sel if g.info(r).coastal]
            if not coast:
                continue
            site = center if center in coast else max(coast, key=lambda r: (g.regions[r].pop, r))
        add("build", key, spec["name"], spec["cost"] * C.BUILD_COST_MULT * C.MONEY_SCALE,
            g.build_time(fid, key, spec["turns"]), level=1, site=site)
    # 군 유닛: 하나를 만들면 지역 수만큼 나온다(해군은 항구가 있는 해안 지역에서)
    port = next((r for r in sel if g.regions[r].b["port"] and g.info(r).coastal), None)
    for key in C.BUILD_UNITS:
        u = C.UNITS[key]
        site = center
        ok, why = True, ""
        if u["kind"] == "naval":
            if not any(g.info(r).coastal for r in sel):
                continue
            if port is None:
                ok, why = False, "항구 필요"
            else:
                site = port
        if ok and not g.can_pay_oil(fid, u["oil"]):
            ok, why = False, f"석유 {u['oil']} 필요(석탄 {u['oil'] * C.OIL_AS_COAL}로 대체 가능)"
        per = g.unit_cost(fid, site, key)
        add("unit", key, f"{u['name']} ×{n}", per * u["turns"], u["turns"], ok, why, oil=u["oil"], site=site)
    # 천도: 수도가 광역시 밖이면 중심으로
    if g.factions[fid].capital not in sel:
        o = next((o for o in raw[center] if o["kind"] == "capital"), None)
        if o:
            add("capital", "capital", o["name"], o["cost"], o["turns"], o["ok"], o["why"], site=center)
    return opts


def start(g, fid, mid, kind, key, border=None, site=None, pool=None) -> tuple:
    m = get(g, mid)
    if m is None:
        return False, "광역시가 없습니다."
    sel = m["members"]
    if any(g.regions[r].project is not None for r in sel):
        return False, "이 광역시 슬롯은 이미 사용 중입니다."
    if g.regions[m["center"]].owner != fid:
        return False, "내 광역시가 아닙니다."
    cands = [o for o in options(g, fid, mid) if o["kind"] == kind and o["key"] == key
             and (border is None or o["border"] == border) and (pool is None or o["pool"] == pool)]
    if site is not None and len(cands) > 1:
        cands = [o for o in cands if o["site"] == site] or cands
    if not cands:
        return False, "선택할 수 없는 항목입니다."
    o = cands[0]
    if not o["ok"]:
        return False, o["why"]
    f = g.factions[fid]
    c = g.regions[m["center"]]
    if kind == "unit":
        u = C.UNITS[key]
        if not g.can_pay_oil(fid, u["oil"]):
            return False, f"석유 {u['oil']} 필요"
        g.pay_oil(fid, u["oil"])
        c.h_delta += C.UNIT_START_HAPPY[u["weight"]]
    name = o["name"]
    if kind == "annex":
        name = f"편입: {g.info(key).name}"          # '공동 n곳' 은 바뀌므로 이름에 넣지 않는다
    p = Project(kind=kind, key=key, level=o["level"], turns=o["turns"], per_turn=o["per_turn"],
                border=o["border"], name=name)
    p.metro, p.site, p.pool = mid, o["site"], o["pool"]
    g.proj_counter = getattr(g, "proj_counter", 0) + 1
    p.priority = g.proj_counter
    for r in sel:
        rr = g.regions[r]
        rr.project = p
        if not f.is_ai:
            rr.focus = rr.pop_focus = False
    turns = g.project_left(m["center"]) if kind == "annex" else o["turns"]
    return True, f"{m['name']}: {name} 착수 ({turns}턴, 턴당 {o['per_turn']:,.0f})"


def complete(g, f, p):
    """광역시 작업 완료(_phase_projects 에서). 구성 지역의 슬롯을 비운다."""
    m = get(g, p.metro)
    for rr in g.regions.values():
        if rr.project is p:
            rr.project = None
    if m is None:
        site = g.regions.get(p.site)
        if site is not None and site.owner == f.id:
            g._complete_project(f, site, p)
        return
    sel = m["members"]
    site = p.site if p.site in sel else m["center"]
    name = m["name"]
    if p.kind == "build":
        if p.pool is not None:
            key = POOL_KEY[p.pool]
            for r in pool_members(g, m, p.pool):
                g.regions[r].b[key] = p.level
            g.event("complete", f"{name} {pool_name(g, p.pool, p.level)} 완공", region=m["center"], fids=(f.id,))
            if p.chain and p.level < max_level(key):
                ok, _ = start(g, f.id, m["id"], "build", key, pool=p.pool)
                if ok:
                    q = g.regions[m["center"]].project
                    q.chain, q.priority, q.pinned = True, p.priority, p.pinned
            return
        if p.key in SINGLES:
            for r in sel:
                if p.key != "port" or g.info(r).coastal:
                    g.regions[r].b[p.key] = 1
            g.event("complete", f"{name} {C.SINGLE_BUILDINGS[p.key]['name']} 완공", region=site, fids=(f.id,))
            return
        g._complete_project(f, g.regions[site], p)      # 방어선(예전 세이브의 지역별 특산물 시설도): 그 지역에
        return
    if p.kind == "unit":
        n = len(sel)
        g.deliver_units(f.id, site, p.key, n)
        g.event("complete", f"{name}에서 {C.UNITS[p.key]['name']} {n}개 생산 완료", region=site, fids=(f.id,))
        if getattr(p, "repeat", 0) > 0:
            ok, msg = start(g, f.id, m["id"], "unit", p.key)
            if ok:
                q = g.regions[m["center"]].project
                q.repeat, q.priority, q.pinned = p.repeat - 1, p.priority, p.pinned
            elif not f.is_ai:
                g.event("info", f"{name}: 연속 생산 중단(남은 {p.repeat}개) — {msg}", region=site, fids=(f.id,))
        return
    g._complete_project(f, g.regions[site], p)          # 과학·경제·천도: 그 지역에


def migrate(g):
    """예전 세이브(v1.2.26 이전): 특산물 시설이 지역별이던 광역시를 통합 건물로 맞춘다(불러올 때 한 번)."""
    for m in metros(g).values():
        if "specialty" in m["merge"] or m.get("spec_pooled"):
            continue
        m["spec_pooled"] = True
        el = pool_members(g, m, "specialty")
        if not el:
            continue
        for r in el:
            m["pre"].setdefault(r, {})["specialty"] = g.regions[r].b["specialty"]
        lv = pool_level(g, m, "specialty")
        m["merge"]["specialty"] = lv
        for r in el:
            g.regions[r].b["specialty"] = lv


# ------------------------------------------------------------------ 점령·정리
def after_capture(g, mid, new_owner):
    m = get(g, mid)
    if m is None:
        return
    m["owner"] = new_owner


def phase(g):
    """턴마다: 주인이 바뀐 광역시는 저항 기간이 끝나면 해제, 주인이 갈라졌거나 없어진 광역시는 해제."""
    for mid, m in list(metros(g).items()):
        sel = m["members"]
        owners = {g.regions[r].owner for r in sel if r in g.regions}
        if len(owners) != 1 or NEUTRAL in owners or not g.factions[next(iter(owners))].alive:
            dissolve(g, mid, "구성 지역의 주인이 달라짐")
            continue
        owner = next(iter(owners))
        m["owner"] = owner
        if owner != m["founder"] and not g.resisting(g.regions[m["center"]]):
            dissolve(g, mid, "점령 뒤 저항 기간이 끝남")
