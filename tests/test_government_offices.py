"""체제 선택과 자원 초기화 분리, 집무실 산출·이전·수복 기한 및 구 저장 호환."""
import pickle

import pytest

from korciv import config as C, diplomacy as D, slots as S
from korciv.game import Game
from korciv.leaders import GOV_BY_KEY, GOV_OFFICES
from korciv.state import Settings
from korciv.text import fmt_points


def game(mode="frontier", leader="cus"):
    return Game(Settings(seed=81, mode=mode, n_enemies=1, player_leader=leader,
                         player_start="S002", ai_starts=["N001"], ai_leaders=["cus"]))


def own(g, rid):
    g.transfer_region(rid, 0, reason="편입")
    g.regions[rid].resist = None
    return g.regions[rid]


@pytest.mark.parametrize("mode", C.GAME_MODES)
def test_start_is_ready_without_government_or_free_admin(mode):
    g = game(mode)
    assert g.setup_done and g.player.gov is None
    assert set(GOV_BY_KEY) == set(GOV_OFFICES) and len(GOV_BY_KEY) == 6
    assert g.office_building(g.player.capital) is None
    if mode == "standard":
        assert g.regions[g.player.capital].b.slots == S.initial(g.world, g.player.capital).slots
    else:
        assert not g.regions[g.player.capital].b.used()
    assert all(f.gov in GOV_BY_KEY for f in g.factions if f.is_ai)
    for f in g.factions:
        if f.is_ai:
            assert g.office_output(f.capital) >= 30


@pytest.mark.parametrize("key", GOV_OFFICES)
@pytest.mark.parametrize("pop,expected", [(1, 30), (30, 30), (30.12345, 30.12345), (100, 100)])
def test_office_is_separate_and_keeps_full_precision(key, pop, expected):
    g = game()
    r = g.regions[g.player.capital]
    r.b.clear_cards()
    r.pop = pop
    slots = pickle.dumps(r.b.slots)
    assert g.set_player_government(key)[0]
    assert g.office_building(r.id) == dict(name=GOV_OFFICES[key], output=expected)
    assert g.admin_output(r.id) == expected
    assert pickle.dumps(r.b.slots) == slots
    assert not any(o["key"] == "office" for o in g.options(0, r.id))
    assert r.b.place("admin", 1)
    assert g.admin_output(r.id) == expected + C.ADMIN_OUTPUT[1]
    r.flooded = True
    assert g.admin_output(r.id) == expected


def test_choice_does_not_reset_money_population_or_ongoing_turn():
    g = game(leader="onz")
    r = g.regions[g.player.capital]
    pop = r.pop
    g.player.money, g.player.admin, g.player.sci_points = 1234, 567, 89.1234
    g.turn = 8
    assert not g.set_player_government("philosopher")[0]
    assert g.set_player_government("presidential")[0]
    assert not g.set_player_government("absolute")[0]
    g.finalize_setup()
    assert (g.player.money, g.player.admin, g.player.sci_points, r.pop, g.turn) == (1234, 567, 89.1234, pop, 8)


def test_banned_government_cannot_create_office():
    g = game(leader="gil")
    assert not g.set_player_government("absolute")[0]
    assert not g.set_player_government("constitutional")[0]
    assert g.player.gov is None and g.office_output(g.player.capital) == 0
    assert g.set_player_government("presidential")[0]


def captured_capital():
    g = game()
    assert g.set_player_government("presidential")[0]
    old = g.player.capital
    rest = [own(g, rid) for rid in sorted(g.world.land_adj[old])[:2]]
    rest[0].pop, rest[1].pop = 70, 40
    g.dip.wars[D.pair(0, 1)] = {"start": g.turn, "declarer": 1, "score": {}}
    g.complete_occupation(1, old)
    return g, old, rest


def test_capture_moves_office_immediately_and_early_retake_restores():
    g, old, rest = captured_capital()
    assert g.player.capital == rest[0].id
    assert g.office_building(old) is None
    assert g.office_output(rest[0].id) == 70
    g.turn += C.RESIST_NO_REBEL_TURNS - 1
    g.complete_occupation(0, old)
    assert g.player.capital == old and g.player.lost_capital is None
    assert g.office_output(old) == 30 and g.office_building(rest[0].id) is None


