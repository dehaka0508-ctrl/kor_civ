"""v1.3.0 편의성 개선: 여러 부대 한 번에 공격, 중립 지역 [편입]/[최대 편입], 공동 편입 한 줄 표시,
자동 해산, 부대 정렬, 거래 제의 거절, 생산 집결지."""
import pickle

import pytest

from korciv import ai
from korciv import config as C
from korciv import diplomacy as D
from korciv.game import Game
from korciv.state import NEUTRAL, Settings


def new_game(**kw):
    kw.setdefault("seed", 5)
    kw.setdefault("player_start", "S002")
    kw.setdefault("n_enemies", 1)
    g = Game(Settings(**kw))
    ids = [f.id for f in g.factions]
    for f in g.factions:
        f.met = set(ids) - {f.id}
    return g


def _clear(g, *rids):
    for r in rids:
        for a in list(g.armies_at(r)):
            g.remove_army(a)


def _two_front(g):
    """S002 와 다른 내 지역 한 곳이 함께 맞닿은 적 지역(tgt)과 그 두 번째 출발지(side)."""
    w = g.world
    for tgt in sorted(w.land_adj["S002"]):
        side = next((n for n in sorted(w.land_adj[tgt]) if n != "S002" and n in g.regions), None)
        if side:
            break
    g.transfer_region(side, 0)
    g.transfer_region(tgt, 1)
    _clear(g, tgt, side, "S002")
    D.declare_war(g, 0, 1)
    return tgt, side


def _joint_target(g):
    """S002 이웃을 모두 내 땅으로 만들고, 내 지역 둘 이상과 맞닿은 중립 지역을 고른다."""
    w = g.world
    for n in sorted(w.land_adj["S002"]):
        if g.regions[n].owner == NEUTRAL:
            g.transfer_region(n, 0)
    cand = {}
    for r in sorted(r for r in g.regions if g.regions[r].owner == 0):
        for n in w.land_adj[r]:
            if g.regions[n].owner == NEUTRAL:
                cand.setdefault(n, set()).add(r)
    tgt = max(sorted(cand), key=lambda n: len(cand[n]))
    assert len(cand[tgt]) >= 2
    return tgt


# ------------------------------------------------------------------ 1. 여러 부대로 한 번에 공격
def test_multi_army_attack_is_one_battle_with_flank_bonus():
    g = new_game()
    tgt, side = _two_front(g)
    g.new_army(1, tgt, {"inf": 6})
    a = g.new_army(0, "S002", {"inf": 3})
    b = g.new_army(0, side, {"inf": 3})
    c = g.new_army(0, "S002", {"inf": 2})
    cands = g.attack_candidates(0, tgt)
    assert {a.id, b.id, c.id} <= {x.id for x in cands}
    solo = g.preview_attack(a, tgt)
    both = g.preview_attack(a, tgt, extra=[b, c])
    assert both["sources"] == 2 and both["A"] > solo["A"] * 2
    bd = g.battle_breakdown(a, tgt, extra=[b, c])
    assert any("협공" in name for name, _ in bd["att_factors"])
    assert bd["att_units"].get("inf") == 8
    n_ev = sum(1 for e in g.events if e["kind"] == "battle")
    ok, msg = g.attack_now(a.id, tgt, extra=[b.id, c.id])
    assert ok, msg
    assert sum(1 for e in g.events if e["kind"] == "battle") == n_ev + 1        # 한 번의 전투
    for x in (a, b, c):
        assert x.id not in g.armies or g.army_fought(x.id)
    assert all(not x.order for x in g.armies.values() if x.owner == 0)


def test_multi_attack_ignores_armies_that_cannot_reach():
    g = new_game()
    tgt, side = _two_front(g)
    g.new_army(1, tgt, {"inf": 2})
    a = g.new_army(0, "S002", {"inf": 4})
    far = next(r for r in sorted(g.regions) if g.regions[r].owner == NEUTRAL
               and r not in g.world.land_adj[tgt] and r != tgt)
    g.transfer_region(far, 0)
    _clear(g, far)
    z = g.new_army(0, far, {"inf": 9})
    assert z.id not in {x.id for x in g.attack_candidates(0, tgt)}
    ok, _ = g.attack_now(a.id, tgt, extra=[z.id, 99999])
    assert ok
    assert not g.army_fought(z.id) and z.loc == far


