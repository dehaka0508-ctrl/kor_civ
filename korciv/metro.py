"""광역시(v1.3.0): 중심 지역에서 육상 3칸 안의 내 지역들(최대 25곳)을 묶어 하나의 지역처럼 다룬다.

지도·소유·부대 위치는 지역 단위 그대로 두고, 그 위에 묶음을 얹는다.
- 슬롯 1개: 구성 지역 모두가 같은 작업(Project) 하나를 가리킨다.
- 방어 건물(방공호·대공포): 구성 지역들의 평균 단계(내림)를 모두에 적용하고 함께 올린다. 방어선만 지역마다 따로.
- 공항: 하나라도 있으면 광역시 전체에 있는 것으로.
- 행복도는 중심 값 하나(구성 지역은 같은 값), 특산물 배분·반란 판정도 한 지역처럼.
- 군 유닛은 하나를 생산하면 지역 수만큼 나온다. 공격받으면 광역시 안의 병력이 함께 방어하고(방어력 ×(1 − 0.02(n − 1))),
  점령되면 통째로 넘어간다(저항 기간이 끝나면 지정 해제).
- 광역 슬롯(v1.3.16): 구성 지역들의 기본·하천·해안 슬롯 카드를 합쳐 중심 지역에 '광역 슬롯'을 만든다.
  · 기본 슬롯은 늘 6칸. 건물 종류마다 레벨 합 ÷ 지역 수를 반올림(하나라도 있으면 최소 1), 평균이 5를 넘으면
    5단계 카드 하나 + (평균 − 5)를 반올림한 카드(칸이 남을 때만). 산출은 구성 지역 수만큼(카드 배수).
  · 하천 슬롯은 하천이 있는 구성 지역이 1곳이면 1칸, 2곳 이상이면 2칸, 산출은 하천이 있는 지역 수만큼.
  · 해안 슬롯도 같은 방식(바다가 있는 지역 수), 항구가 하나라도 있었으면 항구 칸을 따로 하나 더.
  · 기타 슬롯(댐·원전·특산물 시설·무료 항구)은 합치지 않고 지역마다 그대로.
  구성 지역 자신의 기본·하천·해안 카드는 묶는 동안 보관했다가, 해제하면 되돌린 뒤 묶은 뒤 바뀐 단계(광역 카드의
  레벨 합 변화)를 각 지역의 그 건물 카드에 더한다. 공항은 중심, 부대는 중심으로.
- 지도 다시 그리기(v1.3.18): 판의 지도 그래프(g.world)를 광역시가 처음부터 한 칸이었던 지도로 다시 만든다(world_view).
  부대·위인·집결지는 광역시 칸(중심)으로 모이고 방어선은 바깥 경계마다 하나로. 원래 지도는 g.base_world.
- 완전히 하나의 지역(v1.3.17): 산출·행정·과학·행복도 보정·인구 성장·지역 가치·위인 효과는 광역시 전체 한 번(중심 칸이
  대표), 폭격·파괴 공작·지진·침수·산불·작황 피해는 어느 구성 지역에 일어나도 광역시 전체에 한 번. 해제하면 다시 지역마다.
"""
from __future__ import annotations

import math

from . import config as C
from . import rules as R
from . import slots as S
from .state import NEUTRAL, Project

