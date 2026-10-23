"""pygame 화면을 창 없이(dummy 드라이버) 그려 보는 스모크 테스트."""
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from korciv import config as C  # noqa: E402
from korciv.state import NEUTRAL, Settings  # noqa: E402
from korciv.ui.app import MAP_MODES, App  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = App()
    yield a
    pygame.quit()


def frame(app):
    app.gui.begin([])
    app.frame()


def test_screens_render(app):
    frame(app)  # 설정 화면
    app.scene = "pick_start"
    frame(app)
    app.start_game(Settings(seed=4, n_enemies=3))
    frame(app)  # 정치체제
    app.game.set_player_government("presidential")
    app.scene = "main"
    g = app.game
    for _ in range(5):
        g.pending_rebellions.clear()
        g.pending_proposals.clear()
        app.end_turn()
    g.pending_proposals.clear()
    app.modal = None
    app.select(g.player.capital)
    for tab in ("action", "army", "nation"):
        app.tab = tab
        frame(app)
    for key, _ in MAP_MODES:
        app.mode = key
        app.changed()
        frame(app)
    other = next(f.id for f in g.factions if f.id != g.player_id)
    app.open_diplomacy(other)
    frame(app)
    for m in (("help", None), ("log", None), ("gameover", None)):
        app.modal = m
        frame(app)
    app.modal = None
    g.pending_rebellions.append(g.player.capital)
    frame(app)
    g.pending_rebellions.clear()
    g.pending_proposals.append({"from": other, "kind": "nonaggr"})
    frame(app)
    g.pending_proposals.clear()
    # AI 자원 거래 제의(판매·구매) 창
    from korciv import diplomacy as D
    if not D.at_war(g, other, g.player_id):
        for sell, res in ((True, "coal"), (False, "specialty")):
            g.pending_proposals.append({"from": other, "kind": "trade", "res": res, "n": 2, "price": 55.0, "sell": sell})
            frame(app)
            g.pending_proposals.clear()
    app.select("SEA2")
    frame(app)


def test_map_pick(app):
    mv = app.map
    mv.z = 3
    mv.center_on("S002")
    x, y = mv.label_screen("S002")
    assert mv.pick((int(x), int(y))) == "S002"


def test_tax_slider_release_commits(app):
    from korciv.state import Settings
    app.start_game(Settings(seed=5, n_enemies=1))
    app.game.set_player_government("presidential")
    app.scene = "main"
    from korciv.ui import panels
    from korciv.ui.app import LEFT_W
    app.left_open, app.left_tab = True, "nation"
    gui = app.gui
    orig = pygame.mouse.get_pos
    try:
        # 슬라이더 위치: 좌측 세로 탭 옆 [국가] 패널 첫 줄 (논리 좌표 → 실제 픽셀)
        x0 = 8 + panels.RAIL_W + 6 + 14 + 40
        wdt = LEFT_W - 28 - 122
        y = 56 + 12 + 46 + 26 + 4 + 10
        u = gui.u
        def at(lx):
            p = (int(lx * u), int(y * u))
            pygame.mouse.get_pos = lambda: p
            return p
        at(x0 + wdt * 0.1)
        gui.begin([]); app.frame()
        p = at(x0 + wdt * 0.1)
        gui.begin([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=p)]); app.frame()
        p = at(x0 + wdt * 0.6)
        gui.begin([]); app.frame()
        gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=p)]); app.frame()
        assert app.game.player.tax == pytest.approx(0.30, abs=0.02)
    finally:
        pygame.mouse.get_pos = orig


def test_stat_chart_popup(app):
    """국가 현황 위 추이 타일을 누르면 턴별 추이 팝업이 뜨고, 항목·기간을 바꿔 그려도 되며 Esc로 닫힌다."""
    from korciv.ui import panels
    app.start_game(Settings(seed=6, n_enemies=2))
    app.game.set_player_government("presidential")
    app.scene = "main"
    g = app.game
    app.modal = ("stat_chart", "gdp")
    frame(app)                                   # 기록이 없을 때
    app.modal = None
    for _ in range(3):
        g.pending_proposals.clear()
        g.pending_rebellions.clear()
        app.end_turn()
    g.pending_proposals.clear()
    g.dialogues = []
    app.left_open, app.left_tab = True, "status"
    gui = app.gui
    u = gui.u
    orig = pygame.mouse.get_pos
    try:
        x = 8 + panels.RAIL_W + 6 + 40          # 첫 타일(GDP) 안쪽
        hit = None
        for y in range(70, 300, 6):
            p = (int(x * u), int(y * u))
            pygame.mouse.get_pos = lambda p=p: p
            gui.begin([]); app.frame()
            if gui.tooltip == "누르면 턴별 추이를 크게 봅니다":
                hit = p
                break
        assert hit is not None
        gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=hit)]); app.frame()
        assert app.modal == ("stat_chart", "gdp")
        sw, sh = gui.size()
        p = (int(sw / 2 * u), int(sh / 2 * u))            # 그래프 위(마우스를 올린 턴 표시)
        pygame.mouse.get_pos = lambda: p
        for key in panels.STAT_COL:
            for ri in range(3):
                app.modal, app.stat_range = ("stat_chart", key), ri
                frame(app)
        esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="", scancode=41)
        gui.begin([esc]); app.frame()
        assert app.modal is None
    finally:
        pygame.mouse.get_pos = orig


def test_stat_chart_ticks():
    from korciv.ui.modals import _nice_step, _turn_ticks
    assert _nice_step(23000, 4) == 10000
    assert _nice_step(7, 4, integer=True) == 2
    assert _nice_step(0.4, 4, integer=True) == 1
    ticks, step = _turn_ticks(13, 60)
    assert step == 12 and ticks == [13, 25, 37, 49]
    assert len(_turn_ticks(1, 1200)[0]) <= 7


def test_enter_ends_turn_after_setup_text_focus(app):
    """시작 화면 입력칸에 포커스가 남은 채 게임을 시작해도 Enter로 턴이 넘어간다."""
    enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="\r", scancode=40)
    app.game = None
    app.scene = "setup"
    frame(app)
    app.gui.focus = "name"
    frame(app)
    assert app.gui.focus == "name"               # 그려지는 동안은 유지
    app.start_game(Settings(seed=4, n_enemies=3))
    frame(app)
    app.game.set_player_government("presidential")
    app.scene = "main"
    t0 = app.game.turn
    for _ in range(6):
        app.game.pending_proposals.clear()
        app.game.pending_rebellions.clear()
        app.modal = None
        app.gui.begin([enter])
        app.frame()
    assert app.gui.focus is None
    assert app.game.turn > t0


def test_priority_arrow_keys_reorder(app):
    """지출 우선순위에서 고른 행을 ↓로 옮긴다(시작 화면 입력칸 포커스가 남아 있어도)."""
    down = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, mod=0, unicode="", scancode=81)
    app.start_game(Settings(seed=4, n_enemies=3))
    frame(app)
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    pid = g.player_id
    near = sorted(g.world.land_adj[g.player.capital])[:2]
    for r in near:
        g.transfer_region(r, pid)
    for r in [g.player.capital] + near:
        assert g.start_project(pid, r, "build", "farm")[0]
    app.left_open, app.left_tab = True, "nation"           # 지출 우선순위는 [내정] 탭
    frame(app)
    ids = [r.id for r in g.projects_by_priority(pid)]
    app.prio_sel = ids[0]
    app.gui.focus = "name"                       # 시작 화면에서 남은 포커스
    app.gui.begin([down])
    app.frame()
    assert [r.id for r in g.projects_by_priority(pid)] == [ids[1], ids[0]] + ids[2:]


def test_reselect_region_closes_panel(app):
    g = app.game
    cap = g.player.capital
    app.left_open = False
    app.select(cap)
    assert app.left_open and app.left_tab == "region"
    sel = app.sel_army
    app.select(cap)                       # 같은 지역 다시 클릭 → 닫힘, 부대 선택은 그대로
    assert not app.left_open and app.sel_army == sel
    app.left_tab, app.tab, app.left_open = "army", "action", True
    frame(app)                            # 군사 요약
    app.left_tab, app.tab = "region", "army"
    frame(app)                            # 지역 부대 탭


def test_flags_and_diplo_detail(app):
    from korciv import flags as FL
    from korciv.ui import modals
    from korciv.ui.art import render_flag
    for bg in FL.BG_KEYS:                 # 모든 배경·문양 조합이 그려진다
        for em in FL.EMBLEM_KEYS:
            surf = render_flag({"bg": bg, "em": em, "c1": (10, 20, 30), "c2": (200, 0, 0), "ec": (255, 255, 0)}, 30, 20)
            assert surf.get_size() == (30, 20)
    assert len(FL.EMBLEMS) == 24 and len(FL.BACKGROUNDS) == 10
    assert sorted(k for row in FL.EMBLEM_ROWS for k in row) == sorted(FL.EMBLEM_KEYS)
    for pk in FL.PRESET_KEYS:             # 역사 국기(이미지·그림)
        assert render_flag({"preset": pk}, 30, 20).get_size() == (30, 20)
    assert FL.normalize({"bg": "nordic", "em": "star6"}) ["bg"] == "cross"   # 예전 저장 키
    assert FL.normalize({"em": "bolt"})["em"] == "cloud"
    # 단색 배경은 배경 색 2, 한 색 문양은 문양 색 2를 쓰지 않는다
    assert not FL.uses_c2({"bg": "solid"}) and FL.uses_c2({"bg": "h2"})
    assert FL.uses_ec2({"em": "taegeuk"}) and FL.uses_ec2({"em": "flower"}) and not FL.uses_ec2({"em": "star5"})
    a = render_flag({"em": "taegeuk", "ec": (255, 0, 0), "ec2": (0, 0, 255)}, 60, 40)
    b = render_flag({"em": "taegeuk", "ec": (255, 0, 0), "ec2": (0, 255, 0)}, 60, 40)
    assert a.get_at((30, 26)) != b.get_at((30, 26))   # 문양 색 2가 태극 아래쪽 색
    a = FL.default_flag("#3366cc", "1:x")
    assert a == FL.default_flag("#3366cc", "1:x")   # 기본 국기는 결정적
    s = app.setup
    s.flag_draft = dict(s.flag)
    app.scene = "setup"
    frame(app)                            # 국기 편집 창
    s.flag_draft["em"] = "taegeuk"
    s.flag = FL.normalize(s.flag_draft)
    s.flag_draft = None
    modals.start_from_setup(app)
    assert app.game.player.flag["em"] == "taegeuk"
    app.game.set_player_government("presidential")
    app.scene = "main"
    app.game.pending_proposals.clear()
    app.left_open, app.left_tab = True, "diplo"
    frame(app)
    other = next(f.id for f in app.game.factions if f.id != app.game.player_id)
    app.dip_view = other
    frame(app)
    app.dip_view = None