# ------------------------------------------------------------------ 2·3. [편입]/[최대 편입], 공동 편입 한 줄
def test_annex_from_one_then_every():
    g = new_game()
    tgt = _joint_target(g)
    g.player.money = 100_000
    srcs = g.annex_sources(0, tgt)
    assert len(srcs) >= 2
    n, msg = g.annex_from(0, tgt)
    assert n == 1 and g.joint_count(0, tgt) == 1
    assert g.regions[srcs[0]].project.kind == "annex" and g.regions[srcs[0]].project.key == tgt
    n, msg = g.annex_from(0, tgt, every=True)
    assert n == len(srcs) - 1 and g.joint_count(0, tgt) == len(srcs)
    assert g.annex_sources(0, tgt) == []
    assert g.annex_from(0, tgt)[0] == 0


def test_joint_annex_is_one_priority_row_and_pins_together():
    g = new_game()
    tgt = _joint_target(g)
    g.player.money = 100_000
    srcs = g.annex_sources(0, tgt)
    g.start_project(0, srcs[0], "annex", tgt)
    other = next(r.id for r in g.regions_of(0) if not r.project and r.id not in srcs)
    ok, _ = g.start_project(0, other, "unit", "inf")
    assert ok
    g.start_project(0, srcs[1], "annex", tgt)
    rows = g.priority_rows(0)
    annex_rows = [row for row in rows if row[0].project.kind == "annex" and row[0].project.key == tgt]
    assert len(annex_rows) == 1 and {r.id for r in annex_rows[0]} == {srcs[0], srcs[1]}
    order = [r.id for r in g.projects_by_priority(0)]
    i, j = order.index(srcs[0]), order.index(srcs[1])
    assert abs(i - j) == 1                          # 같은 대상 편입은 붙어 있다
    assert g.toggle_pin(0, srcs[1]) is True
    assert g.regions[srcs[0]].project.pinned and g.regions[srcs[1]].project.pinned
    assert [r.id for r in g.priority_rows(0)[0]] == [srcs[0], srcs[1]] or \
        {r.id for r in g.priority_rows(0)[0]} == {srcs[0], srcs[1]}


# ------------------------------------------------------------------ 7. 편입 자동 해산
def _annex_until_done(g, src, tgt):
    ok, msg = g.start_project(0, src, "annex", tgt)
    assert ok, msg
    for _ in range(g.regions[src].project.turns + 1):
        g.player.money += 10_000
        g.pending_proposals.clear()
        g.end_turn()
        if g.regions[tgt].owner == 0:
            break
    assert g.regions[tgt].owner == 0


def test_annex_auto_disband_gives_happiness_instead_of_infantry():
    res = {}
    for disband in (False, True):
        g = new_game()
        tgt = min(g.world.land_adj["S002"], key=lambda r: (g.regions[r].pop, r))
        if disband:
            g.player.annex_disband.add(tgt)
        _annex_until_done(g, "S002", tgt)
        res[disband] = (sum(a.units.get("inf", 0) for a in g.armies_at(tgt, 0)), g.regions[tgt].happy)
        assert tgt not in g.player.annex_disband
    assert res[False][0] >= 1 and res[True][0] == 0
    # 완료한 턴 끝의 행복도 변화(소폭 수렴)를 거쳐도 +0.5 만큼 높다
    assert res[True][1] - res[False][1] == pytest.approx(C.UNIT_DISBAND_HAPPY["light"], abs=0.02)


# ------------------------------------------------------------------ 6. 같은 지역 부대는 늘 같은 병종 순서
def test_army_sort_key_orders_by_unit_type():
    g = new_game()
    _clear(g, "S002")
    tk = g.new_army(0, "S002", {"tank": 5})
    inf2 = g.new_army(0, "S002", {"inf": 2})
    inf9 = g.new_army(0, "S002", {"inf": 9})
    art = g.new_army(0, "S002", {"art": 1})
    got = [a.id for a in sorted(g.armies_at("S002", 0), key=g.army_sort_key)]
    order = {k: i for i, k in enumerate(C.UNIT_ORDER)}
    exp = sorted([tk, inf2, inf9, art], key=lambda a: (order[g.army_icon_unit(a)], -sum(a.units.values()), a.id))
    assert got == [a.id for a in exp]
    assert got.index(inf9.id) < got.index(inf2.id)