@pytest.mark.parametrize("late", [0, 1, 50])
def test_retake_at_or_after_deadline_does_not_restore_even_in_same_war(late):
    g, old, rest = captured_capital()
    g.turn += C.RESIST_NO_REBEL_TURNS + late
    g.complete_occupation(0, old)
    assert g.player.capital == rest[0].id and g.player.lost_capital is None
    assert g.office_building(old) is None and g.office_output(rest[0].id) == 70


def test_losing_temporary_capital_does_not_extend_original_deadline():
    g, old, rest = captured_capital()
    claim = dict(g.player.lost_capital)
    g.turn += 4
    g.complete_occupation(1, rest[0].id)
    assert g.player.capital == rest[1].id and g.player.lost_capital == claim
    assert g.office_output(rest[1].id) == 40
    g.complete_occupation(0, old)
    assert g.player.capital == old
    assert sum(g.office_building(r.id) is not None for r in g.regions_of(0)) == 1


def test_claim_expires_without_recapture_and_survives_save_before_expiry():
    g, old, rest = captured_capital()
    copy = pickle.loads(pickle.dumps(g))
    assert copy.player.lost_capital == g.player.lost_capital
    assert copy.office_output(rest[0].id) == 70
    copy.turn += C.RESIST_NO_REBEL_TURNS
    copy._settle_government_buildings()
    assert copy.player.lost_capital is None and copy.player.capital == rest[0].id


def test_manual_move_transfers_office_and_cancels_automatic_return():
    g, old, rest = captured_capital()
    g.player.money = 1e9
    target = rest[1].id
    assert g.start_project(0, target, "capital", "capital")[0]
    project = g.regions[target].project
    g._complete_project(g.player, g.regions[target], project)
    assert g.player.capital == target and g.player.lost_capital is None
    assert g.office_output(target) == 40 and g.office_building(rest[0].id) is None
    g.complete_occupation(0, old)
    assert g.player.capital == target


def test_removed_government_save_migrates_without_starting_resources_reset():
    g = game()
    g.player.gov = "philosopher"
    g.factions[1].gov = "philosopher"
    g.player.money, g.player.admin, g.turn = 987, 654, 17
    copy = pickle.loads(pickle.dumps(g))
    assert copy.player.gov is None and copy.factions[1].gov in GOV_BY_KEY
    assert (copy.player.money, copy.player.admin, copy.turn) == (987, 654, 17)
    assert copy.set_player_government("socialist")[0]


def test_metro_has_one_office_based_on_its_capital_region_population():
    """광역시는 하나의 지역(v1.3.17): 수도가 든 광역시의 집무실은 하나, 행정력은 광역시 인구 합으로."""
    g = game()
    assert g.set_player_government("presidential")[0]
    cap = g.player.capital
    members = [cap] + sorted(g.world.land_adj[cap])[:3]
    for rid in members:
        r = own(g, rid)
        r.pop, r.happy = 26, 20
        r.b["admin"] = 3
        r.b["factory"] = r.b["bank"] = 5
    assert g.create_metro(0, members[1], members)[0]
    assert g.office_output(cap) == 4 * 26
    assert all(g.office_building(rid) is None for rid in members if rid != cap)
    assert g.admin_balance(0)[0] == 4 * C.ADMIN_OUTPUT[3] + 4 * 26


@pytest.mark.parametrize("number,text", [(0, "0"), (.000012, "0"), (12.34567, "12.35"),
                                         (100.01, "100.01"), (12345.6789, "12,345.68")])
def test_science_display_rounds_only_the_text(number, text):
    assert fmt_points(number) == text
    g = game()
    r = g.regions[g.player.capital]
    r.b["edu"], r.pop = 1, 12.34567
    produced = g.science_output(r.id)
    assert produced != round(produced, 2)
    g._phase_knowledge(g.player)
    assert g.player.sci_points == produced
    display = g.building_effect(0, r.id, dict(key="edu", level=1))
    assert fmt_points(C.EDU_SCIENCE[1] * r.pop) in display