def test_click_foreign_region_by_visibility(app):
    app.start_game(Settings(seed=5, n_enemies=3, fog=1))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    app.modal = None
    g.pending_proposals.clear()
    pid = g.player_id
    other = next(f for f in g.factions if f.id != pid)
    cap = other.capital
    assert not g.is_visible(pid, cap) and g.is_explored(pid, cap)
    app.sel, app.left_open = None, False
    app.select(cap)                       # 시야 밖 타국 영토 → 외교 탭 세력 상세
    assert app.left_open and app.left_tab == "diplo" and app.dip_view == other.id
    frame(app)
    app.select(cap)                       # 다시 누르면 닫힘
    assert not app.left_open
    g.new_army(pid, cap, {"inf": 1})      # 시야 확보 → 지역 현황
    g._visible = {}
    assert g.is_visible(pid, cap)
    app.sel = None
    app.select(cap)
    assert app.left_tab == "region" and app.tab == "info"
    frame(app)
    neutral = next(rid for rid, r in g.regions.items() if r.owner == NEUTRAL and not g.is_visible(pid, rid))
    app.select(neutral)                   # 중립은 현행대로 지역 정보
    assert app.left_tab == "region" and app.tab == "info"
    frame(app)


def test_arrow_key_hold_pans(app, monkeypatch):
    """방향키를 누르고 있으면 프레임마다 지도가 계속 움직인다."""
    app.start_game(Settings(seed=4, n_enemies=3))
    app.game.set_player_government("presidential")
    app.scene, app.modal = "main", None
    app.game.pending_proposals.clear()
    app.gui.focus = None
    held = {pygame.K_RIGHT}

    class Pressed:
        def __getitem__(self, k):
            return k in held
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: Pressed())
    t = [1000]
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: t[0])
    app.arrow_pan()
    x0 = app.map.cx
    for _ in range(5):
        t[0] += 16
        app.arrow_pan()
    assert app.map.cx > x0                 # 오른쪽 키: 지도 중심이 오른쪽(동쪽)으로
    held.clear()
    x1 = app.map.cx
    t[0] += 16
    app.arrow_pan()
    assert app.map.cx == x1                # 떼면 멈춘다


def test_ai_flag_rules():
    from korciv import flags as FL
    for i in range(500):
        f = FL.default_flag("#c0392b", i)
        assert "preset" not in f                       # 역사 국기는 플레이어 전용
        if f["bg"] in ("solid", "border"):
            assert f["em"] != "none" and f["ec"] == (255, 255, 255)
            if f["em"] == "flower":
                assert f["ec2"] == f["c1"]
            if f["em"] == "yinyang":
                assert f["ec2"] == (0, 0, 0)
        else:
            assert f["em"] == "none"
        if f["bg"] != "solid":
            assert f["c2"] == (255, 255, 255)


def test_random_flag_follows_ai_rules():
    import random as _r
    from korciv import flags as FL
    rng = _r.Random(1)
    for _ in range(200):
        f = FL.random_flag(rng)
        assert "preset" not in f and f["c2"] == (255, 255, 255)
        assert (f["em"] != "none") == (f["bg"] in ("solid", "border"))


def test_save_version_and_slot_visibility(app, tmp_path, monkeypatch):
    """세이브에는 버전이 적히고, 버전이 없거나 주·부 버전이 다른 세이브는 [이어하기]에 보이지 않는다."""
    import pickle
    from korciv import version as V
    from korciv.ui import app as appmod
    monkeypatch.setattr(appmod, "SAVE_DIR", str(tmp_path))
    app.start_game(Settings(seed=4, n_enemies=1))
    assert app.save("slot1")
    with open(tmp_path / "slot1.sav", "rb") as f:
        assert pickle.load(f)["version"] == V.VERSION
    assert app.slot_info(1) is not None
    with open(tmp_path / "slot2.sav", "wb") as f:          # 버전 표기 없는 예전 형식
        pickle.dump(app.game, f)
    assert app.slot_info(2) is None
    major, minor, patch = V.parse(V.VERSION)
    with open(tmp_path / "slot3.sav", "wb") as f:          # 내용 패치(부 버전)가 다름
        pickle.dump({"version": f"{major}.{minor + 1}.0", "game": app.game}, f)
    assert app.slot_info(3) is None
    with open(tmp_path / "slot3.sav", "wb") as f:          # 수 버전만 다르면 이어서 가능
        pickle.dump({"version": f"{major}.{minor}.{patch + 5}", "game": app.game}, f)
    assert app.slot_info(3) is not None
    app.game = None
    app.load("slot2")
    assert app.game is None                                 # 불러오기도 거부
    app.load("slot1")
    assert app.game is not None
    app.game, app.scene = None, "title"
    frame(app)                                              # 시작 화면 버전 표시


def test_random_flag_ec2_not_white():
    """무작위 국기의 문양 색 2는 흰색으로 고정되지 않는다(두 색 문양으로 바꿔도 보이게)."""
    import random as _r
    from korciv import flags as FL
    rng = _r.Random(5)
    for _ in range(200):
        f = FL.random_flag(rng)
        assert f["ec2"] != (255, 255, 255)


def test_unmet_factions_hidden_under_fog(app):
    """안개 '미탐색'에서 조우하지 않은 국가는 '미지의 국가'·'수수께끼의 지도자'로만 보인다."""
    app.start_game(Settings(seed=7, n_enemies=6, fog=2))
    g = app.game
    g.set_player_government("presidential")
    app.scene, app.modal = "main", None
    g.pending_proposals.clear()
    pid = g.player_id
    unmet = [f for f in g.factions if f.id != pid and not g.has_met(pid, f.id)]
    assert unmet, "시작하자마자 모두 만난 상태면 안 된다"
    o = unmet[0]
    assert g.seen_name(o.id) == "미지의 국가" and g.seen_leader(o.id) == "수수께끼의 지도자"
    # 조우 판정: 그 세력 영토가 시야에 들어오면 만난 것
    g.new_army(pid, o.capital, {"inf": 1})
    g._update_fog()
    assert g.has_met(pid, o.id) and g.seen_name(o.id) == o.name
    # 이벤트 문장 가리기
    other = next(f for f in unmet[1:] if not g.has_met(pid, f.id))
    e = {"turn": 1, "kind": "war", "text": f"{other.name}이(가) {g.player.name}에 선전포고", "fids": (other.id, pid)}
    assert other.name not in g.event_for_player(e) and "미지의 국가" in g.event_for_player(e)
    e2 = {"turn": 1, "kind": "war", "text": "x", "fids": (other.id, o.id)}
    assert g.event_for_player(e2) is None
    app.left_open, app.left_tab, app.dip_view = True, "diplo", None
    frame(app)
    app.dip_view = other.id
    frame(app)
    app.modal = ("log", None)
    frame(app)
    app.modal = None
    # 안개가 없으면 모두 안다
    app.start_game(Settings(seed=7, n_enemies=3, fog=0))
    assert all(app.game.has_met(app.game.player_id, f.id) for f in app.game.factions)


def test_ai_leader_picker_and_fog_name_rules(app):
    from korciv.ui import modals
    s = modals.SetupState()
    s.leader, s.n_enemies, s.ai_leaders = "sej", 3, ["yis", None, None]
    app.setup, app.scene, app.game = s, "setup", None
    s.ai_pick = 1
    frame(app)                                   # 고르기 창
    assert s.ai_pick == 1
    s.ai_pick = None
    frame(app)
    # 안개 '지도 공개'는 국가명·수도는 알고 지도자는 모른다, '미탐색'은 둘 다 모른다
    for fog, name_known in ((1, True), (2, False)):
        app.start_game(Settings(seed=7, n_enemies=6, fog=fog))
        g = app.game
        o = next(f for f in g.factions if f.id != g.player_id and not g.has_met(g.player_id, f.id))
        assert (g.seen_name(o.id) == o.name) == name_known
        assert g.seen_leader(o.id) == "수수께끼의 지도자"


def test_portrait_codes():
    """지도자 키는 서로 다른 3글자이고, 올려 둔 이미지가 그 이름으로 불린다."""
    from korciv.leaders import LEADERS
    from korciv.ui.art import portrait_path
    keys = [l["key"] for l in LEADERS]
    assert len(keys) == len(set(keys)) and all(len(k) == 3 and k.islower() for k in keys)
    for key in ("dan", "jum", "onz"):
        p = portrait_path(key)
        assert p and os.path.basename(p).startswith(key + ".")


def test_resisting_region_action_tab(app):
    app.start_game(Settings(seed=4, n_enemies=1))
    g = app.game
    rid = g.player.capital
    r = g.regions[rid]
    r.resist = {"turn": g.turn, "from": 1, "h0": 0, "resist": 4, "recover": 20}
    app.select(rid)
    app.tab = "action"
    frame(app)
    assert g.resisting(r)
    assert rid not in [x.id for x in g.regions_of(g.player_id) if not g.resisting(x)]


def test_half_ranking_modal(app):
    app.start_game(Settings(seed=4, n_enemies=3, fog=2))
    g = app.game
    g.player.science = ["lab"]
    g.turn = 49
    g._half_ranking()
    app.modal = ("ranking", 49)
    for col in ("regions", "pop", "happy", "gdp", "science"):
        app.rank_col = col
        frame(app)
    from korciv.ui.modals import ranking_value_text
    row = next(r for r in g.rankings[49] if r["fid"] == g.player_id)
    assert ranking_value_text(g, row, "science") == "1/7"
    assert ranking_value_text(g, row, "gdp").endswith("%)")
    unmet = [f.id for f in g.factions if not g.has_met(g.player_id, f.id)]
    assert unmet and all(g.seen_name(f) == g.UNKNOWN_NAME for f in unmet)


def test_econ_ui_renders(app):
    app.start_game(Settings(seed=4, n_enemies=3))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    cap = g.player.capital
    plan, frontier = [cap], [cap]
    while len(plan) < 5:
        u = frontier.pop(0)
        for v in sorted(g.world.land_adj[u]):
            if v not in plan and len(plan) < 5:
                plan.append(v)
                frontier.append(v)
    for r in plan:
        if g.regions[r].owner != g.player_id:
            g.transfer_region(r, g.player_id)
        g.regions[r].b["bank"] = 5
        g.regions[r].resist = None
    g.player.money = 1e9
    app.select(cap)
    app.tab = "action"
    frame(app)
    assert any(o["kind"] == "econ" for o in g.options(g.player_id, cap))
    assert g.start_project(g.player_id, cap, "econ", "exchange")[0]
    frame(app)
    from korciv.ui.panels import econ_progress_text
    assert econ_progress_text(g, g.player_id).startswith("1/5")
    g.econ_alert(1, "테스트 알림")
    app.left_open, app.left_tab = True, "nation"
    g.turn = 49
    g._half_ranking()
    app.modal = ("ranking", 49)
    app.rank_col = "econ"
    frame(app)