# ------------------------------------------------------------------ 8. 거래 제의 거절
@pytest.mark.parametrize("flag,sell", [("reject_buy", False), ("reject_sell", True), ("from", True), ("from", False)])
def test_trade_offer_rejection_settings(flag, sell):
    g = new_game()
    pf = g.player
    if flag == "from":
        pf.ai["reject_from"] = {1}
    else:
        pf.ai[flag] = True
    assert ai._offer_to_player(g, 1, 0, "oil", 2, sell) is False
    assert not g.pending_proposals
    if flag != "from":                           # 반대쪽 제의는 막지 않는다(협상이 열리는지는 상황에 따라)
        other = ai._offer_to_player(g, 1, 0, "oil", 2, not sell)
        assert other in (True, False)


# ------------------------------------------------------------------ 9. 생산 집결지
def test_set_rally_validation_and_clear_on_transfer():
    g = new_game()
    near = sorted(g.world.land_adj["S002"])
    mine, enemy = near[0], near[1]
    g.transfer_region(mine, 0)
    g.transfer_region(enemy, 1)
    assert g.set_rally(0, "S002", enemy)[0] is False
    assert g.set_rally(0, enemy, "S002")[0] is False
    assert g.set_rally(0, "S002", mine)[0] is True
    assert g.rally_of(0, "S002") == mine and g.rally_of(0, mine) is None
    assert g.set_rally(0, None, "S002")[0] is True           # 일괄 지정은 지역별 지정을 지운다
    assert g.regions["S002"].rally is None and g.player.rally == "S002"
    assert g.rally_of(0, mine) == "S002" and g.rally_of(0, "S002") is None
    g.set_rally(0, mine, "S002")
    g.transfer_region(mine, 1)
    assert g.regions[mine].rally is None                     # 주인이 바뀌면 지운다
    g.set_rally(0, None, None)
    assert g.player.rally is None


def test_produced_land_units_head_to_rally():
    g = new_game()
    dest = sorted(g.world.land_adj["S002"])[0]
    g.transfer_region(dest, 0)
    _clear(g, dest)
    g.set_rally(0, "S002", dest)
    a1 = g.deliver_units(0, "S002", "inf", 1)
    a2 = g.deliver_units(0, "S002", "inf", 1)
    assert a1 is a2 and a1.units["inf"] == 2 and a1.goto == dest   # 같은 집결지로 갈 부대에 합친다
    g.pending_proposals.clear()
    g.end_turn()
    assert a1.id in g.armies and g.armies[a1.id].loc == dest
    # 해군·과학 유닛은 집결지와 상관없이 그 자리
    g.regions["S002"].b["port"] = 1
    before = {a.id for a in g.armies_at("S002", 0)}
    g.deliver_units(0, "S002", "dd", 1)
    assert all(a.goto is None for a in g.armies_at("S002", 0) if a.id not in before)


def test_unit_project_completion_uses_rally():
    g = new_game()
    dest = sorted(g.world.land_adj["S002"])[0]
    g.transfer_region(dest, 0)
    _clear(g, dest)
    g.set_rally(0, "S002", dest)
    g.player.money = 100_000
    ok, msg = g.start_project(0, "S002", "unit", "inf")
    assert ok, msg
    for _ in range(g.regions["S002"].project.turns + 2):
        g.pending_proposals.clear()
        g.end_turn()
    assert any(a.units.get("inf") for a in g.armies_at(dest, 0))


def test_national_rally_includes_annexed_infantry():
    g = new_game()
    tgt = min(g.world.land_adj["S002"], key=lambda r: (g.regions[r].pop, r))
    g.set_rally(0, None, "S002")
    before = sum(a.units.get("inf", 0) for a in g.armies_at("S002", 0))
    _annex_until_done(g, "S002", tgt)
    # 넘겨받은 보병은 다음 턴 시작(같은 end_turn 끝)에 집결지로 이미 옮겨 갔다
    assert not g.armies_at(tgt, 0)
    assert sum(a.units.get("inf", 0) for a in g.armies_at("S002", 0)) == before + 1


def test_save_roundtrip_and_old_save_migration():
    g = new_game()
    dest = sorted(g.world.land_adj["S002"])[0]
    g.transfer_region(dest, 0)
    g.set_rally(0, "S002", dest)
    g.player.annex_disband.add("S999")
    g2 = pickle.loads(pickle.dumps(g))
    assert g2.regions["S002"].rally == dest and "S999" in g2.player.annex_disband
    for f in g.factions:                          # v1.3.0 전 세이브: 새 필드가 없다
        f.__dict__.pop("annex_disband", None)
        f.__dict__.pop("rally", None)
    for r in g.regions.values():
        r.__dict__.pop("rally", None)
    g3 = pickle.loads(pickle.dumps(g))
    assert g3.player.annex_disband == set() and g3.player.rally is None
    assert g3.rally_of(0, "S002") is None