# (통합 종류, 건물 키): 슬롯을 쓰지 않는 방어 건물만 예전처럼 구성 지역끼리 평균 단계로 통합한다(슬롯 건물은 광역 슬롯)
POOLS = (("shelter", "shelter"), ("aa", "aa"))
MERGE_TYPES = ("base", "river", "coast")
MERGE_FIRST = ("admin", "edu", "academy", "extract")    # 기본 슬롯 6칸이 모자라면 먼저 넣는 건물
POOL_KEY = dict(POOLS)
SINGLES = ("port", "airport", "academy")
SPREAD_SINGLES = ("airport",)        # 광역시 전체로 퍼지는 유일 건물(슬롯 밖). 항구·사관학교는 슬롯 카드(v1.3.8)
SNAP_KEYS = ("shelter", "aa") + SINGLES
POOL_NAMES = {"admin": "광역시청", "edu": "연구 건물", "farm": "광역 경작지", "fishery": "광역 어장", "factory": "광역 공업 지구", "bank": "광역 시장 지구",
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


# ------------------------------------------------------------------ 하나의 지역(v1.3.17)
# 광역시는 지정한 뒤 모든 면에서 하나의 지역이다. 지도 칸(구성 지역)은 위치·이동·방어선 경계·영토 수에만 남고,
# 지역 단위의 상태·판정·산출은 중심 칸(hub)이 광역시 전체를 대신한다. 어느 구성 지역에 일어난 일(폭격·재해·
# 파괴 공작·침수·산불)도 광역시 전체에 한 번 일어난다. 해제하면 구성 지역마다 다시 따로(가역).
def hub(g, rid) -> str:
    """광역시면 중심(광역시 전체를 대신하는 칸), 아니면 그 지역."""
    return center_of(g, rid)


def is_extra(g, rid) -> bool:
    """광역시의 중심이 아닌 구성 지역: 지역 단위 산출·판정은 중심이 광역시 전체로 맡는다."""
    m = of(g, rid)
    return bool(m) and m["center"] != rid


def regions(g, rid) -> list:
    return [g.regions[r] for r in members(g, rid)]


def total_pop(g, rid) -> float:
    return sum(r.pop for r in regions(g, rid))


def total_area(g, rid) -> float:
    return sum(g.info(r).area_km2 for r in members(g, rid))


def outer_adj(g, rid) -> set:
    """광역시(하나의 지역)와 맞닿은 바깥 지역."""
    sel = set(members(g, rid))
    w = base_world(g)
    return {n for r in sel for n in w.land_adj[r]} - sel


def damage_choices(g, rid, keys=None, lines=True) -> list:
    """하나의 지역으로 본 광역시(아니면 그 지역)의 피해 대상 [(칸, 'b'|'lines', 키)].
    슬롯 카드는 그 카드가 있는 칸(광역 슬롯은 중심, 기타 슬롯은 그 구성 지역), 방공호·대공포·공항처럼
    광역시 전체에 같은 값인 슬롯 밖 건물은 한 번만, 방어선은 바깥 경계만."""
    sel = members(g, rid)
    out, shared = [], set()
    for x in sel:
        r = g.regions[x]
        for k, v in r.b.items():
            if v <= 0 or (keys is not None and k not in keys):
                continue
            if k in S.CARD_KEYS or len(sel) == 1:
                out.append((x, "b", k))
            elif k not in shared:
                shared.add(k)
                out.append((sel[0], "b", k))
        if lines:
            out += [(x, "lines", k) for k, v in sorted(r.lines.items()) if v > 0 and k not in sel]
    return out


def apply_damage(g, x, kind, key, levels=1) -> tuple:
    """damage_choices 의 한 대상을 levels 단계 깎는다(광역시 전체에 같은 값인 건물은 모든 구성 지역을). (전, 후)"""
    r = g.regions[x]
    if kind == "lines":
        before = r.lines.get(key, 0)
        r.lines[key] = max(0, before - levels)
        return before, r.lines[key]
    before = r.b.get(key, 0)
    after = max(0, before - levels)
    if key in S.CARD_KEYS or not of(g, x):
        r.b[key] = after
    else:
        for y in members(g, x):
            g.regions[y].b[key] = after
    return before, after


# ------------------------------------------------------------------ 지도 다시 그리기(v1.3.18)
# 광역시를 지정하면 판의 지도 그래프를 '광역시가 처음부터 한 칸이었던 지도'로 다시 만든다(g.world). 중심 칸이 광역시
# 전체를 대신하는 칸이 되고(바깥 이웃·맞닿은 해역·경계 지형을 모두 가짐), 나머지 구성 지역 칸은 그래프에서 빠진다.
# 그래서 이동·공격·경로·상륙·시야·AI 판단이 모두 광역시를 한 지역으로 본다. 원래 지도는 g.base_world.
def base_world(g):
    return g.__dict__.get("base_world") or g.world


def node(g, rid):
    """지도 그래프의 칸: 광역시 구성 지역이면 중심(광역시 칸), 아니면 그대로(해역 포함)."""
    return center_of(g, rid) if rid is not None else rid


def _terrain_pick(ts):
    """합쳐진 경계의 지형: 구간이 가장 많은 지형(같으면 지키는 쪽에 유리한 것)."""
    count = {}
    for t in ts:
        k = None if t is None else (t["kind"], t.get("name"))
        n, best = count.get(k, (0, t))
        count[k] = (n + 1, best)
    pick = max(count.values(), key=lambda v: (v[0], -(v[1]["mult"] if v[1] else 1.0)))
    return pick[1]


def world_view(g):
    """광역시를 한 칸으로 합친 지도(광역시가 없으면 원래 지도)."""
    import dataclasses
    base = base_world(g)
    ms = [m for m in metros(g).values() if m.get("members") and all(r in base.regions for r in m["members"])]
    if not ms:
        return base
    hubs = {r: m["center"] for m in ms for r in m["members"]}
    groups = {m["center"]: list(m["members"]) for m in ms}

    def N(x):
        return hubs.get(x, x)
    v = object.__new__(type(base))
    v.__dict__.update(base.__dict__)
    v.__dict__.pop("_air_cache", None)
    v.base, v.hub_of = base, hubs
    adj = {}
    for rid, ns in base.land_adj.items():
        h = hubs.get(rid)
        if h is None:
            adj[rid] = {N(n) for n in ns}
        elif h == rid:
            adj[rid] = {N(n) for r in groups[rid] for n in base.land_adj[r]} - {rid}
        else:
            adj[rid] = set()                          # 광역시 중심이 아닌 구성 지역 칸: 그래프에서 빠짐
    v.land_adj = adj
    regs = dict(base.regions)
    for h, sel in groups.items():
        seas = []
        for r in sel:
            seas += [s for s in base.regions[r].seas if s not in seas]
        regs[h] = dataclasses.replace(base.regions[h], seas=tuple(seas), coastal=bool(seas))
        for r in sel:
            if r != h and base.regions[r].seas:
                regs[r] = dataclasses.replace(base.regions[r], seas=())
    v.regions = regs
    seas = dict(base.seas)
    for s in {s for sel in groups.values() for r in sel for s in base.regions[r].seas}:
        coast = []
        for c in base.seas[s].coast:
            if N(c) not in coast:
                coast.append(N(c))
        seas[s] = dataclasses.replace(base.seas[s], coast=coast)
    v.seas = seas
    links = {}
    for a in hubs:
        for b in base.land_adj[a]:
            if N(a) != N(b):
                links.setdefault(frozenset((N(a), N(b))), set()).add(frozenset((a, b)))
    terrain = {k: t for k, t in base.terrain.items() if not (k & hubs.keys())}
    bridges = {k: b for k, b in base.bridges.items() if not (k & hubs.keys())}
    for key, ls in links.items():
        ls = sorted(ls, key=sorted)
        t = _terrain_pick([base.terrain.get(x) for x in ls])
        if t is not None:
            terrain[key] = t
        names = [base.bridges.get(x) for x in ls]
        if all(names):
            bridges[key] = names[0]
    v.terrain, v.bridges = terrain, bridges
    v.river_regions = set(base.river_regions) | {h for h, sel in groups.items() if any(r in base.river_regions for r in sel)}
    v.mountain_regions = set(base.mountain_regions) | {h for h, sel in groups.items()
                                                       if any(r in base.mountain_regions for r in sel)}
    v.outer_rivers = set(base.outer_rivers) | {h for h, sel in groups.items() if any(r in base.outer_rivers for r in sel)}
    return v


def refresh_world(g):
    """광역시를 지정·해제하거나 불러온 뒤 지도 그래프를 다시 만든다."""
    if "base_world" not in g.__dict__:
        g.base_world = g.world
    g.world = world_view(g)
    for k in ("_near_cap", "_visible"):
        if isinstance(g.__dict__.get(k), dict):
            g.__dict__[k].clear()


def _gather(g, m):
    """지정: 구성 지역 칸의 부대·위인·집결지·이동 계획을 광역시 칸(중심)으로."""
    sel, center = set(m["members"]), m["center"]
    for a in g.armies.values():
        if a.loc in sel and a.loc != center:
            a.loc = center
        o = a.order or {}
        if o.get("target") in sel or any(x in sel for x in o.get("path", ())):
            a.order = None
        if a.goto in sel:
            a.goto = center if a.loc != center else None
    for gp in getattr(g, "great_people", []):
        if gp.get("loc") in sel:
            gp["loc"] = center
    for rr in g.regions.values():
        if getattr(rr, "rally", None) in sel:
            rr.rally = center
    for f in g.factions:
        if getattr(f, "rally", None) in sel:
            f.rally = center


def _merge_lines(g, m):
    """지정: 방어선을 광역시의 바깥 경계(이웃 지역·해안선)마다 하나로(가장 높은 단계). 해제 때 되돌린다."""
    sel = m["members"]
    m["pre_lines"] = {r: dict(g.regions[r].lines) for r in sel}
    merged = {}
    for r in sel:
        for k, lv in g.regions[r].lines.items():
            if k not in sel:
                merged[k] = max(merged.get(k, 0), lv)
    for r in sel:
        g.regions[r].lines = {}
    g.regions[m["center"]].lines = dict(merged)
    m["merged_lines"] = dict(merged)


def _split_lines(g, m):
    """해제: 구성 지역마다 묶기 전 방어선 + (광역시 경계의 지금 단계 − 묶은 시점 단계)."""
    sel = [r for r in m["members"] if r in g.regions]
    pre = m.get("pre_lines")
    if pre is None:
        return
    now = dict(g.regions[m["center"]].lines)
    base = m.get("merged_lines", {})
    top = C.DEF_BUILDINGS["line"]["max"]
    for r in sel:
        lines = dict(pre.get(r, {}))
        for k in list(lines):
            if k not in m["members"]:
                lines[k] = max(0, min(top, lines[k] + now.get(k, 0) - base.get(k, 0)))
        for k, lv in now.items():                    # 묶은 뒤 새로 지은 경계
            if k not in lines and base.get(k, 0) == 0 and lv > 0 and k in (
                    base_world(g).land_adj[r] if k != "coast" else (("coast",) if base_world(g).regions[r].coastal else ())):
                lines[k] = lv
        g.regions[r].lines = {k: v for k, v in lines.items() if v > 0}


def merged(g, rid):
    """구성 지역 슬롯을 합친 광역시(v1.3.16)면 그 광역시, 아니면 None."""
    m = of(g, rid)
    return m if m and m.get("slot_merge") else None


def is_merged_center(g, rid) -> bool:
    m = merged(g, rid)
    return bool(m) and m["center"] == rid


def group(g, m, stype) -> list:
    """그 종류 슬롯을 가진(묶기 전) 구성 지역."""
    pre = m.get("pre_slots", {})
    return [r for r in m["members"] if pre.get(r, {}).get(stype)]


def slot_regions(g, rid, stype) -> list:
    """그 칸의 카드가 대표하는 지역들: 광역 슬롯이면 그 슬롯을 가진 구성 지역, 아니면 그 지역 하나."""
    m = merged(g, rid)
    if m and rid == m["center"] and stype in MERGE_TYPES:
        return group(g, m, stype) or [rid]
    return [rid]


def extract_res(g, rid) -> tuple:
    """채굴 카드를 지을 수 있는 자원 ("oil", "coal"). 광역 슬롯 중심이면 구성 지역 전체의 자원."""
    sites = slot_regions(g, rid, "base")
    return tuple(k for k in ("oil", "coal") if any(getattr(g.info(r), "is_" + k) for r in sites))


def extract_levels(g, rid, res) -> list:
    """그 자원으로 나오는 채굴 카드 단계(배수만큼 되풀이). 광역 채굴 카드는 유전·탄전 구성 지역 수 비율로 나눈다."""
    b = g.regions[rid].b
    lv = b.levels("extract") if hasattr(b, "levels") else [b.get("extract", 0)]
    m = merged(g, rid)
    if not m or rid != m["center"]:
        return lv
    oil = sum(1 for r in m["members"] if g.info(r).is_oil)
    coal = sum(1 for r in m["members"] if g.info(r).is_coal)
    if not oil + coal:
        return []
    k = S.round_half_up(len(lv) * oil / (oil + coal))
    return lv[:k] if res == "oil" else lv[k:]


# ------------------------------------------------------------------ 광역 슬롯(v1.3.16)
def _sums(slots) -> dict:
    """{(슬롯 종류, 건물 키): 카드 레벨 합}(배수 없이)."""
    out = {}
    for t in MERGE_TYPES:
        for c in slots.get(t, []):
            if c:
                out[(t, c["key"])] = out.get((t, c["key"]), 0) + c["level"]
    return out


def merge_plan(g, sel) -> dict:
    """구성 지역들의 기본·하천·해안 카드를 합친 광역 슬롯(지정 미리보기와 지정에 함께 쓴다).
    {"slots": {종류: [카드 또는 None]}, "mult": {종류: 그 슬롯을 가진 지역 수}}"""
    bs = {r: g.regions[r].b for r in sel}
    groups = {"base": list(sel),
              "river": [r for r in sel if bs[r].slots.get("river")],
              "coast": [r for r in sel if bs[r].slots.get("coast")]}
    slots, mult = {}, {}
    for t in MERGE_TYPES:
        el = groups[t]
        n = len(el)
        size = S.BASE_SLOT_MAX if t == "base" else min(2, n)
        tot, port = {}, False
        for r in el:
            for c in bs[r].slots.get(t, []):
                if not c:
                    continue
                if t == "coast" and c["key"] == "port":
                    port = True
                    continue
                tot[c["key"]] = tot.get(c["key"], 0) + c["level"]
        lists = {k: S.split_average(v, n) for k, v in tot.items()}
        main = sorted(lists, key=lambda k: ((0, MERGE_FIRST.index(k), 0, "") if k in MERGE_FIRST
                                            else (1, -lists[k][0], -tot[k], k)))
        cards = [{"key": k, "level": lists[k][0]} for k in main]
        extra = sorted(((k, lv) for k in main for lv in lists[k][1:]), key=lambda kv: (-kv[1], kv[0]))
        cards += [{"key": k, "level": lv} for k, lv in extra]
        row = cards[:size] + [None] * max(0, size - len(cards))
        if t == "coast" and port:
            row.append({"key": "port", "level": 1})        # 항구가 하나라도 있었으면 항구 칸을 따로
        slots[t] = row
        mult[t] = max(1, n)
    return {"slots": slots, "mult": mult}


def merge(g, m):
    """광역시 지정·예전 세이브: 구성 지역 카드를 보관하고 중심에 광역 슬롯을 만든다."""
    sel = m["members"]
    plan = merge_plan(g, sel)
    m["pre_slots"] = {r: {t: [dict(c) if c else None for c in g.regions[r].b.slots.get(t, [])] for t in MERGE_TYPES}
                      for r in sel}
    for r in sel:
        b = g.regions[r].b
        for t in MERGE_TYPES:
            b.slots[t] = []
        b.__dict__.pop("xmult", None)
        b.resync()
    cb = g.regions[m["center"]].b
    for t in MERGE_TYPES:
        cb.slots[t] = [dict(c) if c else None for c in plan["slots"][t]]
    cb.xmult = dict(plan["mult"])
    cb.resync()
    m["merged"] = _sums(cb.slots)
    m["slot_merge"] = True


def unmerge(g, m):
    """해제: 보관한 카드를 되돌리고, 묶은 뒤 광역 카드의 레벨 합이 바뀐 만큼 각 지역의 그 건물 카드에 더한다
    (예전 '묶기 전 단계 + (지금 단계 − 묶은 시점 단계)'와 같은 규칙. 없던 건물은 빈 칸에 새로)."""
    sel = [r for r in m["members"] if r in g.regions]
    center = m["center"]
    cb = g.regions[center].b
    now = _sums(cb.slots)
    base = m.get("merged", {})
    pre = m.get("pre_slots", {})
    for r in sel:
        b = g.regions[r].b
        if r in pre:
            for t in MERGE_TYPES:
                b.slots[t] = [dict(c) if c else None for c in pre[r][t]]
        b.__dict__.pop("xmult", None)
        b.resync()
    for (t, k), d in sorted({tk: now.get(tk, 0) - base.get(tk, 0) for tk in set(now) | set(base)}.items()):
        if not d or k == "port":
            continue
        top = C.PROD_BUILDINGS[k]["max"] if k in C.PROD_BUILDINGS else S.max_level(k)
        for r in sel:
            b = g.regions[r].b
            if not b.slots.get(t) or (k == "extract" and not (g.info(r).is_oil or g.info(r).is_coal)):
                continue
            pos = max(((tt, i) for tt, i, c in b.cards(k) if tt == t), key=lambda p: b.card(p)["level"], default=None)
            if pos is not None:
                b.set_card(pos, max(0, min(top, b.card(pos)["level"] + d)))
            elif d > 0 and b.empty(t) and not (k in S.UNIQUE_KEYS and b.count(k)) and (k != "academy" or r == center):
                b.place(k, min(top, d), (t, b.empty(t)[0]))     # 없던 건물은 빈 칸에 새로(사관학교는 중심에만)
    had, has = base.get(("coast", "port"), 0) > 0, now.get(("coast", "port"), 0) > 0
    coast = [r for r in sel if g.regions[r].b.slots.get("coast")]
    if has and coast and not any(g.regions[r].b.get("port") for r in sel):
        site = center if center in coast else max(coast, key=lambda r: (g.regions[r].pop, r))
        b = g.regions[site].b
        if b.empty("coast"):
            b.place("port", 1, ("coast", b.empty("coast")[0]))
    elif had and not has:                                   # 광역 항구가 부서졌다
        for r in coast:
            b = g.regions[r].b
            for tt, i, c in list(b.cards("port")):
                if tt == "coast":
                    b.remove((tt, i))


def pool_level(g, m, pool) -> int:
    """지을 수 있는 구성 지역들의 평균 단계(내림)."""
    el = pool_members(g, m, pool)
    if not el or pool not in POOL_KEY:          # 예전 통합 건물 종류(v1.3.16부터 광역 슬롯 카드)
        return 0
    key = POOL_KEY[pool]
    return int(math.floor(sum(g.regions[r].b[key] for r in el) / len(el) + 1e-9))


def slot_site(g, rid, stype) -> str:
    """그 슬롯 카드가 있는 지역: 광역시의 기본·하천·해안 슬롯은 중심, 기타 슬롯은 그 지역."""
    m = of(g, rid)
    return m["center"] if m and stype in MERGE_TYPES else rid


def max_level(key) -> int:
    if key in C.SITE_POWER:
        return 3
    if key in C.SINGLE_BUILDINGS:
        return 1
    if key in C.METRO_L6_KEYS:
        return 6
    if key in C.PROD_BUILDINGS:
        return C.PROD_BUILDINGS[key]["max"]
    return C.DEF_BUILDINGS[key]["max"]


def pool_name(g, pool, level) -> str:
    """'광역 경작지 3단계 (농장)' 처럼. 6단계는 고유 이름."""
    key = POOL_KEY[pool]
    if key == "admin":
        return "정부청사" if level == 5 else f"{level}단계 광역시청"
    if key == "edu":
        return "거점국립대학" if level == 4 else C.PROD_LEVEL_NAMES[key][max(0, level - 1)]
    if key in C.PROD_LEVEL_NAMES and level >= 6:
        return C.PROD_LEVEL_NAMES[key][5]
    return f"{POOL_NAMES[pool]} {level}단계"


def def_mult(g, rid) -> float:
    """넓을수록 지키기 어렵다: 지역 n곳을 묶은 광역시는 방어력 ×(1 − 0.02(n − 1))."""
    m = of(g, rid)
    if not m or g.mods(g.regions[rid].owner).value("metro_def_exempt"):
        return 1.0
    return max(0.0, 1.0 - C.METRO_DEF_PER_REGION * (len(m["members"]) - 1))


def label(g, rid) -> str:
    m = of(g, rid)
    return m["name"] if m else g.info(rid).name


def exchange_weight(g, fid) -> tuple:
    """증권거래소 수(광역시에 있으면 그 광역시 지역 수만큼)와 수도(또는 수도가 든 광역시)에 있는지."""
    cap = g.factions[fid].capital
    seen, n, cap_ok = set(), 0, False
    for r in g.regions_of(fid):
        if "exchange" not in r.econ or g.facility_paused(r.id):
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
    required_pop = C.METRO_MIN_POP * g.mods(fid).value("metro_pop_mult", 1)
    items.append((f"인구 {required_pop:g}만 이상", pop >= required_pop, f"{pop:,.1f}만"))
    fac = any(r.b["factory"] >= 5 for r in regs)
    bank = any(r.b["bank"] >= 5 for r in regs)
    items.append(("공업 단지(공장 5단계)", fac, "있음" if fac else "없음"))
    items.append(("복합 무역 센터(시장 5단계)", bank, "있음" if bank else "없음"))
    admin = g.regions[center].b.get("admin", 0)
    items.append(("중심 지역 시청 이상", admin >= 3, f"행정 {admin}단계"))
    prod = sum(g.admin_output(r.id) for r in regs)
    cons = sum(g.admin_consumption(r.id) for r in regs)
    national_prod, national_cons = g.admin_balance(fid)
    items.append(("구성 지역 행정력 흑자", prod > cons, f"{prod:,.1f} / {cons:,.1f}"))
    items.append(("국가 행정력 흑자", national_prod > national_cons, f"{national_prod:,.1f} / {national_cons:,.1f}"))
    h = sum(r.happy for r in regs) / max(1, len(regs))
    items.append(("평균 행복도 0 이상", h >= 0, f"{h:+.1f}"))
    return all(it[1] for it in items), items


def feasible(g, fid, center) -> tuple:
    """이 지역을 중심으로 광역시를 지정할 길이 있는가(v1.3.0: 행동 탭 버튼 활성 여부). (가능 여부, [이유]).
    중심과 이어진 후보를 모두 고른 경우로 인구·공업 단지·복합 무역 센터를 보고, 식량·행복도는 유리한 지역만
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
        reasons.append("묶을 수 있는 지역에 복합 무역 센터(시장 5단계)가 없습니다.")
    if g.regions[center].b.get("admin", 0) < 3:
        reasons.append("중심 지역에 시청(행정 3단계)이 필요합니다.")
    surplus = {r.id: g.admin_output(r.id) - g.admin_consumption(r.id) for r in regs}
    if surplus[center] + sum(max(0.0, v) for k, v in surplus.items() if k != center) <= 0:
        reasons.append("행정력이 남는 지역만 골라도 행정력 생산이 소비보다 적습니다.")
    prod, cons = g.admin_balance(fid)
    if prod <= cons:
        reasons.append("국가 전체 행정력 흑자가 필요합니다.")
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
    """지정했을 때의 광역 슬롯(merge_plan), 방어 건물 통합 단계 {통합 종류: (단계, 지역 수)}, 유일 건물, 멈출 작업."""
    m = {"members": normalize(center, sel)}
    out = {}
    for pool, key in POOLS:
        el = pool_members(g, m, pool)
        if el:
            out[pool] = (pool_level(g, m, pool), len(el))
    singles = {k: any(g.regions[r].b[k] for r in m["members"]) for k in SINGLES}
    stopped = [r for r in m["members"] if g.regions[r].project is not None]
    return {"plan": merge_plan(g, m["members"]), "pools": out, "singles": singles, "stopped": stopped}


def card_short(g, center, key, stype) -> str:
    if key == "fishery":
        return "하천 어장" if stype == "river" else "바다 어장"
    if key == "power":
        return "화력발전소"
    if key == "extract":
        return "채굴 시설"
    from .state import BUILDING_NAMES
    return BUILDING_NAMES.get(key, key)


def plan_lines(g, center, plan) -> list:
    """광역 슬롯 구성 글줄: ['기본 6칸 ×4: 행정 3 · 농장 1 · …', …]."""
    out = []
    for t in MERGE_TYPES:
        row = plan["slots"].get(t, [])
        if not row:
            continue
        cards = [f"{card_short(g, center, c['key'], t)} {c['level']}" for c in row if c]
        empty = sum(1 for c in row if c is None)
        txt = " · ".join(cards) + (f" · 빈 칸 {empty}" if empty else "") if cards else f"빈 칸 {empty}"
        out.append(f"{S.SLOT_NAMES[t]} {len(row)}칸 ×{plan['mult'].get(t, 1)}: {txt}")
    return out


def create(g, fid, center, sel, name=None) -> tuple:
    ok, items = check(g, fid, center, sel)
    if not ok:
        return False, " · ".join(f"{k}: {d}" for k, o, d in items if not o)
    sel = normalize(center, sel)
    f = g.factions[fid]
    g.metro_seq = getattr(g, "metro_seq", 0) + 1
    mid = g.metro_seq
    m = {"id": mid, "owner": fid, "founder": fid, "center": center, "members": sel,
         "name": full_name(g, fid, center, name), "special": f.capital in sel, "turn": g.turn,
         "pre": {r: {k: g.regions[r].b[k] for k in SNAP_KEYS} for r in sel}, "merge": {}}
    for rid in sel:
        rr = g.regions[rid]
        f.money += sum(p.paid * C.PROJECT_REFUND for p in rr.queue)
        rr.queue.clear()
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
    for k in SPREAD_SINGLES:
        if any(g.regions[r].b[k] for r in sel):
            for r in sel:
                g.regions[r].b[k] = 1
    merge(g, m)                      # 광역 슬롯(v1.3.16): 구성 지역의 기본·하천·해안 카드를 중심에 합친다
    _gather(g, m)                    # 지도 다시 그리기(v1.3.18): 부대·위인·집결지는 광역시 칸(중심)으로
    _merge_lines(g, m)
    m["map_merged"] = True
    refresh_world(g)
    # 행복도는 평균 하나로, 특산물 공급·징집 피로도 중심 기준으로 맞춘다
    regs = [g.regions[r] for r in sel]
    h = sum(r.happy for r in regs) / len(regs)
    hd = sum(r.h_delta for r in regs) / len(regs)
    c = g.regions[center]
    for r in regs:
        r.happy, r.h_delta = h, 0.0
        r.focus = r.pop_focus = False
    c.h_delta = hd
    # 하나의 지역: 구성 지역 하나라도 침수면 광역시 전체가 침수, 지진·시설 정지는 가장 긴 것으로
    c.flooded = any(r.flooded for r in regs)
    c.quake_until = max(r.quake_until for r in regs)
    c.facility_off_until = max(getattr(r, "facility_off_until", 0) for r in regs)
    c.fire_scar = max(r.fire_scar for r in regs)
    c.last_agri_damage = max(r.last_agri_damage for r in regs)
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
        # 하나의 지역(v1.3.17): 생산·인구 집중, 침수·지진 피해, 시설 정지도 광역시 전체가 같은 상태
        rr.focus, rr.pop_focus = c.focus, c.pop_focus
        rr.focus_unrest_until = c.focus_unrest_until
        rr.flooded = c.flooded
        rr.quake_until = c.quake_until
        rr.facility_off_until = c.facility_off_until
        rr.famine = c.famine


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
    for q in g.regions[center].queue:
        if owner != NEUTRAL:
            g.factions[owner].money += q.paid * C.PROJECT_REFUND
    g.regions[center].queue.clear()
    p = shared_project(g, m)
    if p is not None:
        for r in sel:
            if g.regions[r].project is p:
                g.regions[r].project = None
        site = p.site if p.site in sel else center
        merged_slot = bool(getattr(p, "slot", None)) and p.slot[0] in MERGE_TYPES and m.get("slot_merge")
        if p.pool is not None or merged_slot or g.regions[site].owner != owner:
            if owner != NEUTRAL:
                refund = p.paid * C.PROJECT_REFUND
                g.factions[owner].money += refund
        else:
            p.metro = None
            g.regions[site].project = p
    # 방어 건물: 묶기 전 단계 + (지금 단계 − 묶은 시점 평균 단계), 0~최대 단계
    for pool, key in POOLS:
        base = m["merge"].get(pool)
        if base is None:
            continue
        top = (C.PROD_BUILDINGS if key in C.PROD_BUILDINGS else C.DEF_BUILDINGS)[key]["max"]
        for r in pool_members(g, m, pool):
            rr = g.regions[r]
            pre = m["pre"].get(r, {}).get(key, 0)
            rr.b[key] = max(0, min(top, pre + rr.b[key] - base))
    # 슬롯 카드: 보관한 카드로 되돌리고 묶은 뒤 바뀐 단계를 더한다(6단계는 광역시 전용이라 5단계로)
    if m.get("slot_merge"):
        unmerge(g, m)
    # 공항: 중심에. 항구는 해안 구성 지역에(unmerge)
    for k in SPREAD_SINGLES:
        had = any(g.regions[r].b[k] for r in sel)
        for r in sel:
            g.regions[r].b[k] = 0
        if had:
            g.regions[center].b[k] = 1
    ports = [r for r in sel if g.regions[r].b.get("port")]
    port_site = (center if center in ports else max(ports, key=lambda r: (g.regions[r].pop, r))) if ports else None
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
        rr = g.regions[r]
        if rr.owner != NEUTRAL and g.factions[rr.owner].capital != r:
            for key in ("admin", "edu"):
                rr.b[key] = min(4, rr.b.get(key, 0))
    if m.get("map_merged"):
        _split_lines(g, m)                   # 지도: 구성 지역마다 다시 칸으로
    refresh_world(g)
    for a in list(g.armies.values()):        # 항구 없는 칸에 남은 함대는 가까운 항구로
        if a.loc in sel and a.domain() == "naval" and not g.has_port(a.loc):
            g.teleport_home(a)
    if owner != NEUTRAL:
        g.event("info", f"{m['name']} 지정 해제" + (f" — {why}" if why else ""), region=center, fids=(owner,))
    return True


# ------------------------------------------------------------------ 슬롯(작업)
def options(g, fid, mid) -> list:
    """광역시 슬롯에 넣을 수 있는 선택지. 각 선택지에 site(짓는 지역)가 붙고, 광역 슬롯 카드는 mult(산출 배수),
    방공호·대공포 통합은 pool 이 붙는다."""
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

    def add(kind, key, name, cost, turns, ok=True, why="", level=0, border=None, oil=0, site=None, pool=None, slot=None):
        turns = max(1, turns)
        if resisting:
            ok, why = False, "점령 저항 중"
        elif frozen and kind != "annex":
            ok, why = False, frozen
        opts.append({"kind": kind, "key": key, "name": name, "cost": cost, "turns": turns,
                     "per_turn": cost / turns, "ok": ok, "why": why, "level": level,
                     "border": border, "oil": oil, "site": site or center, "pool": pool, "slot": slot})

    raw = {r: g.options(fid, r, raw=True) for r in sel}
    cb = cr.b
    # 광역 슬롯(v1.3.16): 중심의 기본·하천·해안 카드는 비용 = 한 지역 비용 × 그 슬롯을 가진 지역 수.
    # 기타 슬롯(댐·원전·특산물)은 지역마다 따로
    for r in sel:
        for o in raw[r]:
            slot = o.get("slot")
            if o["kind"] != "build" or not slot:
                continue
            merged_t = slot[0] in MERGE_TYPES and m.get("slot_merge")
            if merged_t and r != center:
                continue
            # 항구·사관학교는 산출이 없는 유일 건물이라 한 곳 비용 그대로
            mult = cb.mult_of(slot[0]) if merged_t and o["key"] not in C.SINGLE_BUILDINGS else 1
            add("build", o["key"], o["name"] if r == center else f"{g.info(r).short} {o['name']}", o["cost"] * mult,
                o["turns"], o["ok"], o["why"], o["level"], site=r, slot=slot)
            if mult > 1:
                opts[-1]["mult"] = mult
    # 방어 건물 통합: 한 단계 올리면 구성 지역 모두가 함께 오른다(비용 = 한 지역 비용 × 지역 수)
    for pool, key in POOLS:
        el = pool_members(g, m, pool)
        if not el:
            continue
        planned = [pool_level(g, m, pool)]
        projects = g.local_projects(center) if not getattr(g, '_continuing', False) else (
            [cr.project] if cr.project else [])
        for p in projects:
            if p.kind == 'build' and p.pool == pool:
                planned.append(max_level(key) if p.chain else p.level)
        lv = max(planned) + 1
        if lv > max_level(key):
            continue
        if key in C.PROD_BUILDINGS:
            cost = R.prod_building_cost(key, lv, any(g.info(r).power_site for r in el))
            cost *= g.building_cost_mult(fid, key, lv)
            turns = g.build_time(fid, key, R.prod_building_turns(lv), center, lv)
        else:
            cost = R.def_building_cost(key, lv) * g.building_cost_mult(fid, key, lv)
            turns = g.build_time(fid, key, R.def_building_turns(lv), center, lv)
        ok, why = g.building_allowed(fid, center, key, lv, pool=pool)
        add("build", key, pool_name(g, pool, lv), cost * len(el), turns, ok, why, level=lv, pool=pool)
    seen = set()
    for r in sel:
        for o in raw[r]:
            k, key = o["kind"], o["key"]
            if k == "build" and o.get("slot"):
                continue                         # 슬롯 카드는 위에서
            if k == "build" and key == "line" and o["border"] not in sel and r == center:
                # 광역시 칸(v1.3.18)의 바깥 경계마다 방어선 하나
                add(k, key, o["name"], o["cost"], o["turns"], o["ok"], o["why"], o["level"], border=o["border"], site=r)
            elif k == "annex" and ("annex", key) not in seen:
                seen.add(("annex", key))
                add(k, key, o["name"], o["cost"], o["turns"], o["ok"], o["why"], o["level"], site=r)
                opts[-1]["eff_turns"] = o.get("eff_turns", o["turns"])     # 구성 지역 수만큼 줄어든 턴
            elif k == 'repair' and ("repair", key) not in seen:
                seen.add(("repair", key))        # 하나의 지역: 침수 복구도 광역시 전체 한 번
                add(k, key, o['name'], o['cost'], o['turns'], o['ok'], o['why'], o['level'], site=center)
            elif k in ("science", "econ") and (k, key) not in seen:
                if k == "econ" and key == "exchange" and any("exchange" in g.regions[x].econ for x in sel):
                    continue                     # 증권거래소는 광역시에 하나
                seen.add((k, key))
                add(k, key, o["name"] + ("" if r == center else f" ({g.info(r).short})"), o["cost"], o["turns"],
                    o["ok"], o["why"], o["level"], site=r)
    # 공항: 광역시에 하나도 없을 때만(항구·사관학교는 광역 슬롯 카드)
    for key in SPREAD_SINGLES:
        spec = C.SINGLE_BUILDINGS[key]
        if any(g.reserved_level(r, key) for r in sel):
            continue
        site = center
        add("build", key, spec["name"], spec["cost"] * C.BUILD_COST_MULT * C.MONEY_SCALE * g.building_cost_mult(fid, key),
            g.build_time(fid, key, spec["turns"], site, 1), level=1, site=site)
    # 군 유닛: 하나를 만들면 지역 수만큼 나온다(해군은 항구가 있는 해안 지역에서)
    # 해군은 광역시 칸(중심)에서: 광역시에 항구(광역 해안 슬롯·무료 항구)가 있거나 짓는 중이면
    port = center if g.info(center).coastal and any(g.reserved_level(r, 'port') for r in sel) else None
    for key in C.BUILD_UNITS:
        u = g.unit_spec(fid, key)
        site = center
        ok, why = (False, "항공모함 강습단 기술 필요") if key == "cv" and "cv" not in g.factions[fid].techs else (True, "")
        if u["kind"] == "naval":
            if not any(g.info(r).coastal for r in sel):
                continue
            if port is None:
                ok, why = False, "항구 필요"
            else:
                site = port
        oil = g.unit_oil(fid, key)
        if ok and not cr.project and not g.can_pay_oil(fid, oil):
            ok, why = False, f"석유 {oil} 필요(석탄 {oil * C.OIL_AS_COAL}로 대체 가능)"
        per = g.unit_cost(fid, site, key)
        add("unit", key, f"{u['name']} ×{n}", per * u["turns"], g.unit_turns(fid, key), ok, why, oil=oil, site=site)
    # 천도: 수도가 광역시 밖이면 중심으로
    if g.factions[fid].capital not in sel:
        o = next((o for o in raw[center] if o["kind"] == "capital"), None)
        if o:
            add("capital", "capital", o["name"], o["cost"], o["turns"], o["ok"], o["why"], site=center)
    return opts


def start(g, fid, mid, kind, key, border=None, site=None, pool=None) -> tuple:
    m = get(g, mid)
    if not m:
        return False, '광역시가 없습니다.'
    return g.start_project(fid, m['center'], kind, key, border=border, site=site, pool=pool)


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
        if p.key in SPREAD_SINGLES:
            for r in sel:
                g.regions[r].b[p.key] = 1
            g.event("complete", f"{name} {C.SINGLE_BUILDINGS[p.key]['name']} 완공", region=site, fids=(f.id,))
            return
        rr = g.regions[site]
        g._complete_project(f, rr, p)      # 슬롯 카드(광역 슬롯은 중심, 기타 슬롯은 그 지역)·방어선: 그 지역에
        if getattr(p, "chain", False) and getattr(p, "slot", None):
            g._chain_next(f, rr, p)
        return
    if p.kind == "unit":
        n = g.leader_units_completed(f.id, site, p.key, len(sel))
        g.deliver_units(f.id, site, p.key, n)
        g.event("complete", f"{name}에서 {g.unit_spec(f.id, p.key)['name']} {n}개 생산 완료", region=site, fids=(f.id,))
        if getattr(p, "repeat", 0) > 0:
            g._repeat_unit(f, g.regions[m['center']], p)
        return
    g._complete_project(f, g.regions[site], p)          # 과학·경제·천도: 그 지역에


def migrate(g):
    """예전 세이브(v1.3.9까지: 생산 건물을 구성 지역끼리 평균 단계로 통합하던 광역시)를 광역 슬롯으로 바꾼다(불러올 때 한 번).
    통합 건물 공사와 구성 지역의 기본·하천·해안 슬롯 공사는 칸이 바뀌어 낸 돈을 모두 돌려준다."""
    for m in metros(g).values():                 # v1.3.17 전 세이브: 부대·방어선을 광역시 칸으로(지도 다시 그리기)
        if m.get("slot_merge") and not m.get("map_merged") and all(r in g.regions for r in m["members"]):
            _gather(g, m)
            _merge_lines(g, m)
            m["map_merged"] = True
    for m in metros(g).values():
        if m.get("slot_merge") or not all(r in g.regions for r in m["members"]):
            continue
        if not all(hasattr(g.regions[r].b, "slots") for r in m["members"]):
            continue
        center = m["center"]
        cr = g.regions[center]
        owner = cr.owner
        for p in list(g.local_projects(center)):
            stale = p.kind == "build" and ((p.pool is not None and p.pool not in POOL_KEY)
                                           or (getattr(p, "slot", None) and p.slot[0] in MERGE_TYPES))
            if not stale:
                continue
            if owner != NEUTRAL:
                g.factions[owner].money += p.paid
                g.factions[owner].refund += p.paid
            if cr.project is p:
                for r in g.regions.values():
                    if r.project is p:
                        r.project = None
            else:
                cr.queue[:] = [q for q in cr.queue if q is not p]
        m["merge"] = {k: v for k, v in m.get("merge", {}).items() if k in POOL_KEY}
        merge(g, m)
        _gather(g, m)
        _merge_lines(g, m)
        m["map_merged"] = True
        if cr.project is None and owner != NEUTRAL:
            g.promote_queue(center)


# ------------------------------------------------------------------ 점령·정리
def after_capture(g, mid, new_owner):
    m = get(g, mid)
    if m is None:
        return
    m["owner"] = new_owner
    m["special"] = new_owner != NEUTRAL and g.factions[new_owner].capital in m["members"]


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