def test_econ_progress_text_each_stage(app):
    from korciv.ui.panels import econ_progress_text
    app.start_game(Settings(seed=4, n_enemies=2))
    g = app.game
    cap = g.regions[g.player.capital]
    texts = [econ_progress_text(g, g.player_id)]
    for key in ("sez", "ifc", "currency"):
        cap.econ.add(key)
        texts.append(econ_progress_text(g, g.player_id))
    assert texts[1].startswith("3/5") and "국제금융센터" in texts[1]
    assert texts[2].startswith("4/5") and "기축통화" in texts[2]
    assert texts[3].startswith("5/5")


def test_dialogue_popup_enter_and_cjk(app):
    from korciv.ui import theme
    assert theme.is_cjk("星") and not theme.is_cjk("가")
    w_cjk = theme.measure("星星之火", 16)[0]
    assert w_cjk > 0 and theme.render_text("星星之火 가나", 16, (0, 0, 0)).get_width() > 0
    app.start_game(Settings(seed=4, n_enemies=2, ai_leaders=["mao", "sta"]))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    g.dialogues = [{"kind": "war", "fid": 1, "turn": 1}, {"kind": "peace", "fid": 2, "turn": 1}]
    app.enter_guard = 0
    assert app.active_modal() == "dialogue"
    frame(app)
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="\r")
    app.gui.begin([ev])
    app.frame()
    assert len(g.dialogues) == 1 and g.dialogues[0]["fid"] == 2
    g.game_over = True
    app.modal = ("gameover", None)
    app.gui.begin([ev])
    app.frame()
    assert not g.dialogues and app.active_modal() == "gameover"     # 대사를 닫으면 게임 종료 화면


def test_enemy_nation_slots_and_pick_ai(app):
    """적 국가: 모두 무작위 지도자·지역, 지도에서 칸별 시작 지역 고르기, 게임 시작 때 칸 순서 그대로 반영."""
    from korciv.game import land_dist, start_gap
    from korciv.ui import modals
    s = modals.SetupState()
    s.n_enemies = 4
    app.setup, app.scene, app.game = s, "setup", None
    frame(app)
    modals.random_ai_leaders(s)
    assert all(s.ai_leaders[:4]) and len(set(s.ai_leaders[:4])) == 4 and s.leader not in s.ai_leaders
    modals.random_ai_starts(app)                       # 내 지역을 안 골랐으면 적 국가끼리만
    st = s.ai_starts[:4]
    assert all(st) and all(land_dist(app.world, a, b, start_gap(app.world, a, b)) >= start_gap(app.world, a, b)
                           for i, a in enumerate(st) for b in st[i + 1:])
    s.start = "S001"
    modals.random_ai_starts(app)                       # 내 지역을 골랐으면 거기에 맞춰서
    assert all(land_dist(app.world, "S001", a, start_gap(app.world, "S001", a)) >= start_gap(app.world, "S001", a)
               for a in s.ai_starts[:4])
    frame(app)
    # 지도 화면: AI 2를 고르고 지역을 누르면 그 칸에 배치, 다른 나라 시작 지역은 무시
    app.scene = "pick_ai"
    s.ai_place = 1
    target = next(r for r in app.world.order if r not in s.ai_starts and r != s.start)
    app.pick_popup = target
    frame(app)
    assert s.ai_starts[1] == target
    s.ai_place = 2
    app.pick_popup = s.start
    frame(app)
    assert s.ai_starts[2] != s.start
    app.scene = "setup"
    s.ai_leaders[0] = None
    modals.start_from_setup(app)
    g = app.game
    assert [f.capital for f in g.factions[1:5]] == s.ai_starts[:4] and g.player.capital == "S001"
    assert [f.leader for f in g.factions[2:5]] == s.ai_leaders[1:4]


def test_player_color_from_custom_flag():
    from korciv.game import Game
    custom = {"bg": "solid", "c1": (10, 200, 30), "em": "disc"}
    g = Game(Settings(seed=3, n_enemies=2, player_flag=custom))
    assert g.player.color == "#0AC81E"
    g = Game(Settings(seed=3, n_enemies=2, player_flag={"preset": "taeguk"}))
    assert g.player.color == "#2B5B84"


def test_flag_hsl_roundtrip():
    from korciv.ui.modals import hsl_rgb, rgb_hsl
    for rgb in ((47, 111, 222), (0, 0, 0), (255, 255, 255), (200, 30, 30), (12, 150, 90)):
        back = hsl_rgb(*rgb_hsl(rgb))
        assert all(abs(a - b) <= 3 for a, b in zip(rgb, back))
    assert hsl_rgb(0, 100, 50) == (255, 0, 0) and hsl_rgb(120, 0, 100) == (255, 255, 255)


def test_enter_end_turn_does_not_skip_new_dialogue(app):
    """Enter로 턴을 넘기면 그 턴에 뜬 지도자 대사 창이 같은 Enter(또는 바로 이어진 Enter)로 닫히지 않는다."""
    app.start_game(Settings(seed=4, n_enemies=2, ai_leaders=["mao", "sta"]))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    g.pending_proposals.clear()
    g.pending_rebellions.clear()
    g.dialogues = []
    app.next_region = lambda: False
    real = g.end_turn

    def end_turn():
        real()
        g.pending_proposals.clear()
        g.pending_rebellions.clear()
        g.dialogues = [{"kind": "war", "fid": 1, "turn": g.turn}]
    g.end_turn = end_turn
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="\r")
    t0 = g.turn
    app.gui.begin([ev])
    app.frame()
    assert g.turn == t0 + 1 and len(g.dialogues) == 1        # 같은 Enter로 닫히지 않음
    app.gui.begin([ev])
    app.frame()
    assert len(g.dialogues) == 1                                # 바로 이어진 Enter(키 반복)도 무시
    app.enter_guard = 0
    app.gui.begin([ev])
    app.frame()
    assert not g.dialogues and g.turn == t0 + 1                 # 잠시 뒤 Enter는 대사만 닫는다
    del app.next_region


def test_battle_modal_enter_fights_now(app):
    from korciv import diplomacy as D
    app.start_game(Settings(seed=4, n_enemies=1))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    g.pending_proposals.clear()
    other = next(f.id for f in g.factions if f.id != g.player_id)
    cap = g.player.capital
    tgt = sorted(g.world.land_adj[cap])[0]
    g.transfer_region(tgt, other)
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    g.new_army(other, tgt, {"inf": 2})
    for f in g.factions:
        f.met = {x.id for x in g.factions} - {f.id}
    D.declare_war(g, g.player_id, other)
    g.dialogues = []
    a = g.new_army(g.player_id, cap, {"inf": 8})
    app.select(cap)
    app.sel_army = a.id
    app.modal = ("battle", {"army": a.id, "node": tgt, "mode": "assault"})
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="\r")
    app.gui.begin([ev])
    app.frame()
    assert g.army_acted(a.id) or a.id not in g.armies            # Enter로 바로 싸웠다
    app.modal = None
    app.tab = "army"
    app.left_open, app.left_tab = True, "region"
    frame(app)                                                    # 전투 완료 표시가 그려진다


def test_pause_and_prefs(app, monkeypatch, tmp_path):
    from korciv.ui import app as A
    monkeypatch.setattr(A, "PREFS_PATH", str(tmp_path / "prefs.json"))
    app.start_game(Settings(seed=5, n_enemies=1))
    app.game.set_player_government("presidential")
    app.scene = "main"
    app.game.pending_proposals.clear()
    app.game.dialogues = []
    app.modal = ("pause", None)
    frame(app)
    app.modal = ("prefs", "pause")
    frame(app)
    app.prefs["volume"] = 35
    A.save_prefs(app.prefs)
    assert A.load_prefs()["volume"] == 35
    app.modal = None


def test_pinned_priority_and_done_buildings_render(app):
    app.start_game(Settings(seed=4, n_enemies=2))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    g.pending_proposals.clear()
    app.modal = None
    pid = g.player_id
    cap = g.player.capital
    near = sorted(g.world.land_adj[cap])[:2]
    for r in near:
        g.transfer_region(r, pid)
    for r in near:
        assert g.start_project(pid, r, "build", "farm")[0]
    assert g.toggle_pin(pid, near[1])
    app.left_open, app.left_tab = True, "nation"
    frame(app)
    assert g.projects_by_priority(pid)[0].id == near[1]
    g.regions[cap].b["bank"] = C.PROD_BUILDINGS["bank"]["max"]
    app.select(cap)
    app.left_open, app.left_tab, app.tab = True, "region", "action"
    frame(app)


def test_sell_stored_food_slider(app):
    app.start_game(Settings(seed=4, n_enemies=2))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    g.pending_proposals.clear()
    app.modal = None
    f = g.player
    f.res["food"] = 500
    app.left_open, app.left_tab = True, "nation"
    app.food_sell_amt = 200
    frame(app)
    q, gain = g.market_sell(g.player_id, "food", app.food_sell_amt)
    assert q == 200 and f.res["food"] == 300 and gain == pytest.approx(200 * g.sell_price(g.player_id, "food"))


def _main_game(app, **kw):
    kw.setdefault("seed", 4)
    kw.setdefault("n_enemies", 2)
    app.start_game(Settings(**kw))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    g.pending_proposals.clear()
    g.pending_rebellions.clear()
    g.dialogues = []
    app.modal = None
    for f in g.factions:
        f.met = {x.id for x in g.factions} - {f.id}
    return g


def _key(app, k, mod=0):
    app.gui.begin([pygame.event.Event(pygame.KEYDOWN, key=k, mod=mod, unicode="", scancode=0)])
    app.frame()


def test_seed_with_unicode_digit_does_not_crash(app):
    """QA: 시드 칸의 '②'·'²'처럼 isdigit() 는 참이지만 int() 가 못 읽는 글자로 건국해도 멈추지 않는다."""
    from korciv.ui import modals
    for bad in ("②", "²", "12²"):
        app.setup.seed = bad
        modals.start_from_setup(app)
        assert app.game is not None
    app.setup.seed = "１２"                     # 전각 숫자는 그대로 시드로 쓴다
    modals.start_from_setup(app)
    assert app.game.settings.seed == 12
    app.setup.seed = ""


def test_end_turn_double_click_ends_one_turn(app):
    """QA: [턴 종료]를 빠르게 두 번 누르거나 Enter를 연타해도 한 턴만 넘어간다."""
    g = _main_game(app)
    from korciv import ai as AI
    AI.auto_slots(g, g.player_id, military=False)
    app.next_region = lambda: False
    real = g.end_turn

    def end_turn():
        real()
        g.pending_proposals.clear()
        g.pending_rebellions.clear()
        g.dialogues = []
    g.end_turn = end_turn
    t0 = g.turn
    app.request_end_turn()
    app.modal = None
    app.request_end_turn()                    # 바로 이어진 두 번째 입력은 무시
    assert g.turn == t0 + 1
    app.enter_guard = 0
    app.modal = None
    app.request_end_turn()
    assert g.turn == t0 + 2
    del app.next_region


def test_context_menu_stays_on_screen(app):
    """QA: 화면 오른쪽 아래에서 연 우클릭 메뉴가 화면 밖으로 나가지 않는다."""
    g = _main_game(app)
    sw, sh = app.lsize()
    other = next(f for f in g.factions if f.id != g.player_id)
    app.sel_army = None
    app.right_click(other.capital, (sw - 5, sh - 5))
    (x, y), _, _ = app.ctx_menu
    assert x + 170 <= sw and y + 84 <= sh
    frame(app)
    # 메뉴가 [다음 지역]·[턴 종료] 버튼과 겹쳐도 메뉴의 [외교]가 눌린다
    t0 = g.turn
    pos = (int((x + 85) * app.gui.u), int((y + 41) * app.gui.u))
    old = pygame.mouse.get_pos
    pygame.mouse.get_pos = lambda: pos
    try:
        app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)])
        app.frame()
    finally:
        pygame.mouse.get_pos = old
    assert app.modal and app.modal[0] == "diplomacy" and g.turn == t0
    app.modal = None
    app.ctx_menu = None


def test_review_queue_skips_resisting_regions(app):
    """QA: [다음 지역]은 점령 저항 중이라 슬롯을 못 쓰는 지역을 건너뛴다."""
    from korciv import diplomacy as D
    g = _main_game(app, n_enemies=1)
    pid = g.player_id
    cap = g.player.capital
    other = next(f.id for f in g.factions if f.id != pid)
    tgt = sorted(g.world.land_adj[cap])[0]
    g.transfer_region(tgt, other)
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    D.declare_war(g, pid, other)
    g.dialogues = []
    a = g.new_army(pid, cap, {"inf": 2})
    assert g.capture_now(a.id, tgt)[0] and g.resisting(g.regions[tgt])
    assert tgt not in app.review_queue()


def test_stale_counter_offer_cleared_after_other_trade(app):
    """QA: 수정안을 받은 뒤 다른 거래(선물)가 성사되면 옛 수정안은 지워지고, 돈이 모자라면 수정안 수락이 막힌다."""
    from korciv import diplomacy as D
    g = _main_game(app, n_enemies=1)
    pid = g.player_id
    other = next(f.id for f in g.factions if f.id != pid)
    g.player.money = 5000
    g.factions[other].money = 5000
    app.open_diplomacy(other)
    ds = app.dip_state
    ds.counter = {"give": D.empty_offer()["give"] | {"money": 1100},
                  "take": D.empty_offer()["take"] | {"money": 1000}}
    ds.offer["give"]["money"] = 5000                         # 전 재산 선물
    btn = {}
    real_button = app.gui.button

    def spy(rect, label, *a, **k):
        btn[label] = rect
        return real_button(rect, label, *a, **k)
    app.gui.button = spy
    frame(app)
    r = pygame.Rect(btn["제안하기"])
    u = app.gui.u
    pos = (int(r.centerx * u), int(r.centery * u))
    old = pygame.mouse.get_pos
    pygame.mouse.get_pos = lambda: pos
    try:
        app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)])
        app.frame()
    finally:
        pygame.mouse.get_pos = old
        app.gui.button = real_button
    assert g.player.money == 0 and ds.counter is None
    app.modal = None


def test_loaded_game_over_save_shows_result(app, monkeypatch, tmp_path):
    """QA: 게임이 끝난 뒤 저장한 파일을 불러오면 결과 창이 다시 뜬다(턴 종료만 막힌 채 멈춰 보이지 않게)."""
    from korciv.ui import app as A
    monkeypatch.setattr(A, "SAVE_DIR", str(tmp_path))
    g = _main_game(app, n_enemies=1)
    g.game_over = True
    g.winner = ((1,), "conquest")
    assert app.save("slot1")
    app.load("slot1")
    assert app.active_modal() == "gameover"
    app.modal = None


def test_escape_closes_info_modals(app):
    """QA: 도움말·로그·랭킹·특산물·저장 슬롯·외교 창은 Esc로 닫힌다."""
    g = _main_game(app, n_enemies=1)
    other = next(f.id for f in g.factions if f.id != g.player_id)
    for open_ in (lambda: setattr(app, "modal", ("help", None)), lambda: setattr(app, "modal", ("log", None)),
                  lambda: setattr(app, "modal", ("ranking", None)), lambda: setattr(app, "modal", ("specialty", None)),
                  lambda: app.open_slots("save"), lambda: app.open_diplomacy(other)):
        open_()
        frame(app)
        _key(app, pygame.K_ESCAPE)
        assert app.modal is None


def test_diplomacy_modal_war_needs_confirm(app):
    """QA: 외교 창의 [선전포고]도 측면 패널처럼 한 번 더 눌러야 선포된다."""
    from korciv import diplomacy as D
    g = _main_game(app, n_enemies=1)
    pid = g.player_id
    other = next(f.id for f in g.factions if f.id != pid)
    app.open_diplomacy(other)
    btn = {}
    real_button = app.gui.button

    def spy(rect, label, *a, **k):
        btn[label] = rect
        return real_button(rect, label, *a, **k)
    app.gui.button = spy
    try:
        frame(app)

        def click(label):
            r = pygame.Rect(btn[label])
            u = app.gui.u
            pos = (int(r.centerx * u), int(r.centery * u))
            old = pygame.mouse.get_pos
            pygame.mouse.get_pos = lambda: pos
            try:
                app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)])
                app.frame()
            finally:
                pygame.mouse.get_pos = old
        click("선전포고")
        assert not D.at_war(g, pid, other)
        frame(app)
        click("선전포고 확정")
        assert D.at_war(g, pid, other)
    finally:
        app.gui.button = real_button
        app.modal = None


def _click_button(app, label, frames_before=1):
    """이번 프레임에 그려진 버튼 중 label 인 것을 실제 마우스 이벤트로 누른다. 눌렀으면 True."""
    btn = {}
    real_button = app.gui.button

    def spy(rect, lab, *a, **k):
        ok = real_button(rect, lab, *a, **k)
        btn.setdefault(lab, (rect, k.get("enabled", a[1] if len(a) > 1 else True)))
        return ok
    app.gui.button = spy
    try:
        for _ in range(frames_before):
            frame(app)
        if label not in btn:
            return False
        r = pygame.Rect(btn[label][0])
        u = app.gui.u
        pos = (int(r.centerx * u), int(r.centery * u))
        old = pygame.mouse.get_pos
        pygame.mouse.get_pos = lambda: pos
        try:
            app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)])
            app.frame()
        finally:
            pygame.mouse.get_pos = old
        return True
    finally:
        app.gui.button = real_button


def test_counter_offer_blocked_when_money_short(app):
    """리뷰 C-02 보강: 수정안을 받은 뒤 자금이 모자라게 되면 [수정안 수락]이 막혀 거래가 실행되지 않는다."""
    from korciv import diplomacy as D
    g = _main_game(app, n_enemies=1)
    pid = g.player_id
    other = next(f.id for f in g.factions if f.id != pid)
    g.player.money = 5000
    g.factions[other].money = 5000
    app.open_diplomacy(other)
    ds = app.dip_state
    ds.counter = {"give": D.empty_offer()["give"] | {"money": 1100},
                  "take": D.empty_offer()["take"] | {"money": 1000}}
    g.player.money = 500                                      # 수정안 요구액(1100)보다 적다
    _click_button(app, "수정안 수락")
    assert g.player.money == 500 and g.factions[other].money == 5000 and ds.counter is not None
    g.player.money = 5000                                     # 자금이 충분하면 그대로 수락된다
    assert _click_button(app, "수정안 수락")
    assert g.player.money == 5000 - 1100 + 1000 and ds.counter is None
    app.modal = None


def test_rebellion_accept_refreshes_map(app):
    """리뷰 M-01: 반란 '요구 수용'(v1.3.0부터 돈 지급만) 뒤 행복도 지도를 다시 그린다(진압과 같게)."""
    g = _main_game(app, n_enemies=1)
    cap = g.player.capital
    g.player.money = 10 ** 6
    for label in ("요구 수용", "요구 수용"):
        g.regions[cap].happy = -80
        g.pending_rebellions.append(cap)
        v0 = app.map.version
        btn = {}
        real_button = app.gui.button

        def spy(rect, lab, *a, **k):
            if label in lab:
                btn["r"] = rect
            return real_button(rect, lab, *a, **k)
        app.gui.button = spy
        try:
            frame(app)
            r = pygame.Rect(btn["r"])
            u = app.gui.u
            pos = (int(r.centerx * u), int(r.centery * u))
            old = pygame.mouse.get_pos
            pygame.mouse.get_pos = lambda: pos
            try:
                app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)])
                app.frame()
            finally:
                pygame.mouse.get_pos = old
        finally:
            app.gui.button = real_button
        assert not g.pending_rebellions and g.regions[cap].happy > -80
        assert app.map.version > v0


def test_malformed_save_does_not_break_title_or_slots(app, monkeypatch, tmp_path):
    """리뷰 M-03: 버전은 맞지만 내용이 게임이 아닌 저장 파일은 그 슬롯만 비어 있는 것으로 보고, 시작 화면·슬롯 창은 그대로."""
    import pickle
    from korciv.ui import app as A
    from korciv.version import VERSION
    monkeypatch.setattr(A, "SAVE_DIR", str(tmp_path))
    for i, payload in enumerate(("망가진 데이터", {"player": 1}), start=1):
        with open(tmp_path / f"slot{i}.sav", "wb") as f:
            pickle.dump({"version": VERSION, "game": payload}, f)
    app.game = None
    app.modal = None
    app.scene = "title"
    frame(app)                                                # 시작 화면([이어하기] 줄)이 예외 없이 그려진다
    app.open_slots("load")
    frame(app)
    assert app.slot_cache[1] is None and app.slot_cache[2] is None
    app.modal = None


def test_save_failure_keeps_previous_save(app, monkeypatch, tmp_path):
    """리뷰 C-10 보강: 저장 중 오류가 나면 알림만 띄우고, 같은 슬롯의 예전 저장은 그대로 남는다."""
    import pickle
    from korciv.ui import app as A
    monkeypatch.setattr(A, "SAVE_DIR", str(tmp_path))
    g = _main_game(app, n_enemies=1)
    assert app.save("slot1")
    before = (tmp_path / "slot1.sav").read_bytes()

    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(pickle, "dump", boom)
    assert app.save("slot1") is False
    assert (tmp_path / "slot1.sav").read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))
    loaded, _ = A.App.read_save(str(tmp_path / "slot1.sav"))
    assert loaded is not None and loaded.turn == g.turn


def test_game_over_load_with_pending_popups(app, monkeypatch, tmp_path):
    """리뷰 C-10 보강: 대사·제안이 남은 채로 끝난 판을 불러오면 그 창들을 먼저 보이고, 다 닫으면 결과 창이 뜬다."""
    from korciv.ui import app as A
    monkeypatch.setattr(A, "SAVE_DIR", str(tmp_path))
    g = _main_game(app, n_enemies=1)
    other = next(f.id for f in g.factions if f.id != g.player_id)
    g.game_over = True
    g.winner = ((g.player_id,), "conquest")
    g.dialogues = [{"kind": "victory", "fid": other, "turn": g.turn}]
    g.pending_proposals = [{"from": other, "kind": "nonaggr"}]
    assert app.save("slot1")
    app.load("slot1")
    g = app.game
    assert app.active_modal() == "dialogue"
    g.dialogues.clear()
    assert app.active_modal() == "proposal"
    g.pending_proposals.clear()
    assert app.active_modal() == "gameover"
    app.modal = None


def test_escape_with_quantity_window_closes_only_it(app):
    """리뷰 C-09 보강: 외교 창 위에 수량 창이 열려 있으면 Esc는 수량 창만 닫는다."""
    from korciv.ui import modals
    g = _main_game(app, n_enemies=1)
    other = next(f.id for f in g.factions if f.id != g.player_id)
    app.open_diplomacy(other)
    modals.open_qty(app, "돈", 1000, 0, lambda v: None)
    frame(app)
    _key(app, pygame.K_ESCAPE)
    assert app.qty is None and app.modal and app.modal[0] == "diplomacy"
    _key(app, pygame.K_ESCAPE)
    assert app.modal is None


def test_help_scroll_reaches_last_line(app):
    """리뷰 C-09 보강: 도움말은 끝까지 스크롤되고, 맨 아래에서 마지막 줄이 창 안에 보인다."""
    from korciv.ui import modals
    _main_game(app, n_enemies=1)
    app.modal = ("help", None)
    texts = []
    real_text = app.gui.text

    def spy(pos, s, *a, **k):
        r = real_text(pos, s, *a, **k)
        texts.append((str(s), r, app.gui._clip_stack[-1] if app.gui._clip_stack else None))
        return r
    app.gui.text = spy
    sw, sh = app.window.get_size()
    old = pygame.mouse.get_pos
    pygame.mouse.get_pos = lambda: (sw // 2, sh // 2)      # 도움말 글 위에서 휠
    try:
        frame(app)
        for _ in range(40):                                 # 휠을 끝까지 내린다
            app.gui.begin([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-3, flipped=False)])
            app.frame()
        texts.clear()
        frame(app)
    finally:
        app.gui.text = real_text
        pygame.mouse.get_pos = old
    last = modals.HELP.strip().splitlines()[-1].strip()
    hits = [(r, c) for s, r, c in texts if s and last.startswith(s.strip()[:10])]
    assert hits
    r, clip = hits[-1]
    assert clip is not None and clip.top <= r.top and r.bottom <= clip.bottom + 1
    app.modal = None


def test_cargo_panel_board_and_unload_buttons(app):
    """v1.3.0 화물칸: 함대 [부대] 탭에서 같은 항구 부대를 [승선]하고, 고른 수량만 [하선]한다(합치기와 따로)."""
    g = _main_game(app, n_enemies=1)
    pid = g.player_id
    port = next(r for r in g.world.order if g.world.regions[r].coastal and g.regions[r].owner == NEUTRAL)
    g.transfer_region(port, pid)
    g.regions[port].b["port"] = 1
    for a in list(g.armies_at(port)):
        g.remove_army(a)
    fl = g.new_army(pid, port, {"lst": 1})
    land = g.new_army(pid, port, {"inf": 3, "tank": 1})
    app.select(port)
    app.left_open, app.left_tab, app.tab = True, "region", "army"
    app.sel_army = fl.id
    assert _click_button(app, f"승선: 부대 #{land.id} {land.label()}")
    assert g.cargo_of(fl) == {"tank": 1, "inf": 3} and land.id not in g.armies
    app.sel_army = fl.id
    app.cargo_pick = {"fid": fl.id, "units": {"inf": 2, "tank": 0}}
    assert _click_button(app, "하선 (2)")
    assert g.cargo_of(fl) == {"tank": 1, "inf": 1}
    assert [a.units for a in g.armies_at(port, pid) if a.domain() == "land"] == [{"inf": 2}]


def test_right_click_moves_immediately(app):
    """v1.3.0: 우클릭 이동은 턴 종료를 기다리지 않고 바로 실행되고, 한 부대는 한 턴에 한 번만 움직인다."""
    g = _main_game(app, n_enemies=1)
    pid = g.player_id
    cap = g.player.capital
    dst = sorted(g.world.land_adj[cap])[0]
    g.transfer_region(dst, pid)
    for a in list(g.armies_at(dst)):
        g.remove_army(a)
    a = g.new_army(pid, cap, {"inf": 2})
    app.select(cap)
    app.sel_army = a.id
    t0 = g.turn
    app.right_click(dst, (300, 300))
    assert a.loc == dst and g.turn == t0 and g.army_acted(a.id) and app.sel == dst
    app.right_click(cap, (300, 300))
    assert a.loc == dst and "이미 행동" in app.toasts[-1][0]
    frame(app)


def test_artillery_right_click_opens_bombard_confirm(app):
    """v1.3.0: 포병 부대 우클릭 — 적 병력이 있으면 폭격 확인 창([폭격]으로 바로 폭격), 없으면 이동."""
    from korciv import diplomacy as D
    g = _main_game(app, n_enemies=1)
    pid = g.player_id
    other = next(f.id for f in g.factions if f.id != pid)
    cap = g.player.capital
    tgt, empty = sorted(g.world.land_adj[cap])[:2]
    for r in (tgt, empty):
        g.transfer_region(r, other)
        for a in list(g.armies_at(r)):
            g.remove_army(a)
    D.declare_war(g, pid, other)
    app.modal = None
    g.dialogues = []
    e = g.new_army(other, tgt, {"inf": 3})
    art = g.new_army(pid, cap, {"art": 2})
    app.select(cap)
    app.sel_army = art.id
    frame(app)
    app.right_click(tgt, (300, 300))
    assert app.modal and app.modal[0] == "bombard" and not g.army_acted(art.id)
    hp0 = e.hp_left("inf")
    assert _click_button(app, "폭격")
    assert app.modal is None and g.army_acted(art.id) and art.loc == cap
    assert e.id not in g.armies or e.hp_left("inf") < hp0
    # 다음 턴: 병력이 없는 적 땅은 이동(차지)
    art2 = g.new_army(pid, cap, {"art": 1})
    app.sel_army = art2.id
    app.right_click(empty, (300, 300))
    assert app.modal is None and art2.loc == empty
    frame(app)


def test_trade_negotiation_windows(app):
    """v1.3.0: AI 의 거래 제의는 협상 창 — 값을 불러 역제의를 받거나 상대 값을 수락한다. 외교 창에서 먼저 협상도 연다."""
    from korciv import diplomacy as D
    from korciv import negotiation as NG
    g = _main_game(app, n_enemies=1)
    pid = g.player_id
    other = next(f.id for f in g.factions if f.id != pid)
    g.dip.op[(other, pid)] = g.dip.op[(pid, other)] = 20.0
    g.regions[g.factions[other].capital].b.update(factory=0, power=0)
    g.regions[g.player.capital].b["factory"] = 3
    g.energy_mined = lambda fid: {"oil": 0, "coal": 6, "elec": 0} if fid == other else {"oil": 0, "coal": 0, "elec": 0}
    g._refresh_pools()
    st = NG.start(g, other, pid, "coal", 3, ai_sells=True, init="ai")
    assert st["status"] == "open"
    g.pending_proposals.append({"from": other, "kind": "trade", "res": "coal", "n": st["n"], "price": st["price"],
                                "sell": True, "nego": st})
    frame(app)
    assert app.active_modal() == "proposal"
    g.player.money = 10 ** 6
    assert _click_button(app, f"상대 값 수락 (개당 {st['price']:,.0f})")
    assert st["status"] == "done" and D.contracts_between(g, pid, other)
    assert _click_button(app, "닫기")
    assert not g.pending_proposals
    # 플레이어가 먼저: 외교 창 → [자원·특산물 협상] → [제안하기]
    D.update_turn(g)
    app.open_diplomacy(other)
    assert _click_button(app, "자원·특산물 협상")
    assert app.modal and app.modal[0] == "nego"
    assert _click_button(app, "제안하기")
    ui = app.nego
    assert ui["st"] is not None and ui["st"]["hist"]
    frame(app)
    assert _click_button(app, "그만두기") or _click_button(app, "닫기")
    assert app.modal and app.modal[0] == "diplomacy"


def test_map_mode_popup_click_not_stolen_by_panel_below(app):
    """v1.3.0: 하단 지도 메뉴 [자원] 세부 메뉴가 내정 탭 지출 우선순위의 [고정] 단추 위에 겹쳐 있어도
    세부 메뉴를 누르면 [고정]이 아니라 그 메뉴가 눌린다(먼저 그려지는 아래 패널이 클릭을 가로채지 않게)."""
    from korciv.ui.app import SUB_MODES
    app.start_game(Settings(seed=12, n_enemies=3, fog=1, player_start="S002"))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    g.pending_proposals.clear()
    g.pending_rebellions.clear()
    app.modal = None
    pid = g.player_id
    near = sorted({n for r in g.world.land_adj["S002"] for n in g.world.land_adj[r]} - {"S002"})[:14]
    for r in near:
        g.transfer_region(r, pid)
        g.regions[r].resist = None
    g.player.money = 10 ** 7
    for r in g.regions_of(pid):
        r.project = None
        g.start_project(pid, r.id, "unit", "inf")
    assert len(g.projects_by_priority(pid)) >= 10
    pins = []
    orig_pin = g.toggle_pin
    g.toggle_pin = lambda f, rid: pins.append(rid) or orig_pin(f, rid)
    app.left_open, app.left_tab = True, "nation"
    u = app.gui.u
    orig = pygame.mouse.get_pos
    try:
        for i, (key, *_r) in enumerate(SUB_MODES["resource"]):
            for fx in (0.3, 0.6, 0.92):
                app.mode, app.mode_popup = "resource", "resource"
                g.dialogues.clear()
                pop = app.mode_popup_rect()
                row = pygame.Rect(pop.x + 6, pop.y + 6 + i * (app.SUB_ROW_H + 4), app.SUB_W - 12, app.SUB_ROW_H)
                p = (int((row.x + row.w * fx) * u), int(row.centery * u))
                pygame.mouse.get_pos = lambda p=p: p
                frame(app)
                app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=p)]); app.frame()
                app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=p)]); app.frame()
                assert app.sub_modes.get("resource") == key, (key, fx)
        assert not pins
    finally:
        pygame.mouse.get_pos = orig
        g.toggle_pin = orig_pin


# ------------------------------------------------------------------ v1.3.0 편의성 개선
class _Spy:
    """gui.button·checkbox 를 감싸 그린 위치를 기억하고, 그 자리를 눌러 본다. draw() 는 기록을 비우고 한 프레임 그린다."""

    def __init__(self, app):
        self.app, self.rects = app, {}
        self.real_button, self.real_check = app.gui.button, app.gui.checkbox

        def button(rect, label, *a, **k):
            self.rects[label] = ("button", rect)
            return self.real_button(rect, label, *a, **k)

        def checkbox(rect, label, *a, **k):
            self.rects[label] = ("check", rect)
            return self.real_check(rect, label, *a, **k)
        app.gui.button, app.gui.checkbox = button, checkbox

    def close(self):
        self.app.gui.button, self.app.gui.checkbox = self.real_button, self.real_check

    def draw(self):
        self.rects = {}
        frame(self.app)

    def find(self, prefix):
        return next((k for k in self.rects if k.startswith(prefix)), None)

    def click(self, label):
        kind, rect = self.rects[label]
        r = pygame.Rect(rect)
        u = self.app.gui.u
        pos = (int((r.x + 9) * u) if kind == "check" else int(r.centerx * u), int(r.centery * u))
        old = pygame.mouse.get_pos
        pygame.mouse.get_pos = lambda: pos
        try:
            self.app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)])
            self.app.frame()
        finally:
            pygame.mouse.get_pos = old


def test_battle_modal_attacks_with_several_armies(app):
    """공격 확인 창에서 함께 공격할 부대를 고르면 한 전투로 합쳐 싸운다(협공 보너스)."""
    from korciv import diplomacy as D
    g = _main_game(app, seed=7, n_enemies=1, player_start="S002")
    w = g.world
    tgt = next(t for t in sorted(w.land_adj["S002"]) if any(n != "S002" for n in w.land_adj[t]))
    side = next(n for n in sorted(w.land_adj[tgt]) if n != "S002")
    g.transfer_region(side, 0)
    g.transfer_region(tgt, 1)
    for r in (tgt, side, "S002"):
        for a in list(g.armies_at(r)):
            g.remove_army(a)
    D.declare_war(g, 0, 1)
    g.dialogues = []
    g.new_army(1, tgt, {"inf": 5})
    a = g.new_army(0, "S002", {"inf": 4})
    b = g.new_army(0, side, {"inf": 4})
    app.select("S002")
    app.sel_army = a.id
    app.right_click(tgt, (500, 400))
    assert app.modal and app.modal[0] == "battle"
    spy = _Spy(app)
    try:
        spy.draw()
        st = app.modal[1]
        assert b.id in st["cands"]
        spy.click("모두")
        assert b.id in st["extra"]
        spy.draw()
        spy.click("전투")
    finally:
        spy.close()
    assert g.army_fought(a.id) or a.id not in g.armies
    assert g.army_fought(b.id) or b.id not in g.armies


def test_neutral_panel_annex_buttons_and_auto_disband(app):
    """내 땅과 맞닿은 중립 지역 [행동] 탭: [편입]·[최대 편입]·자동 해산 체크."""
    g = _main_game(app, seed=7, n_enemies=1, player_start="S002")
    w = g.world
    for n in sorted(w.land_adj["S002"]):
        if g.regions[n].owner == NEUTRAL:
            g.transfer_region(n, 0)
    g.player.money = 10 ** 6
    cand = {}
    for r in sorted(r for r in g.regions if g.regions[r].owner == 0):
        for n in w.land_adj[r]:
            if g.regions[n].owner == NEUTRAL:
                cand.setdefault(n, set()).add(r)
    tgt = max(sorted(cand), key=lambda n: len(cand[n]))
    app.left_open = False
    app.select(tgt)
    assert app.tab == "action"
    spy = _Spy(app)
    try:
        spy.draw()
        assert spy.find("최대 편입") and spy.find("편입 (")
        spy.click(spy.find("편입 ("))
        assert g.joint_count(0, tgt) == 1
        spy.draw()
        spy.click(spy.find("최대 편입"))
        assert g.joint_count(0, tgt) >= 2 and not g.annex_sources(0, tgt)
        spy.draw()
        spy.click("자동 해산")
        assert tgt in g.player.annex_disband
        # 내정 탭 지출 우선순위: 같은 대상 편입은 한 줄
        app.left_tab = "nation"
        spy.draw()
    finally:
        spy.close()
    rows = g.priority_rows(0)
    assert sum(1 for row in rows if row[0].project.kind == "annex" and row[0].project.key == tgt) == 1


def test_diplomacy_trade_reject_checkboxes(app):
    """외교 탭 하단 '모든 구매/판매 제의 거절', 국가 상세의 '이 국가의 거래 제의 거절'."""
    g = _main_game(app, seed=7, n_enemies=2)
    app.left_open, app.left_tab, app.dip_view = True, "diplo", None
    spy = _Spy(app)
    try:
        spy.draw()
        spy.click("모든 구매 제의 거절")
        assert g.player.ai.get("reject_buy") is True and not g.player.ai.get("reject_sell")
        spy.draw()
        spy.click("모든 판매 제의 거절")
        assert g.player.ai.get("reject_sell") is True
        other = next(f.id for f in g.factions if f.id != g.player_id and f.alive)
        app.dip_view = other
        spy.draw()
        spy.click("이 국가의 거래 제의 거절")
        assert other in g.player.ai["reject_from"]
        spy.draw()
        spy.click("이 국가의 거래 제의 거절")
        assert other not in g.player.ai["reject_from"]
    finally:
        spy.close()


def test_tab_shortcuts_and_flag_click(app):
    """Space 로 [행동]→[부대]→[지역 정보], Q/W/E 로 바로 가기. 지도 위 군기를 누르면 그 부대의 [부대] 탭."""
    g = _main_game(app, seed=7, n_enemies=1, player_start="S002")
    app.select("S002")
    app.tab = "action"
    _key(app, pygame.K_SPACE)
    assert app.tab == "army"
    _key(app, pygame.K_SPACE)
    assert app.tab == "info"
    _key(app, pygame.K_SPACE)
    assert app.tab == "action"
    _key(app, pygame.K_e)
    assert app.tab == "info"
    _key(app, pygame.K_w)
    assert app.tab == "army"
    _key(app, pygame.K_q)
    assert app.tab == "action"
    # 군기 클릭
    app.map.center_on("S002", zoom=6.0)
    app.map.invalidate()
    extra = g.new_army(0, "S002", {"tank": 2})
    app.tab = "info"
    frame(app)
    hits = [h for h in app._flag_hits if h[1] == extra.id]
    assert hits
    pos = hits[0][0].center
    old = pygame.mouse.get_pos
    pygame.mouse.get_pos = lambda: pos
    try:
        app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)]); app.frame()
        app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)]); app.frame()
    finally:
        pygame.mouse.get_pos = old
    assert app.tab == "army" and app.sel_army == extra.id and app.left_open


def test_split_stepper_has_big_steps(app):
    """병력이 많으면 분리·해산 수량을 ±5·±10 으로도 조절한다."""
    g = _main_game(app, seed=7, n_enemies=1, player_start="S002")
    a = g.new_army(0, "S002", {"inf": 30})
    app.select("S002")
    app.sel_army = a.id
    app.left_open, app.left_tab, app.tab = True, "region", "army"
    app.split = {}
    spy = _Spy(app)
    try:
        spy.draw()
        spy.click("+10")
        assert app.split.get("inf") == 10
        spy.draw()
        spy.click("+5")
        assert app.split.get("inf") == 15
        spy.draw()
        spy.click("−10")
        assert app.split.get("inf") == 5
    finally:
        spy.close()


def test_rally_pick_flow(app):
    """[생산 집결지 지정] → 지도에서 내 지역 클릭. Esc·우클릭·[취소]로 그만둔다. 군사 탭 [일괄 지정]."""
    g = _main_game(app, seed=7, n_enemies=1, player_start="S002")
    dest = sorted(g.world.land_adj["S002"])[0]
    g.transfer_region(dest, 0)
    app.select("S002")
    app.left_open, app.left_tab, app.tab = True, "region", "army"
    spy = _Spy(app)
    try:
        spy.draw()
        spy.click("생산 집결지 지정")
        assert app.rally_pick == "S002"
        frame(app)                                   # 안내 띠
        _key(app, pygame.K_ESCAPE)
        assert app.rally_pick is None
        app.start_rally_pick("S002")
        app.right_click(dest, (400, 300))
        assert app.rally_pick is None
        app.start_rally_pick("S002")
        spy.draw()
        spy.click("취소 (Esc)")
        assert app.rally_pick is None
        app.start_rally_pick("S002")
        app.finish_rally_pick(dest)
        assert g.regions["S002"].rally == dest
        app.left_open, app.left_tab = True, "army"
        spy.draw()
        spy.click("일괄 지정")
        assert app.rally_pick == "*"
        app.finish_rally_pick("S002")
        assert g.player.rally == "S002" and g.regions["S002"].rally is None
        frame(app)                                   # 집결지 깃발 표시
    finally:
        spy.close()


def _click_map(app, rid):
    pos = tuple(int(v) for v in app.map.label_screen(rid))
    old = pygame.mouse.get_pos
    pygame.mouse.get_pos = lambda: pos
    try:
        app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)]); app.frame()
        app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)]); app.frame()
    finally:
        pygame.mouse.get_pos = old


def test_metro_designation_by_clicking_map(app):
    """v1.3.0: [광역자치단체 지정] → 지도에서 육상 3칸 안의 내 지역을 눌러 넣고 빼고, Enter 로 지정(Esc 취소).
    광역시 행동 탭의 편입 선택지는 줄어든 턴 수를 보여 준다."""
    from korciv import metro as M
    g = _main_game(app, seed=7, n_enemies=1, player_start="S002")
    nb = sorted(g.world.land_adj["S002"])[:3]
    for r in nb:
        g.transfer_region(r, 0)
    for r in ["S002"] + nb:
        rr = g.regions[r]
        rr.resist, rr.project, rr.happy = None, None, 10.0
        rr.b["farm"] = 5
        rr.b["admin"] = 5 if r == g.player.capital else 4
        rr.pop = min(rr.pop, 45)
    g.regions["S002"].b["factory"] = 5
    g.regions[nb[0]].b["bank"] = 5
    g.player.money = 10 ** 7
    app.select("S002")
    app.left_open, app.left_tab, app.tab = True, "region", "action"
    spy = _Spy(app)
    try:
        spy.draw()
        spy.click("광역자치단체 지정")
    finally:
        spy.close()
    assert app.metro_pick and app.metro_pick["center"] == "S002" and app.modal is None
    frame(app)
    _key(app, pygame.K_ESCAPE)                                    # Esc: 취소
    assert app.metro_pick is None
    app.start_metro_pick("S002")
    frame(app)
    far = next(r for r in g.regions if g.regions[r].owner != 0 and r not in M.distances(g, "S002", C.METRO_RANGE))
    app.toggle_metro_pick(far)                                     # 고를 수 없는 곳은 무시
    assert not app.metro_pick["sel"]
    for r in nb:
        _click_map(app, r)
    assert app.metro_pick["sel"] == set(nb)
    _click_map(app, nb[2])                                         # 다시 누르면 뺀다
    assert app.metro_pick["sel"] == set(nb[:2])
    _click_map(app, nb[2])
    t0 = g.turn
    _key(app, pygame.K_RETURN)                                     # Enter: 지정(턴 종료로 넘어가지 않는다)
    assert g.turn == t0 and app.metro_pick is None
    m = M.of(g, "S002")
    assert m and set(m["members"]) == {"S002", *nb}
    assert app.sel == "S002" and app.tab == "action"
    spy = _Spy(app)
    try:
        spy.draw()
    finally:
        spy.close()
    o = next(o for o in g.options(0, "S002") if o["kind"] == "annex")
    assert o["eff_turns"] < o["turns"]


def test_metro_pick_limit_25_and_drawn_as_one_region(app):
    """v1.3.0: [모두]는 가까운 25곳까지, 지도에서 더 누르면 거절. 지정한 광역시는 바깥 윤곽만 긋고
    구성 지역 사이 경계는 바탕 지도에서도 긋지 않는다(하나의 지역처럼)."""
    from korciv import metro as M
    from korciv.ui import mapview as MV
    g = _main_game(app, seed=7, n_enemies=1, player_start="S002")
    d = M.distances(g, "S002", C.METRO_RANGE)
    for r in d:
        if r != "S002":
            g.transfer_region(r, 0)
        rr = g.regions[r]
        rr.resist, rr.project, rr.happy, rr.occ = None, None, 10.0, None
        rr.b["farm"] = 5
        rr.b["admin"] = 5 if r == g.player.capital else 4
        rr.pop = min(rr.pop, 45)
    g.regions["S002"].b["factory"] = 5
    g.regions["S002"].b["bank"] = 5
    g.player.money = 10 ** 7
    g._update_fog()                                                # 넘겨받은 땅도 지금 시야로(국경선이 남지 않게)
    app.start_metro_pick("S002")
    spy = _Spy(app)
    try:
        spy.draw()
        label = spy.find("모두")
        assert label == f"모두 ({C.METRO_MAX_REGIONS - 1}곳)"
        spy.click(label)
    finally:
        spy.close()
    sel = app.metro_pick["sel"]
    assert len(sel) == C.METRO_MAX_REGIONS - 1
    rest = next(r for r in M.candidates(g, 0, "S002") if r not in sel and r != "S002")
    app.toggle_metro_pick(rest)                                    # 26번째는 넣지 않는다
    assert rest not in app.metro_pick["sel"] and len(app.metro_pick["sel"]) == C.METRO_MAX_REGIONS - 1
    assert "25곳까지" in app.toasts[-1][0]
    frame(app)
    assert app.confirm_metro_pick()
    m = M.of(g, "S002")
    mem = set(m["members"])
    assert len(mem) == C.METRO_MAX_REGIONS
    # 바탕 지도: 구성 지역들은 같은 광역시 번호 → 그 사이 경계는 긋지 않는다
    ex = app.map_extra()
    assert {r for r, mid in ex["metro"].items() if mid == m["id"]} == mem
    mv = app.map
    inner = [i for i, (a_, b_, _) in enumerate(mv.pair_lines) if a_ in mem and b_ in mem]
    assert inner
    spans, boxes = mv._group_chains(m["members"])
    want = ({mv.pair_span[i][2] for i, (a_, b_, _) in enumerate(mv.pair_lines) if (a_ in mem) != (b_ in mem)}
            | {sp for r_, sp in mv.coast_span if r_ in mem})
    assert set(spans) == want and len(boxes) == len(spans)
    assert not {mv.pair_span[i][2] for i in inner} & set(spans)
    # 그리는 선을 가로채 안쪽 경계 사슬이 그려지지 않는지 본다
    app.fit_regions(m["members"])
    drawn = []
    real = pygame.draw.lines

    def spy_lines(surf, color, closed, pts, width=1):
        drawn.append(tuple((round(x, 1), round(y, 1)) for x, y in pts))
        return real(surf, color, closed, pts, width)
    pygame.draw.lines = spy_lines
    try:
        # 지형(하천·산맥)은 지역 경계를 따라 그대로 그리므로 빼고 본다
        mv._render(("t",), app.theme, app.region_colors(), app.sea_colors(), app.mode, app.map_labels(), False, ex)
        no_metro = dict(ex, metro={})
        n_with = len(drawn)
        mv._render(("t2",), app.theme, app.region_colors(), app.sea_colors(), app.mode, app.map_labels(), False,
                   no_metro)
    finally:
        pygame.draw.lines = real
    s = mv.scale
    ox, oy = mv.offset()
    ox += int(mv.view.w * MV.CACHE_MARGIN) - mv.view.x
    oy += int(mv.view.h * MV.CACHE_MARGIN) - mv.view.y

    def chain(i):
        a0, a1 = mv.pair_span[i][2]
        return tuple((round(x, 1), round(y, 1)) for x, y in (mv.verts[a0:a1] * s + (ox, oy)).tolist())
    inner_pts = {chain(i) for i in inner}
    assert not inner_pts & set(drawn[:n_with])                     # 광역시가 있으면 안쪽 경계를 긋지 않고
    assert inner_pts & set(drawn[n_with:])                         # 없으면(예전처럼) 긋는다
    frame(app)                                                     # 바깥 윤곽·선택 윤곽을 그려도 멈추지 않는다
    app.select(sorted(mem - {"S002"})[0])
    frame(app)


def test_metro_button_disabled_when_impossible(app):
    """조건을 채울 수 없는 지역에서는 [광역자치단체 지정]이 비활성(눌러도 지정 화면이 열리지 않는다)."""
    g = _main_game(app, seed=7, n_enemies=1, player_start="S002")
    app.select("S002")
    app.left_open, app.left_tab, app.tab = True, "region", "action"
    spy = _Spy(app)
    try:
        spy.draw()
        assert "광역자치단체 지정" in spy.rects
        spy.click("광역자치단체 지정")
    finally:
        spy.close()
    assert app.metro_pick is None


def test_fullscreen_toggle_does_not_minimize(app, monkeypatch):
    """v1.3.3: 창 모드에서 Alt+Enter 로 전체화면 전환 시 최소화되던 문제.
    ① 포커스를 잠깐 잃어도 SDL 이 전체화면 창을 최소화하지 않게 하고, ② 전환 직후 잠깐은 지도를 다시 그리지 않고
    지난 그림을 늘려 보여 주며(창이 먼저 응답), ③ 그래도 전환 직후 최소화되면 바로 되살린다."""
    import os
    assert os.environ.get("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS") == "0"
    _main_game(app, seed=3, n_enemies=1, player_start="S002")
    frame(app)
    # Alt+Enter 는 전체화면 전환으로만 쓰이고 턴 종료 등으로 넘어가지 않는다
    calls = []
    monkeypatch.setattr(app, "set_fullscreen", lambda on, save=True: calls.append(on))
    monkeypatch.setattr(app, "is_fullscreen", lambda: False)
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=pygame.KMOD_LALT, unicode="\r", scancode=0)
    assert app.system_event(ev) and calls == [True]
    assert not app.system_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="\r",
                                                   scancode=0))
    # 지도 다시 그리기 미루기: 미루는 동안은 지난 그림, 시간이 지나면 다시 그린다
    mv = app.map
    renders = []
    real = mv._render
    monkeypatch.setattr(mv, "_render", lambda *a, **k: (renders.append(1), real(*a, **k)))
    now = [pygame.time.get_ticks()]
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: now[0])
    mv.defer(400)
    mv.invalidate()
    frame(app)
    assert renders == []
    now[0] += 500
    frame(app)
    assert renders == [1]
    # 전환 직후(1.5초 안) 최소화되면 되살리고, 한참 뒤 사용자가 최소화한 것은 그대로 둔다
    restored = []
    monkeypatch.setattr(app, "restore_window", lambda: restored.append(1))
    monkeypatch.setattr(app, "is_fullscreen", lambda: True)
    app.mode_switch_t = now[0]
    now[0] += 300
    app.system_event(pygame.event.Event(pygame.WINDOWMINIMIZED))
    assert restored == [1]
    now[0] += 5000
    app.system_event(pygame.event.Event(pygame.WINDOWMINIMIZED))
    assert restored == [1]


def test_v136_mode_order_leader_tip_and_pop_focus_rate(app, monkeypatch):
    """v1.3.6: ① 개척시대가 맨 앞·기본 선택, '기본모드' → '현실' ② 지도자 툴팁은 '버프'·'디버프' 글자 없이
    효과 이름을 초록·빨강으로 ③ 인구 성장 집중 성장률은 소수점 둘째 자리까지."""
    import re
    from korciv.leaders import LEADER_BY_KEY
    from korciv.ui import modals as MO
    assert list(C.GAME_MODES) == ["frontier", "standard", "chaos"]
    assert C.GAME_MODES["standard"] == "현실" and "기본모드" not in C.GAME_MODES.values()
    assert MO.SetupState().mode == "frontier"
    t = app.theme
    tip = MO.leader_tip(LEADER_BY_KEY["dan"], t)
    flat = " ".join(s for line in tip for s, _ in line)
    assert "버프" not in flat and "디버프" not in flat
    assert tip[1][0] == (LEADER_BY_KEY["dan"]["buff"][0], t.good)
    assert tip[2][0] == (LEADER_BY_KEY["dan"]["debuff"][0], t.bad)
    assert len(MO.leader_tip(LEADER_BY_KEY["kgu"], t)) == 3          # v1.3.7: 망명 정부 디버프 추가
    assert len(MO.leader_tip(LEADER_BY_KEY["cus"], t)) == 1          # 효과 없음: 줄째 뺀다
    app.gui.tooltip = tip                                            # 조각마다 색이 다른 툴팁도 그려진다
    app.gui.draw_tooltip()
    # 인구 성장 집중: 0.236361 → 0.24
    g = _main_game(app, seed=3, n_enemies=1, player_start="S002")
    monkeypatch.setattr(g, "growth_scale", lambda rid: 0.945444)
    app.select("S002")
    app.left_open, app.left_tab, app.tab = True, "region", "action"
    spy = _Spy(app)
    try:
        spy.draw()
        label = spy.find("인구 성장 집중")
    finally:
        spy.close()
    assert label == "인구 성장 집중 (+0.24%p/턴)", label
    assert not re.search(r"\d\.\d{3}", label)


# ------------------------------------------------------------------ v1.3.12 지도 메뉴(오른쪽 아래)·부대 카드
def _click_at(app, lp):
    """논리 좌표 lp 를 한 번 눌렀다 뗀다(마우스를 그 자리에 둔 채)."""
    u = app.gui.u
    p = (int(lp[0] * u), int(lp[1] * u))
    pygame.mouse.get_pos = lambda: p
    frame(app)
    app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=p)]); app.frame()
    app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=p)]); app.frame()


def test_map_menu_bottom_right_vertical(app):
    """지도 모드는 오른쪽 아래 작은 창에 세로로: 줄을 누르면 모드가 바뀌고, 자원·건물·군사 세부 메뉴는 창 왼쪽에 펼친다."""
    _main_game(app)
    sw, sh = app.lsize()
    win, rows, terr = app._map_menu_layout()
    assert win.right <= sw - 8 and win.x > sw / 2 and win.y > sh / 3          # 오른쪽 아래
    assert all(r.x == rows[0].x and r.y > p.y for r, p in zip(rows[1:], rows))  # 세로 한 줄
    orig = pygame.mouse.get_pos
    try:
        _click_at(app, rows[1].center)
        assert app.mode == "happy"
        i = [k for k, _ in MAP_MODES].index("resource")
        _click_at(app, rows[i].center)
        assert app.mode == "resource" and app.mode_popup == "resource"
        pop = app.mode_popup_rect()
        assert pop.right <= win.x and pop.top >= 56 and pop.bottom <= sh       # 창 왼쪽, 화면 안
        _click_at(app, (pop.x + 30, pop.y + 6 + 1 * (app.SUB_ROW_H + 4) + 10))  # 두 번째 세부 항목
        from korciv.ui.app import SUB_MODES
        assert app.sub_modes.get("resource") == SUB_MODES["resource"][1][0] and app.mode_popup is None
    finally:
        pygame.mouse.get_pos = orig


def test_army_cards_fan_hover_and_pick(app):
    """지역을 누르면 그 지역 부대가 왼쪽 아래 카드로 펼쳐지고, 커서를 올린 카드는 위로 올라오며, 누르면 그 부대를 고른다."""
    from korciv.state import Army
    g = _main_game(app, seed=5, n_enemies=1)
    pid = g.player_id
    cap = g.player.capital
    for units in ({"inf": 3}, {"tank": 2, "inf": 1}, {"art": 2}):
        nid = max(g.armies) + 1
        g.armies[nid] = Army(nid, pid, cap, dict(units))
    app.select(cap)
    here = [a.id for a in g.armies_at(cap) if not a.empty()]
    frame(app)
    for c in app.hand.cards:                     # 올라오는 애니메이션을 건너뛴다
        c.appear, c.born = 1.0, 0
    frame(app)
    assert sorted(aid for _, aid in app.hand.rects) == sorted(here)
    sw, sh = app.lsize()
    rects = sorted(app.hand.rects, key=lambda x: x[0].x)
    assert all(r.x < sw / 2 and r.y > sh - 100 for r, _ in rects)            # 왼쪽 아래에 비죽
    target = next(aid for _, aid in rects if aid != app.sel_army)
    r = next(r for r, aid in rects if aid == target)
    orig = pygame.mouse.get_pos
    try:
        u = app.gui.u
        p = (int((r.x + 8) * u), int((r.y + 16) * u))
        pygame.mouse.get_pos = lambda: p
        for _ in range(12):                       # 커서를 올려 두면 카드가 위로 올라온다
            frame(app)
        card = next(c for c in app.hand.cards if c.aid == target)
        assert app.hand.hover == target and card.lift > 0.3
        lifted = next(rr for rr, aid in app.hand.rects if aid == target)
        assert lifted.y < r.y - 20
        app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=p)]); app.frame()
        app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=p)]); app.frame()
        assert app.sel_army == target and app.sel == cap                     # 지도는 눌리지 않는다
        assert app.left_open and app.left_tab == "region" and app.tab == "army"
        pygame.mouse.get_pos = lambda: (int(sw * u / 2), int(sh * u / 2))
        for _ in range(12):                       # 커서를 떼면 제자리로
            frame(app)
        assert app.hand.hover is None and card.lift < 0.3
    finally:
        pygame.mouse.get_pos = orig
    app.select(None)
    frame(app)
    assert app.hand.rects == []                  # 선택을 풀면 카드는 내려간다


# ------------------------------------------------------------------ v1.3.15 누른 곳·뗀 곳이 다르면 클릭이 아님, 우선순위 → 지역 행동 탭
def _rail_tab_rects(app):
    from korciv.ui import panels
    from korciv.ui.app import TOP_H
    out, y = {}, TOP_H + 12
    for k, label, _ in panels.SIDE_TABS:
        r = pygame.Rect(8, y, panels.RAIL_W, 22 + len(label.replace("\n", "")) * 19)
        out[k] = r
        y = r.bottom + 7
    return out


def test_press_drag_release_on_other_button_is_not_click(app, monkeypatch):
    """[내정]을 눌러 아래로 끌고 와 [군사]에서 떼면 아무 탭도 열리지 않고 지도도 움직이지 않는다."""
    _main_game(app)
    app.left_open, app.left_tab = False, "policy"
    frame(app)
    tabs = _rail_tab_rects(app)
    u = app.gui.u
    a, b = tabs["nation"].center, tabs["army"].center
    cx, cy, sel = app.map.cx, app.map.cy, app.sel
    state = {"p": (int(a[0] * u), int(a[1] * u)), "down": False, "rel": (0, 0)}
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: state["p"])
    monkeypatch.setattr(pygame.mouse, "get_pressed", lambda *a_: (state["down"], False, False))
    monkeypatch.setattr(pygame.mouse, "get_rel", lambda: state["rel"])
    app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=state["p"])]); state["down"] = True
    app.frame()
    steps = 12
    for i in range(1, steps + 1):                 # 탭 사이 빈틈(지도 위)을 지나 [군사]까지
        y = a[1] + (b[1] - a[1]) * i / steps
        prev = state["p"]
        state["p"] = (int(a[0] * u), int(y * u))
        state["rel"] = (state["p"][0] - prev[0], state["p"][1] - prev[1])
        frame(app)
    state["down"], state["rel"] = False, (0, 0)
    app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=state["p"])]); app.frame()
    assert not app.left_open and app.left_tab == "policy"        # [군사]가 열리지 않는다
    assert (app.map.cx, app.map.cy) == (cx, cy) and app.sel == sel   # 지도는 끌리지도, 눌리지도 않는다
    # 같은 버튼에서 누르고 떼면 평소처럼 눌린다
    _click_at(app, b)
    assert app.left_open and app.left_tab == "army"


def test_map_drag_released_over_button_does_not_press_it(app, monkeypatch):
    """지도에서 눌러 끌다가 왼쪽 세로 탭 위에서 떼도 그 탭은 눌리지 않는다."""
    _main_game(app)
    app.left_open, app.left_tab = False, "policy"
    frame(app)
    tab = _rail_tab_rects(app)["diplo"]
    u = app.gui.u
    start = (600, 400)
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (int(start[0] * u), int(start[1] * u)))
    app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(int(start[0] * u), int(start[1] * u)))])
    app.frame()
    p = (int(tab.centerx * u), int(tab.centery * u))
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: p)
    frame(app)
    app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=p)]); app.frame()
    assert not app.left_open


def test_priority_row_click_opens_region_action_tab(app, monkeypatch):
    """[내정] 지출 우선순위에서 행을 누르면 그 지역을 고르고 [행동] 탭을 연다(끌기·≡ 고르기는 그대로)."""
    from korciv.ui import panels
    g = _main_game(app, seed=4, n_enemies=3)
    pid = g.player_id
    near = sorted(g.world.land_adj[g.player.capital])[:2]
    for r in near:
        g.transfer_region(r, pid)
        g.regions[r].resist = None
    for r in [g.player.capital] + near:
        assert g.start_project(pid, r, "build", "farm")[0]
    ids = [r.id for r in g.projects_by_priority(pid)]
    spots = []
    real = panels.draw_priority_list

    def spy(app_, x, y, w, items):
        spots.append((x, y, w))
        return real(app_, x, y, w, items)
    monkeypatch.setattr(panels, "draw_priority_list", spy)
    app.left_open, app.left_tab = True, "nation"
    frame(app)
    x, y, w = spots[-1]
    sh = app.lsize()[1]
    app.gui.scroll["nation"] = max(0, y + 44 * 2 - (sh - 140))   # 목록이 화면 아래에 있으면 끌어올린다
    spots.clear()
    frame(app)
    x, y, w = spots[-1]
    row = pygame.Rect(x, y + 44 * 1, w, 40)
    orig = pygame.mouse.get_pos
    try:
        _click_at(app, (row.right - 12, row.centery))           # ≡: 그 행을 고른다(↑↓로 이동)
        assert app.prio_sel == ids[1] and app.left_tab == "nation"
        _click_at(app, (row.x + 40, row.centery))               # 행: 그 지역 [행동] 탭
        assert app.sel == ids[1] and app.left_open and app.left_tab == "region" and app.tab == "action"
        assert [r.id for r in g.projects_by_priority(pid)] == ids  # 순서는 그대로
    finally:
        pygame.mouse.get_pos = orig
