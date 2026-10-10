"""pygame 앱: 장면 전환, 메인 루프, 지도 상호작용, 상단 바."""
from __future__ import annotations

import math
import os
import pickle
import sys

import pygame

from .. import config as C
from .. import diplomacy as D
from ..data import SEA_NAMES, load_world
from ..game import Game, initial_buildings
from ..leaders import LEADER_BY_KEY
from ..state import NEUTRAL, Army, Settings
from ..version import VERSION, compatible
from . import modals, panels
from .gui import Gui
from .mapview import MapView
from .theme import Theme, desaturate, fmt_money, hex2rgb, measure, mix, render_text, set_ui_scale, ui_scale

SAVE_DIR = os.path.join(os.path.expanduser("~"), ".korciv", "saves")
TOP_H = 56
LEFT_W = 360
RIGHT_W = 320
MAP_MODES = [("political", "정치"), ("happy", "행복도"), ("pop", "인구"), ("resource", "자원"),
             ("building", "건물"), ("military", "군사"), ("opinion", "우호도")]
MODE_ICONS = {"political": "flag", "happy": "face", "pop": "people", "resource": "coal", "building": "hammer",
              "military": "shield", "opinion": "scroll"}
# 자원·건물·군사 모드는 누르면 위로 세부 메뉴가 펼쳐지고, 고른 한 가지만 지도에 표시한다.
# (키, 이름, 색, 최대 단계 또는 None=단계 없음)
SUB_MODES = {
    "resource": [("specialty", "특산물", "#2B8A3E", 3), ("coal", "석탄", "#6F4E37", 5), ("oil", "석유", "#000000", 6),
                 ("scenic", "자연경관", "#0CA678", None), ("dam", "댐", "#1971C2", None), ("nuclear", "원전", "#F08C00", None)],
    "building": [("farm", "농장", "#B5803A", 5), ("fishery", "어장", "#1C7ED6", 5), ("factory", "공장", "#E8590C", 5),
                 ("bank", "은행", "#2F9E44", 5), ("power", "발전소", "#FAB005", 5)],
    "military": [("line", "방어선", "#C92A2A", 5), ("aa", "대공포", "#7048E8", 5), ("shelter", "방공호", "#5C940D", 5),
                 ("academy", "사관학교", "#E67700", None), ("airport", "공항", "#1864AB", None),
                 ("port", "항구", "#0C8599", None)],
}


def _dpi_aware():
    """Windows 화면 배율 때문에 창이 확대돼 모니터 밖으로 넘치지 않도록 실제 픽셀 단위를 쓴다."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# 명령 화살표 색(기존 색) — 얇은 흰 테두리로 영토 색과 구분
ORDER_COLORS = {"move": (47, 111, 222), "attack": (201, 42, 42), "land": (12, 166, 120), "bombard": (230, 119, 0)}


class App:
    def __init__(self, width=None, height=None, screenshot=None):
        _dpi_aware()
        pygame.init()
        pygame.display.set_caption("한반도의 문명")
        flags = pygame.RESIZABLE
        # 모니터 크기에 맞춰 크게 연다(최대화하면 UI 전체가 화면에 맞게 커진다)
        info = pygame.display.Info()
        if info.current_w > 0 and info.current_h > 0 and width is None:
            width = int(info.current_w * 0.92)
            height = int(info.current_h * 0.86)
        width, height = width or 1440, height or 900
        if info.current_w > 0 and info.current_h > 0:
            width = min(width, info.current_w)
            height = min(height, info.current_h)
        self.window = pygame.display.set_mode((max(800, width), max(500, height)), flags)
        self.screen = self.window
        self._update_scale()
        self.clock = pygame.time.Clock()
        self.theme = Theme()
        self.gui = Gui(self.screen, self.theme)
        self.gui.blur()               # pygame 2는 텍스트 입력(IME)이 기본으로 켜져 있다: 입력칸을 누를 때만 켠다
        self.world = load_world()
        self.map = MapView(self.world)
        self.game: Game | None = None
        self.scene = "title"
        self.setup = modals.SetupState()
        self.running = True
        self.screenshot = screenshot
        self.reset_ui()

    # UI 는 논리 좌표 1280x800 기준으로 배치하고, 창 크기에 맞춰 비율을 유지하며 확대한다
    DESIGN_W, DESIGN_H = 1280, 800

    def _update_scale(self):
        self.screen = self.window
        ww, wh = self.window.get_size()
        u = max(0.5, min(4.0, ww / self.DESIGN_W, wh / self.DESIGN_H))
        set_ui_scale(u)
        if hasattr(self, "gui"):
            self.gui.screen = self.screen
        if hasattr(self, "map"):
            self.map.invalidate()

    def lsize(self):
        """화면 크기(논리 좌표)."""
        return self.gui.size()

    def set_map_view(self):
        W, H = self.screen.get_size()
        top = int(round(TOP_H * ui_scale()))
        self.map.set_view((0, top, W, H - top))

    def reset_ui(self):
        self.sel = None              # 선택한 구역/해역 ID
        self.sel_army = None
        self.dip_view = None         # 외교 탭에서 상세 보기 중인 세력
        self.war_confirm = None      # 선전포고 확인 대기 중인 세력
        self.qty = None              # 수량 슬라이더 창 (modals.open_qty)
        self.prio_sel = None         # 지출 우선순위에서 고른 행(위·아래 방향키로 이동)
        self.hover = None
        self.tab = "action"
        self.mode = "political"
        self.left_open = True
        self.attack_mode = "assault"
        self.bombard_mode = False
        self.toasts = []             # [text, color, t0]
        self.modal = None            # (name, data)
        self.flash_t = 0
        self.prev_values = {}
        self.prev_t = -10000
        self.dragging = False
        self.drag_start = None
        self.drag_moved = False
        self.split = {}
        self.ctx_menu = None
        self.fog_reveal = False
        self.dip_state = None
        self.show_terrain = True
        self.pick_popup = None
        self.spec_sel = None
        self.visited = set()         # 이번 턴 '다음 지역'으로 확인한 지역
        self.left_tab = "status"      # 좌측 패널: nation/diplo/army/energy/status(세로 탭), region(지역 선택)
        self.prio_drag = None

    # ------------------------------------------------------------ 게임 시작·저장
    def start_game(self, settings: Settings):
        self.game = Game(settings, self.world)
        self.reset_ui()
        self.scene = "government"
        self.map.z = 1.0
        self.map.center_on(self.game.player.capital, zoom=2.2)
        self.sel = self.game.player.capital

    def save(self, name="slot1"):
        if not self.game:
            return False
        os.makedirs(SAVE_DIR, exist_ok=True)
        path = os.path.join(SAVE_DIR, name + ".sav")
        with open(path, "wb") as f:
            pickle.dump({"version": VERSION, "game": self.game}, f)
        self.toast(f"저장했습니다: {path}")
        return True

    @staticmethod
    def slot_info(slot: int):
        """저장 슬롯(1~3) 정보: 없으면 None, 있으면 {"path", "mtime", "label"}."""
        path = os.path.join(SAVE_DIR, f"slot{slot}.sav")
        if not os.path.exists(path):
            return None
        g, ver = App.read_save(path)
        if g is None:
            return None                  # 버전 표기가 없거나 이어서 할 수 없는 버전: 보이지 않음
        return {"path": path, "mtime": os.path.getmtime(path), "version": ver,
                "label": f"{g.player.name} · {g.date_label()} · 지역 {g.region_count(g.player_id)}곳"}

    @staticmethod
    def read_save(path):
        """(게임, 버전). 버전 표기가 없거나 지금 버전과 이어서 할 수 없으면 (None, 버전)."""
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
        except Exception:
            return None, None
        if not isinstance(data, dict) or "game" not in data:
            return None, None
        ver = data.get("version")
        return (data["game"] if compatible(ver) else None), ver

    def open_slots(self, mode):
        """mode: save / save_exit / load — 슬롯 선택 창."""
        self.slot_cache = {i: self.slot_info(i) for i in range(1, C.SAVE_SLOTS + 1)}
        self.modal = ("saveslots", mode)

    def load(self, name="slot1"):
        path = os.path.join(SAVE_DIR, name + ".sav")
        if not os.path.exists(path):
            self.toast("저장 파일이 없습니다.", self.theme.bad)
            return
        g, ver = self.read_save(path)
        if g is None:
            self.toast(f"이 버전({VERSION})에서 이어서 할 수 없는 저장 파일입니다.", self.theme.bad)
            return
        if any(not hasattr(f, "met") for f in g.factions):
            g._update_fog()                      # v0.0.0 세이브: 조우 기록을 지금 시야로 채운다
        self.game = g
        self.modal = None
        self.reset_ui()
        self.scene = "main" if self.game.setup_done else "government"
        self.map.center_on(self.game.player.capital, zoom=2.0)
        self.map.invalidate()
        self.toast("불러왔습니다.")

    def toast(self, text, color=None):
        self.toasts.append([text, color or self.theme.text, pygame.time.get_ticks()])
        self.toasts = self.toasts[-7:]

    def changed(self):
        self.map.invalidate()

    # ------------------------------------------------------------ 루프
    def run(self, max_frames=None):
        frames = 0
        while self.running:
            events = pygame.event.get()
            for e in events:
                if e.type == pygame.QUIT:
                    self.running = False
                elif e.type == pygame.VIDEORESIZE:
                    w, h = max(800, e.w), max(500, e.h)
                    if (w, h) != self.window.get_size():
                        self.window = pygame.display.set_mode((w, h), pygame.RESIZABLE)
                    self._update_scale()
                elif e.type == getattr(pygame, "WINDOWSIZECHANGED", -1):
                    self.window = pygame.display.get_surface()
                    self._update_scale()
            self.gui.begin(events)
            self.frame()
            pygame.display.flip()
            self.clock.tick(60)
            frames += 1
            if max_frames and frames >= max_frames:
                if self.screenshot:
                    pygame.image.save(self.window, self.screenshot)
                break
        pygame.quit()

    def frame(self):
        self.screen.fill(self.theme.bg)
        if self.scene == "title":
            slots_open = bool(self.modal and self.modal[0] == "saveslots")
            help_open = bool(self.modal and self.modal[0] == "help")
            self.gui.input_enabled = not (slots_open or help_open)
            modals.draw_title(self)
            self.gui.input_enabled = True
            if slots_open:
                modals.draw_save_slots(self)
            elif help_open:
                modals.draw_help(self)
        elif self.scene == "setup":
            slots_open = bool(self.modal and self.modal[0] == "saveslots")
            flag_open = self.setup.flag_draft is not None
            pick_open = getattr(self.setup, "ai_pick", None) is not None
            self.gui.input_enabled = not (slots_open or flag_open or pick_open)
            modals.draw_setup(self)
            self.gui.input_enabled = True
            if slots_open:
                modals.draw_save_slots(self)
            elif flag_open:
                modals.draw_flag_editor(self)
            elif pick_open:
                modals.draw_ai_leader_picker(self)
        elif self.scene == "pick_start":
            self.draw_pick_start()
        elif self.scene == "pick_ai":
            self.draw_pick_ai()
        elif self.scene in ("government", "main"):
            self.draw_main()
        self.gui.draw_tooltip()

    # ------------------------------------------------------------ 시작 구역 고르기
    def draw_pick_start(self):
        sw, sh = self.lsize()
        self.set_map_view()
        popup = self.pick_popup
        self.gui.input_enabled = popup is None
        self.draw_map(pick_mode=True)
        g = self.gui
        g.panel((0, 0, sw, TOP_H), radius=0, shadow=False)
        if g.button((12, 10, 120, 36), "← 설정으로"):
            self.pick_popup = None
            self.scene = "setup"
            return
        from .mapview import TERRAIN_COLORS
        lx = max(560, sw - 240)
        g.text((148, TOP_H // 2), "시작할 지역을 클릭하세요 · 휠로 확대, 드래그로 이동", 15, weight="bold", anchor="midleft",
               max_w=lx - 160)
        for i, (kind, label) in enumerate((("도하", "도하(강)"), ("돌파", "산악 돌파"))):
            x = lx + i * 100
            g.line(TERRAIN_COLORS[kind], (x, TOP_H // 2), (x + 18, TOP_H // 2), 4)
            g.text((x + 24, TOP_H // 2), label, 12, self.theme.muted, anchor="midleft")
        if popup is None:
            self.map_input(pick_mode=True)
            if self.hover in self.world.regions:
                g.tooltip = self.world.regions[self.hover].name
            for k in g.keys:
                if k.key == pygame.K_ESCAPE:
                    self.scene = "setup"
        else:
            self.gui.input_enabled = True
            modals.draw_start_popup(self, popup)

    # ------------------------------------------------------------ 적 국가 지역 고르기
    def draw_pick_ai(self):
        """적 국가 지역 선택: 왼쪽 아래 목록에서 국가를 고르고 지도에서 지역을 누르면 그곳에 배치."""
        sw, sh = self.lsize()
        s = self.setup
        modals.fit_ai_slots(s)
        n = s.n_enemies
        s.ai_place = max(0, min(n - 1, s.ai_place or 0))
        self.set_map_view()
        self.draw_map(pick_mode=True)
        g = self.gui
        t = self.theme
        g.panel((0, 0, sw, TOP_H), radius=0, shadow=False)
        if g.button((12, 10, 120, 36), "← 설정으로"):
            self.scene = "setup"
            return
        g.text((148, TOP_H // 2), "왼쪽 아래 목록에서 국가를 고르고 지도에서 시작 지역을 클릭하세요 · 휠로 확대, 드래그로 이동",
               15, weight="bold", anchor="midleft", max_w=sw - 300)
        if g.button((sw - 150, 10, 138, 36), "모두 무작위 지역", size=12):
            modals.random_ai_starts(self)
        # 왼쪽 아래: AI1~n 목록
        rowh = max(22, min(34, int((sh - TOP_H - 70) / n) - 4))     # 15곳이어도 화면 안에
        ph = 40 + n * (rowh + 4)
        pr = pygame.Rect(12, sh - ph - 12, 300, ph)
        g.panel(pr, radius=10)
        g.text((pr.x + 14, pr.y + 12), "적 국가", 13, t.muted, "semibold")
        for i in range(n):
            k = s.ai_leaders[i]
            rid = s.ai_starts[i]
            lab = f"AI {i + 1}: {LEADER_BY_KEY[k]['name'] if k else '무작위'}"
            place = self.world.regions[rid].short if rid else "무작위"
            cell = (pr.x + 10, pr.y + 34 + i * (rowh + 4), pr.w - 20, rowh)
            if g.button(cell, "", selected=i == s.ai_place, tooltip=self.world.regions[rid].name if rid else "무작위 지역"):
                s.ai_place = i
            g.rect(hex2rgb(C.FACTION_COLORS[(i + 1) % len(C.FACTION_COLORS)]), (cell[0] + 8, cell[1] + rowh // 2 - 7, 14, 14),
                   radius=3)
            g.text((cell[0] + 30, cell[1] + rowh // 2), lab, 12, weight="semibold", anchor="midleft", max_w=150)
            g.text((cell[0] + cell[2] - 10, cell[1] + rowh // 2), place, 12, t.muted if not rid else t.text,
                   anchor="midright", max_w=90)
        self.map_input(pick_mode=True)
        if self.hover in self.world.regions:
            taken = self.start_owner(self.hover)
            g.tooltip = self.world.regions[self.hover].name + (f"\n{taken}의 시작 지역" if taken else "")
        if self.pick_popup:                    # 지도 클릭: 고른 국가를 그 지역에 배치(다른 나라 시작 지역이면 무시)
            rid = self.pick_popup
            self.pick_popup = None
            if self.start_owner(rid) is None or s.ai_starts[s.ai_place] == rid:
                s.ai_starts[s.ai_place] = rid
                nxt = [j for j in range(n) if s.ai_starts[j] is None]
                if nxt:
                    s.ai_place = nxt[0]
            self.map.invalidate()
        for k in g.keys:
            if k.key == pygame.K_ESCAPE:
                self.scene = "setup"

    def start_owner(self, rid):
        """설정 중인 시작 지역 주인: '내 국가'·'AI n' 또는 None."""
        s = self.setup
        if rid == s.start:
            return "내 국가"
        for i, a in enumerate(s.ai_starts[: s.n_enemies]):
            if a == rid:
                return f"AI {i + 1}"
        return None

    # ------------------------------------------------------------ 메인 화면
    def draw_main(self):
        game = self.game
        sw, sh = self.lsize()
        self.set_map_view()
        qty_open = bool(getattr(self, "qty", None))
        modal_open = self.scene == "government" or self.active_modal() is not None or qty_open
        self.gui.input_enabled = not modal_open
        self.draw_map()
        self.draw_topbar()
        h = sh - TOP_H - 90
        rail = pygame.Rect(8, TOP_H + 12, panels.RAIL_W, h)
        panels.draw_side(self, rail, pygame.Rect(rail.right + 6, TOP_H + 12, LEFT_W, h))
        self.draw_compass()
        self.draw_mode_chips()
        self.draw_end_turn()
        self.draw_toasts()
        if self.ctx_menu:
            self.draw_ctx_menu()
        if not modal_open:
            self.map_input()
            self.keyboard()
        self.gui.input_enabled = not qty_open
        if self.scene == "government":
            modals.draw_government(self)
        else:
            modals.draw_active_modal(self)
        self.gui.input_enabled = True
        if qty_open:
            modals.draw_qty(self)

    def active_modal(self):
        g = self.game
        if not g:
            return None
        if getattr(g, "dialogues", None):
            return "dialogue"                     # 지도자 대사 팝업이 가장 먼저(게임 종료 화면보다도)
        if g.pending_rebellions:
            return "rebellion"
        if g.pending_proposals:
            return "proposal"
        if self.modal:
            return self.modal[0]
        return None

    # ------------------------------------------------------------ 지도 색
    def region_colors(self, pick_mode=False):
        t = self.theme
        g = self.game
        out = {}
        pid = g.player_id if g else None
        fog_on = g and g.settings.fog > 0 and not self.fog_reveal
        ai_starts = list(self.setup.ai_starts[: self.setup.n_enemies]) if pick_mode else []
        for rid in self.world.order:
            info = self.world.regions[rid]
            if not g or pick_mode:
                fill = t.neutral
                if pick_mode and rid in (self.pick_popup, self.setup.start):
                    fill = t.accent
                elif pick_mode and rid in ai_starts:
                    fill = mix(hex2rgb(C.FACTION_COLORS[(ai_starts.index(rid) + 1) % len(C.FACTION_COLORS)]),
                               (255, 255, 255), 0.25)
                out[rid] = (fill, mix(fill, (255, 255, 255), 0.7))
                continue
            r = g.regions[rid]
            owner = r.owner
            explored = not fog_on or g.is_explored(pid, rid)
            visible = not fog_on or g.is_visible(pid, rid)
            if not explored:
                fill = t.unexplored
                if self.mode in SUB_MODES:          # 모르는 지역은 시작 시점 기준으로 표시
                    fill = self.overlay_color(rid, r, NEUTRAL, info, False,
                                              base=mix(t.unexplored, (255, 255, 255), 0.55))
                out[rid] = (fill, mix(fill, (255, 255, 255), 0.5))
                continue
            if not visible:
                owner = g.player.last_seen.get(rid, owner)
            if self.mode in SUB_MODES and not visible and owner != pid:
                # 세부 모드: 안개 지역은 바탕만 어둡게, 단계 색은 그대로(보이는 곳과 같은 단계면 같은 색)
                base = mix(desaturate(mix(self.owner_fill(owner), t.neutral, 0.75), 0.7), (0, 0, 0), 0.1)
                fill = self.overlay_color(rid, r, owner, info, False, base=base)
                out[rid] = (fill, mix(fill, (255, 255, 255), 0.7))
                continue
            fill = self.mode_color(rid, r, owner, info, visible or owner == pid)
            if self.mode == "political" and visible and owner == pid and r.project:
                # 생산·행동이 진행 중인 내 지역은 더 진한 색
                fill = mix(self.owner_fill(owner), mix(self.faction_rgb(owner), (0, 0, 0), 0.15), 0.55)
            if not visible:
                # 시야 밖: 바랜 한지처럼(채도를 빼고 먹빛을 살짝)
                fill = mix(desaturate(fill, 0.65), (120, 110, 92) if not t.dark else (0, 0, 0), 0.28)
            out[rid] = (fill, mix(fill, (255, 255, 255), 0.7))
        return out

    def map_extra(self, pick_mode=False):
        """지도 렌더용 세력 정보(안개 반영): 지역별 세력 코드, 진한 색, 전쟁 쌍."""
        g = self.game
        if not g or pick_mode:
            return None
        pid = g.player_id
        fog_on = g.settings.fog > 0 and not self.fog_reveal
        owners = {}
        for rid in self.world.order:
            r = g.regions[rid]
            if fog_on and not g.is_explored(pid, rid):
                owners[rid] = 1
                continue
            o = r.owner if (not fog_on or g.is_visible(pid, rid)) else g.player.last_seen.get(rid, r.owner)
            owners[rid] = 1 if o == NEUTRAL else o + 2
        deep = {f.id + 2: mix(self.faction_rgb(f.id), (20, 16, 12), 0.25) for f in g.factions}
        met = getattr(g.player, "met", set()) | {pid}
        alive = [f.id for f in g.factions if f.alive]
        wars = {(a + 2, b + 2) for i, a in enumerate(alive) for b in alive[i + 1:]
                if (a in met and b in met or self.fog_reveal) and D.at_war(g, a, b)}
        return {"owners": owners, "deep": deep, "wars": wars, "glow": self.mode == "political"}

    def order_colors(self):
        """이동 범위·명령 화살표 색: 이동은 내 나라 색(직접 만든 국기의 배경 색 1), 공격·상륙·폭격은 정해진 색."""
        cols = dict(ORDER_COLORS)
        if self.game:
            cols["move"] = mix(self.faction_rgb(self.game.player_id), (0, 0, 0), 0.15)
        return cols

    def faction_rgb(self, fid):
        if fid == NEUTRAL:
            return self.theme.neutral
        return hex2rgb(self.game.factions[fid].color)

    def owner_fill(self, owner):
        """영토 바탕: 세력 색을 조금 누그러뜨려 한지에 번진 수채화처럼."""
        if owner == NEUTRAL:
            return self.theme.neutral
        if self.theme.dark:
            return mix(self.faction_rgb(owner), (255, 255, 255), 0.3)
        return mix(desaturate(self.faction_rgb(owner), 0.2), self.theme.paper, 0.45)

    def sub_mode(self, mode=None):
        mode = mode or self.mode
        key = self.__dict__.setdefault("sub_modes", {}).get(mode) or SUB_MODES[mode][0][0]
        return next(x for x in SUB_MODES[mode] if x[0] == key)

    def overlay_level(self, sub, r, info, visible):
        """세부 모드의 단계(0 = 표시 안 함). 지금 보이지 않는 지역은 게임 시작 시점의 건물 상태로."""
        b = r.b if visible else initial_buildings(info)
        lines = r.lines if visible else {}
        src = info.power_source or ""
        if sub == "specialty":
            return b["specialty"] if info.specialty else 0
        if sub == "coal":
            return (b["extract"] or 0.3) if info.is_coal else 0      # 탄광 없는 탄전은 아주 연하게
        if sub == "oil":
            return info.oil + b["extract"] if info.is_oil else 0
        if sub == "scenic":
            return 1 if info.scenic else 0
        if sub == "dam":
            return info.power_self if "수력" in src else 0
        if sub == "nuclear":
            return info.power_self if "원자력" in src else 0
        if sub == "power":
            return b["power"] - (1 if ("수력" in src or "원자력" in src) else 0)   # 댐·원전은 자원 탭에서
        if sub == "line":
            return max(lines.values(), default=0)
        return b.get(sub, 0)

    def overlay_color(self, rid, r, owner, info, visible, base=None):
        t = self.theme
        key, _, col, top = self.sub_mode()
        if base is None:
            base = mix(self.owner_fill(owner), t.neutral, 0.75)
        lv = self.overlay_level(key, r, info, visible)
        if lv <= 0:
            return base
        # 단계 색은 바탕(세력 색·안개)과 상관없이 같은 단계면 같은 색: 1단계가 가장 연하고 오를수록 진하게
        x = 0.85 if top is None else 0.2 + 0.75 * min(1.0, lv / top)
        light = (241, 243, 245)
        if key == "oil":                      # 석유: 채도 0의 회색 계열, 1단계부터 바탕보다 확실히 진하게
            light = (238, 238, 238)
            x = 0.45 + 0.55 * min(1.0, lv / top)
        return mix(light, hex2rgb(col), x)

    def mode_color(self, rid, r, owner, info, visible=True):
        t = self.theme
        g = self.game
        m = self.mode
        if m == "political":
            return self.owner_fill(owner)
        if m == "happy":
            if owner == NEUTRAL:
                return t.neutral
            h = g.eff_happy(r)                     # 실질 행복도(전쟁 피로·저항 반영)
            return mix(t.happy_mid, t.happy_pos, h / 100) if h >= 0 else mix(t.happy_mid, t.happy_neg, -h / 100)
        if m == "pop":
            x = min(1.0, math.log10(max(1.0, r.pop)) / 2.1)
            return mix((241, 243, 245), (25, 113, 194), x)
        if m in SUB_MODES:
            return self.overlay_color(rid, r, owner, info, visible)
        if m == "opinion":
            if owner == NEUTRAL:
                return t.neutral
            if owner == g.player_id:
                return mix(self.faction_rgb(owner), (255, 255, 255), 0.3)
            if D.at_war(g, owner, g.player_id):
                return hex2rgb("#C92A2A")
            op = D.opinion(g, owner, g.player_id)
            return mix(t.happy_mid, t.happy_pos, op / 100) if op >= 0 else mix(t.happy_mid, t.happy_neg, -op / 100)
        return t.neutral

    def sea_colors(self):
        t = self.theme
        out = {}
        if self.game:
            for sid in self.world.seas:
                ctrl = self.game.coast_controller(sid)
                if ctrl is not None:
                    out[sid] = mix(t.sea, self.faction_rgb(ctrl), 0.12)
        return out

    def map_labels(self):
        labels = {sid: n for sid, n in SEA_NAMES.items()}
        for rid, info in self.world.regions.items():
            labels[rid] = info.short
        return labels

    # ------------------------------------------------------------ 지도 그리기
    def draw_map(self, pick_mode=False):
        mv = self.map
        busy = 0 if pick_mode or not self.game else hash(frozenset(
            r.id for r in self.game.regions.values() if r.owner == self.game.player_id and r.project))
        key = ("pick", self.setup.start, self.pick_popup, tuple(self.setup.ai_starts[: self.setup.n_enemies])) if pick_mode else (
            self.mode, self.sub_mode()[0] if self.mode in SUB_MODES else "", self.fog_reveal, id(self.game),
                                                              self.game.turn if self.game else 0,
                                                              self.show_terrain, busy)
        # 색·지명은 지도를 다시 그릴 때만 계산한다(매 프레임 계산하지 않음)
        mv.draw_base(self.screen, key, self.theme, lambda: self.region_colors(pick_mode), self.sea_colors,
                     self.mode, self.map_labels, show_terrain=self.show_terrain,
                     extra_fn=lambda: self.map_extra(pick_mode))
        self.screen.set_clip(mv.view)
        u = ui_scale()
        if pick_mode:
            if self.hover and self.hover in self.world.regions:
                mv.outline(self.screen, self.hover, self.theme.text, max(2, int(2 * u)))
            if self.setup.start:
                mv.outline(self.screen, self.setup.start, (255, 255, 255), max(3, int(3 * u)))
            # 적 국가 시작 지역: 'AI n' 표시(적 국가 지역 선택 화면에서는 고른 칸을 굵게)
            for i, rid in enumerate(self.setup.ai_starts[: self.setup.n_enemies]):
                if not rid:
                    continue
                if self.scene == "pick_ai" and i == self.setup.ai_place:
                    mv.outline(self.screen, rid, (255, 212, 59), max(3, int(3 * u)))
                x, y = mv.label_screen(rid)
                lab = render_text(f"AI {i + 1}", 11, (255, 255, 255), "bold")
                box = lab.get_rect(center=(x, y - int(14 * u))).inflate(int(8 * u), int(4 * u))
                pygame.draw.rect(self.screen, hex2rgb(C.FACTION_COLORS[(i + 1) % len(C.FACTION_COLORS)]), box,
                                 border_radius=4)
                self.screen.blit(lab, lab.get_rect(center=box.center))
            self.screen.set_clip(None)
            return
        g = self.game
        # 이동 범위
        army = g.armies.get(self.sel_army) if self.sel_army else None
        if army and army.owner == g.player_id and not g.army_acted(army.id):   # 이번 턴 전투한 부대는 범위 없음
            reach = g.reachable(army)
            box = mv.screen_bbox(reach)
            if box and box.w > 0 and box.h > 0:
                ov = pygame.Surface(box.size, pygame.SRCALPHA)     # 이동 범위가 걸친 만큼만
                cols = self.order_colors()
                # 해역을 먼저 칠해야 섬 구멍을 비워도 육지 오버레이가 지워지지 않는다
                for node, opt in sorted(reach.items(), key=lambda kv: not self.world.is_sea(kv[0])):
                    col = cols[opt["action"]]
                    a = 115 if opt["strong"] else 60
                    if self.world.is_sea(node):
                        mv.sea_overlay(ov, node, (*col, 45), origin=box.topleft)
                    else:
                        mv.fill_overlay(ov, node, (*col, a), origin=box.topleft)
                self.screen.blit(ov, box.topleft)
            if not self.world.is_sea(army.loc):
                for n in self.world.land_adj[army.loc]:
                    if self.world.is_bridge(army.loc, n):
                        self.dashed(mv.label_screen(army.loc), mv.label_screen(n), (60, 60, 60))
        # 해역 hover
        if self.hover in self.world.seas:
            mv.sea_outline(self.screen, self.hover, mix(self.theme.sea_line, self.theme.accent, 0.5), 2)
        if self.hover and self.hover in self.world.regions:
            mv.outline(self.screen, self.hover, self.theme.text, 1)
        if self.sel:
            if self.sel in self.world.seas:
                mv.sea_outline(self.screen, self.sel, self.theme.accent, 3)
            else:
                # 선택 지역: 은은한 금빛 번짐 + 흰·금 이중 윤곽(번짐 면은 지역 크기만큼만)
                box = mv.screen_bbox([self.sel], pad=int(10 * u))
                if box and box.w > 0 and box.h > 0:
                    glow = pygame.Surface(box.size, pygame.SRCALPHA)
                    for wdt, a in ((12, 30), (8, 50), (4, 90)):
                        mv.outline_overlay(glow, self.sel, (*self.theme.gold_lt, a), max(2, int(wdt * u)), origin=box.topleft)
                    self.screen.blit(glow, box.topleft)
                mv.outline(self.screen, self.sel, (255, 248, 230), max(3, int(3 * u)))
                mv.outline(self.screen, self.sel, self.theme.gold, max(2, int(2 * u)))
        # 전투 강조 (1초)
        dt = pygame.time.get_ticks() - self.flash_t
        if dt < 1200 and g.battle_regions:
            a = 1 - dt / 1200
            col = mix((255, 255, 255), (224, 49, 49), a)
            for rid in set(g.battle_regions):
                if rid in self.world.regions:
                    mv.outline(self.screen, rid, col, 3)
        self.draw_battle_marks()
        self.draw_science_sites()
        self.draw_focus()
        self.draw_capitals()
        self.draw_occupations()
        self.draw_orders()
        self.draw_armies()
        self.screen.set_clip(None)

    def dashed(self, p1, p2, color, dash=6, width_k=2):
        dash = dash * ui_scale()
        x1, y1 = p1
        x2, y2 = p2
        d = math.hypot(x2 - x1, y2 - y1)
        if d < 1:
            return
        n = int(d / dash)
        for i in range(0, n, 2):
            a, b = i / n, min(1, (i + 1) / n)
            pygame.draw.line(self.screen, color, (x1 + (x2 - x1) * a, y1 + (y2 - y1) * a),
                             (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b), max(2, int(width_k * ui_scale())))

    def star(self, center, r, color):
        """수도 별: 그림자 + 세력 색(진하게) + 한지색 테두리."""
        cx, cy = center
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.42
            pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
        u = ui_scale()
        key = (int(r * 10), int(u * 10))
        cache = self.__dict__.setdefault("_star_shadow", {})
        sh = cache.get(key)
        if sh is None:
            sh = pygame.Surface((int(r * 3), int(r * 3)), pygame.SRCALPHA)
            pygame.draw.polygon(sh, (0, 0, 0, 70), [(x - cx + r * 1.5 + u, y - cy + r * 1.5 + 2 * u) for x, y in pts])
            cache[key] = sh
        self.screen.blit(sh, (cx - r * 1.5, cy - r * 1.5))
        pygame.draw.polygon(self.screen, color, pts)
        pygame.draw.polygon(self.screen, (247, 241, 227), pts, max(1, int(1.5 * u)))

    def _ellipse_shadow(self, w, h):
        """부대 깃발 밑 그림자(크기별 캐시)."""
        cache = self.__dict__.setdefault("_ell_shadow", {})
        sh = cache.get((w, h))
        if sh is None:
            sh = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
            pygame.draw.ellipse(sh, (0, 0, 0, 55), sh.get_rect())
            if len(cache) > 200:
                cache.clear()
            cache[(w, h)] = sh
        return sh

    def draw_battle_marks(self):
        """이번 턴 전투가 난 지역: 작은 주홍 원 + 칼 교차."""
        from .art import ui_icon
        g = self.game
        mv = self.map
        u = ui_scale()
        for rid in set(getattr(g, "battle_regions", ()) or ()):
            if rid not in self.world.regions:
                continue
            if not (g.is_visible(g.player_id, rid) or self.fog_reveal):
                continue
            x, y = mv.label_screen(rid)
            if not mv.view.collidepoint(x, y):
                continue
            c = (int(x - 18 * u), int(y - 4 * u))
            pygame.draw.circle(self.screen, self.theme.vermilion, c, max(5, int(8 * u)))
            pygame.draw.circle(self.screen, (247, 241, 227), c, max(5, int(8 * u)), max(1, int(1.5 * u)))
            ui_icon(self.screen, "swords", c, (247, 241, 227), 0.55 * u)

    def draw_capitals(self):
        g = self.game
        for f in g.factions:
            if not f.alive:
                continue
            if not (f.id == g.player_id or g.is_visible(g.player_id, f.capital) or self.fog_reveal
                    or g.is_explored(g.player_id, f.capital)):
                continue
            x, y = self.map.label_screen(f.capital)
            u = ui_scale()
            self.star((x, y - (16 * u if self.map.z >= 2 else 0)), (7 if self.map.z < 2 else 9) * u,
                      mix(self.faction_rgb(f.id), (25, 18, 12), 0.3))

    def draw_science_sites(self):
        """과학승리 시설(연구소·관측소·발사대)과 진행 중인 과학 단계 표시."""
        g = self.game
        mv = self.map
        pid = g.player_id
        for r in g.regions.values():
            building = r.project and r.project.kind == "science" and not C.SCIENCE[r.project.key]["unit"]
            if not (r.sci or building):
                continue
            if not (r.owner == pid or g.is_explored(pid, r.id) or self.fog_reveal):
                continue
            x, y = mv.label_screen(r.id)
            if not mv.view.collidepoint(x, y):
                continue
            u = ui_scale()
            x += (18 if mv.z >= 2 else 9) * u
            y -= (16 if mv.z >= 2 else 7) * u
            col = (241, 196, 15) if r.sci else (180, 180, 180)
            tri = [(x, y - 11 * u), (x + 5 * u, y + 7 * u), (x - 5 * u, y + 7 * u)]
            pygame.draw.polygon(self.screen, col, tri)
            pygame.draw.polygon(self.screen, mix(col, (0, 0, 0), 0.4), tri, 1)
            pygame.draw.line(self.screen, mix(col, (0, 0, 0), 0.4), (x - 7 * u, y + 7 * u), (x + 7 * u, y + 7 * u),
                             max(2, int(2 * u)))
            if mv.z >= 3 and r.sci:
                names = "·".join(C.SCIENCE[k]["name"] for k in C.SCIENCE_STEPS if k in r.sci)
                t = render_text(names, 11, (122, 88, 0), "bold")
                self.screen.blit(t, t.get_rect(midleft=(x + 8 * u, y)))

    def draw_focus(self):
        """생산 집중 중인 내 지역: 지명 오른쪽에 [P]."""
        g = self.game
        mv = self.map
        u = ui_scale()
        for r in g.regions_of(g.player_id):
            pf = getattr(r, "pop_focus", False)
            if not r.focus and not pf:
                continue
            x, y = mv.label_screen(r.id)
            if not mv.view.collidepoint(x, y):
                continue
            if mv.z >= 2.0:
                x += render_text(self.world.regions[r.id].short, 11, (0, 0, 0), "semibold").get_width() / 2 + 3 * u
            act = g.pop_focus_active(r) if pf else g.focus_active(r)
            col = ((20, 120, 60) if pf else (25, 25, 25)) if act else (130, 130, 130)
            t = render_text("[G]" if pf else "[P]", 11, col, "bold")
            self.screen.blit(t, t.get_rect(midleft=(x + 2 * u, y + 2 * u - (6 * u if mv.z >= 4 else 0))))

    def draw_occupations(self):
        g = self.game
        for r in g.regions.values():
            if not r.occ or not (g.is_visible(g.player_id, r.id) or self.fog_reveal):
                continue
            x, y = self.map.label_screen(r.id)
            col = self.faction_rgb(r.occ["by"])
            u = ui_scale()
            rect = pygame.Rect(0, 0, int(36 * u), max(6, int(7 * u)))
            rect.center = (x, y + 16 * u)
            frac = min(1.0, r.occ["progress"] / max(1, r.occ["need"]))
            pygame.draw.rect(self.screen, (255, 255, 255), rect, border_radius=rect.h // 2)
            if frac > 0:
                pygame.draw.rect(self.screen, col, (rect.x, rect.y, max(rect.h, int(rect.w * frac)), rect.h),
                                 border_radius=rect.h // 2)
            pygame.draw.rect(self.screen, col, rect, 1, border_radius=rect.h // 2)

    def draw_orders(self):
        g = self.game
        mv = self.map
        for a in g.armies.values():
            if a.owner != g.player_id or not a.order:
                continue
            o = a.order
            p0 = mv.label_screen(a.loc)
            if o["type"] == "move":
                pts = [p0] + [mv.label_screen(n) for n in o["path"]]
                self.arrow(pts, self.order_colors()["move"])
            elif o["type"] in ("attack", "land"):
                pts = [p0] + [mv.label_screen(n) for n in o.get("path", [])]
                if pts[-1] != mv.label_screen(o["target"]):
                    pts.append(mv.label_screen(o["target"]))
                self.arrow(pts, ORDER_COLORS["attack" if o["type"] == "attack" else "land"])
            elif o["type"] == "bombard":
                q = mv.label_screen(o["target"])
                self.dashed(p0, q, (255, 255, 255), width_k=4)
                self.dashed(p0, q, ORDER_COLORS["bombard"])
                self.arrowhead(p0, q, ORDER_COLORS["bombard"], outline=True)
                continue
            # 여러 턴 자동 이동: 이번 턴 도착지부터 최종 목적지까지 남은 경로를 점선으로
            if getattr(a, "goto", None) and a.goto != (o.get("path") or [a.loc])[-1]:
                end = (o.get("path") or [a.loc])[-1]
                probe = Army(0, a.owner, end, a.units)
                route = g.plan_route(probe, a.goto) or [a.goto]
                pts = [mv.label_screen(end)] + [mv.label_screen(n) for n in route]
                for p, q in zip(pts, pts[1:]):
                    self.dashed(p, q, (255, 255, 255), width_k=4)
                    self.dashed(p, q, self.order_colors()["move"])
                self.arrowhead(pts[-2], pts[-1], self.order_colors()["move"], outline=True)

    def arrow(self, pts, color):
        """얇은 직선 화살표(한지색 테두리로 영토 색과 구분)."""
        u = ui_scale()
        pygame.draw.lines(self.screen, (247, 241, 227), False, pts, max(4, int(4 * u)))
        pygame.draw.lines(self.screen, color, False, pts, max(2, int(2 * u)))
        self.arrowhead(pts[-2], pts[-1], color, outline=True)

    def arrowhead(self, p1, p2, color, outline=False):
        ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        L = 9 * ui_scale()
        pts = [p2, (p2[0] - L * math.cos(ang - 0.45), p2[1] - L * math.sin(ang - 0.45)),
               (p2[0] - L * math.cos(ang + 0.45), p2[1] - L * math.sin(ang + 0.45))]
        pygame.draw.polygon(self.screen, color, pts)
        if outline:
            pygame.draw.polygon(self.screen, (247, 241, 227), pts, max(1, int(1 * ui_scale())))

    def draw_armies(self):
        g = self.game
        mv = self.map
        pid = g.player_id
        by_loc = {}
        for a in g.armies.values():
            if a.empty():
                continue
            if a.owner == NEUTRAL and mv.z < 3.5:
                continue
            # 축소 화면에서는 보병 1개짜리 수비대를 숨긴다
            if mv.z < 2 and a.count() <= 1 and not a.order and a.id != self.sel_army:
                continue
            if not (a.owner == pid or g.is_visible(pid, a.loc) or self.fog_reveal):
                continue
            by_loc.setdefault(a.loc, []).append(a)
        u = ui_scale()
        ink = (30, 25, 20)
        for loc, arms in by_loc.items():
            x, y = mv.label_screen(loc)
            if not mv.view.collidepoint(x, y):
                continue
            arms.sort(key=lambda a: (a.owner != pid, a.owner, a.id))
            # 군기: 장대 + 깃발(육군 제비꼬리·해군 뾰족한 삼각기·공군 날개깃) + 대표 병종 아이콘 + 총수
            fh = max(10, int(14 * u))
            flags = []
            for a in arms:
                num = render_text(str(a.count()), 10, (255, 255, 255), "bold")
                fw = int(14 * u) + num.get_width() + int(6 * u)
                flags.append((a, num, fw))
            total = sum(fw + int(4 * u) for _, _, fw in flags)
            fx = x - total / 2
            fy = y + (8 if mv.z >= 2 else 3) * u
            if mv.z >= 4 and not self.world.is_sea(loc):
                fy += 14 * u
            for a, num, fw in flags:
                col = (120, 120, 120) if a.owner == NEUTRAL else self.faction_rgb(a.owner)
                if g.army_acted(a.id):
                    col = mix(col, (150, 150, 150), 0.6)     # 이번 턴 전투한 부대: 흐리게
                icon_key = "lst" if a.units.get("lst", 0) > 0 else max(a.units, key=lambda k: a.units[k] * C.UNITS[k]["cost"])
                kind = C.UNITS[icon_key]["kind"]
                x0, y0 = int(fx), int(fy)
                notch = 4 * u
                if kind == "naval":
                    pts = [(x0, y0), (x0 + fw - notch, y0), (x0 + fw + notch, y0 + fh / 2), (x0 + fw - notch, y0 + fh),
                           (x0, y0 + fh)]
                elif kind == "air":
                    pts = [(x0, y0), (x0 + fw, y0 + 2 * u), (x0 + fw, y0 + fh - 2 * u), (x0, y0 + fh)]
                else:
                    pts = [(x0, y0), (x0 + fw, y0), (x0 + fw - notch, y0 + fh / 2), (x0 + fw, y0 + fh), (x0, y0 + fh)]
                base_y = y0 + fh + 6 * u
                self.screen.blit(self._ellipse_shadow(int(fw * 0.9), max(3, int(5 * u))), (x0 - int(3 * u), base_y - int(2 * u)))
                pygame.draw.line(self.screen, ink, (x0, y0 - 3 * u), (x0, base_y), max(1, int(1.5 * u)))
                if a.id == self.sel_army:
                    pygame.draw.polygon(self.screen, (247, 241, 227), pts, max(3, int(4 * u)))
                pygame.draw.polygon(self.screen, col, pts)
                pygame.draw.polygon(self.screen, ink, pts, max(1, int((2 if a.id == self.sel_army else 1) * u)))
                panels.unit_icon(self.screen, icon_key, (x0 + int(7 * u), int(y0 + fh / 2 + u)), (255, 255, 255), 0.95 * u)
                self.screen.blit(num, num.get_rect(midleft=(x0 + int(13 * u), int(y0 + fh / 2 + 1))))
                if a.order and a.owner == pid:
                    pygame.draw.circle(self.screen, (247, 241, 227), (int(x0 + fw), y0), max(3, int(3.5 * u)))
                    pygame.draw.circle(self.screen, ink, (int(x0 + fw), y0), max(3, int(3.5 * u)), 1)
                fx += fw + int(4 * u)
        # 줌 4배 이상: 인구 배지
        if mv.z >= 4:
            for rid in self.world.order:
                x, y = mv.label_screen(rid)
                if not mv.view.collidepoint(x, y):
                    continue
                if not (g.is_explored(pid, rid) or self.fog_reveal):
                    continue
                t = render_text(f"{g.regions[rid].pop:.1f}만", 10, self.theme.muted, "semibold")
                self.screen.blit(t, t.get_rect(center=(x, y + 10 * ui_scale())))

    # ------------------------------------------------------------ 지도 입력
    def map_input(self, pick_mode=False):
        gui = self.gui
        mv = self.map
        pos = gui.mouse_phys
        over_ui = gui.over_ui(gui.mouse) or not mv.view.collidepoint(pos)
        if not over_ui and (gui.clicked or gui.rclicked):
            self.mode_popup = None              # 지도를 누르면 세부 메뉴를 닫는다
        self.hover = None if over_ui else mv.pick(pos)
        if not over_ui and gui.wheel:
            mv.zoom_at(pos, 1.2 ** gui.wheel)
            gui.wheel = 0
        # 드래그로 이동
        buttons = pygame.mouse.get_pressed()
        rel = pygame.mouse.get_rel()
        if buttons[0] or buttons[1]:
            if not self.dragging and not over_ui:
                self.dragging = True
                self.drag_moved = False
            elif self.dragging and (rel[0] or rel[1]):
                if abs(rel[0]) + abs(rel[1]) > 0:
                    self.drag_moved = self.drag_moved or abs(rel[0]) + abs(rel[1]) > 2
                    mv.pan(*rel)
        elif self.dragging and not gui.clicked:
            self.dragging = False
        if over_ui:
            if gui.clicked:
                self.dragging = False
            return
        if gui.dclicked:
            mv.zoom_at(pos, 2.0)
        if gui.clicked:
            was_drag = self.drag_moved
            self.dragging = False
            self.drag_moved = False
            if was_drag:
                return
            self.ctx_menu = None
            node = self.hover
            if pick_mode:
                if node in self.world.regions:
                    self.pick_popup = node
                    mv.invalidate()
                return
            self.select(node)
        if gui.rclicked and not pick_mode:
            self.right_click(self.hover, gui.mouse)
        if not pick_mode and self.hover and self.sel_army:
            self.order_tooltip(self.hover)

    def select(self, node):
        g = self.game
        prev = self.sel
        self.sel = node
        self.split = {}
        if node is None:
            self.sel_army = None
            return
        mine = sorted(g.armies_at(node, g.player_id), key=lambda a: (-g.army_power(a), a.id))
        cur = g.armies.get(self.sel_army) if self.sel_army else None
        if not cur or cur.loc != node:
            self.sel_army = mine[0].id if mine else None
        hidden = self.hidden_owner(node)
        showing = (self.left_tab == "region" if hidden is None
                   else self.left_tab == "diplo" and self.dip_view == hidden)
        if prev == node and self.left_open and showing:
            self.left_open = False          # 이미 선택한 지역을 다시 누르면 메뉴를 닫는다
            return
        # 지역 메뉴의 [부대]·[지역 정보]를 보던 중이면 다른 지역을 눌러도 같은 탭으로 연다
        keep = self.tab if (self.left_open and self.left_tab == "region" and self.tab in ("army", "info")) else None
        self.left_open = True
        if hidden is not None:
            # 시야 밖 타국 영토: 외교 탭의 그 세력 상세 화면
            self.left_tab, self.dip_view, self.war_confirm = "diplo", hidden, None
        elif g.regions.get(node) is None:
            # 해역: 내 함대가 있으면 [부대], 없으면 해역 정보
            self.left_tab, self.tab = "region", (keep or ("army" if mine else "info"))
        else:
            # 지역을 누르면 [행동](내 지역이 아니면 할 행동이 없으니 [지역 정보]). 보던 탭이 있으면 그대로
            self.left_tab, self.tab = "region", (keep or ("action" if g.regions[node].owner == g.player_id else "info"))

    def hidden_owner(self, node):
        """탐색했지만 지금 시야 밖인 타국 영토면 마지막으로 본 주인 세력, 아니면 None."""
        g = self.game
        r = g.regions.get(node)
        if r is None or self.fog_reveal or g.is_visible(g.player_id, node) or not g.is_explored(g.player_id, node):
            return None
        owner = g.player.last_seen.get(node, r.owner)
        if owner in (NEUTRAL, g.player_id) or not (0 <= owner < len(g.factions)) or not g.factions[owner].alive:
            return None
        return owner

    def right_click(self, node, pos):
        g = self.game
        if not node:
            return
        army = g.armies.get(self.sel_army) if self.sel_army else None
        if army and army.owner == g.player_id and g.army_acted(army.id):
            self.toast("이번 턴에 이미 전투한 부대입니다(합치기·분리·이동·공격 불가).", self.theme.bad)
            return
        if army and army.owner == g.player_id:
            # 전투가 일어나는 공격이면 확인 창(양측 병력·보정·예상 결과)을 먼저 띄운다
            if not self.bombard_mode and node in g.regions:
                opt = g.reachable(army).get(node)
                if opt and opt["action"] == "attack" and g.hostile_units_at(army.owner, node):
                    self.modal = ("battle", {"army": army.id, "node": node, "mode": self.attack_mode})
                    return
            ok, msg = g.order_army(army.id, node, self.attack_mode, force_bombard=self.bombard_mode)
            self.toast(msg if isinstance(msg, str) else str(msg), None if ok else self.theme.bad)
            return
        if node in g.regions:
            o = g.regions[node].owner
            if o not in (NEUTRAL, g.player_id):
                self.ctx_menu = (pos, o, node)

    def draw_ctx_menu(self):
        pos, fid, node = self.ctx_menu
        g = self.gui
        r = pygame.Rect(pos[0], pos[1], 170, 84)
        g.panel(r)
        g.text((r.x + 12, r.y + 8), self.game.seen_name(fid), 13, weight="bold")
        if g.button((r.x + 8, r.y + 30, 154, 22), "외교", "ghost", enabled=self.game.has_met(self.game.player_id, fid)):
            self.open_diplomacy(fid)
            self.ctx_menu = None
        if g.button((r.x + 8, r.y + 56, 154, 22), "구역 정보", "ghost"):
            self.select(node)
            self.ctx_menu = None

    def order_tooltip(self, node):
        g = self.game
        army = g.armies.get(self.sel_army)
        if not army or army.owner != g.player_id or self.gui.over_ui():
            return
        if g.army_acted(army.id):
            self.gui.tooltip = "이번 턴 전투 완료: 이동·공격 불가"
            return
        reach = g.reachable(army)
        opt = reach.get(node)
        if not opt:
            return
        act = "bombard" if self.bombard_mode else opt["action"]
        lines = []
        name = self.world.node_name(node)
        if act == "move":
            lines.append(f"이동: {name} ({len(opt['path'])}칸)")
            if army.domain() == "naval" and self.world.is_sea(node):
                lines.append("해역에 머무는 턴은 해군 유지비 2배")
        elif act == "land":
            lines.append(f"상륙(하역): {name}")
        elif act == "bombard":
            lines.append(f"폭격: {name}")
        elif act == "attack":
            mode = self.attack_mode
            pv = g.preview_attack(army, node, mode)
            lines.append(f"{'기습' if mode == 'surprise' else '돌격'}: {name}")
            if pv:
                if pv["defenders"] == 0:
                    lines.append("방어 병력 없음 → 진입 후 점령 시작")
                else:
                    lines.append(f"공격력 A {pv['A']:.1f} / 방어력 D {pv['D']:.1f} (방어선 {pv['line']}단계)")
                    if pv.get("terrain"):
                        tr = pv["terrain"]
                        lines.append(f"{tr['label']}({tr['name']}·{tr['note']}) 공격 ×{tr['mult']}")
                    if mode == "surprise":
                        lines.append(f"기습 성공률 {pv['surprise_p']*100:.0f}%")
                        lines.append(f"성공 시 적 피해 {pv['def_dmg_win']:.1f} / 아군 {pv['att_dmg_win']:.1f}")
                        lines.append(f"실패 시 적 피해 {pv['def_dmg_fail']:.1f} / 아군 {pv['att_dmg_fail']:.1f}")
                    else:
                        lines.append(f"기대 피해: 적 {pv['def_dmg']:.1f} / 아군 {pv['att_dmg']:.1f} (체력 기준)")
                    lines.append(f"적 총 체력 {pv['def_hp']:.1f}")
        self.gui.tooltip = "\n".join(lines)

    PAN_SPEED = 900          # 방향키를 누르고 있을 때 초당 이동(화면 픽셀)

    def arrow_pan(self):
        """방향키를 누르고 있는 동안 지도를 계속 민다(누른 시간만큼, 프레임 속도와 무관)."""
        now = pygame.time.get_ticks()
        last, self._pan_t = getattr(self, "_pan_t", now), now
        if self.gui.focus:
            self.arrow_capture_v = False
            return
        pressed = pygame.key.get_pressed()
        dx = (pressed[pygame.K_LEFT] - pressed[pygame.K_RIGHT])
        dy = (pressed[pygame.K_UP] - pressed[pygame.K_DOWN])
        if getattr(self, "arrow_capture_v", False):   # 지출 우선순위 행을 고른 동안 ↑↓는 순서 이동
            dy = 0
        self.arrow_capture_v = False
        if not (dx or dy):
            return
        step = self.PAN_SPEED * min(0.1, max(0.0, (now - last) / 1000))
        if dx and dy:
            step *= 0.7071
        if step > 0:
            self.map.pan(dx * step, dy * step)

    def keyboard(self):
        g = self.gui
        self.arrow_pan()
        for k in list(g.keys):
            if g.focus:
                continue
            if k.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                g.keys.remove(k)                     # 이 Enter는 여기서 소비(새로 뜬 대사 창이 같은 Enter로 닫히지 않게)
                if pygame.key.get_mods() & pygame.KMOD_SHIFT or not self.next_region():
                    self.end_turn()
            elif k.key == pygame.K_ESCAPE:
                if self.sel_army:
                    self.sel_army = None
                elif self.sel or self.ctx_menu:
                    self.sel = None
                else:
                    self.modal = ("pause", None)     # 선택한 것이 없으면 일시정지
                    g.keys.remove(k)                 # 같은 프레임에 창이 바로 닫히지 않도록
                self.ctx_menu = None
            elif k.key == pygame.K_p:
                self.modal = ("pause", None)
                g.keys.remove(k)
            elif k.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                self.map.zoom_at(self.map.view.center, 1.25)
            elif k.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.map.zoom_at(self.map.view.center, 0.8)
            elif pygame.K_1 <= k.key < pygame.K_1 + len(MAP_MODES):
                self.mode = MAP_MODES[k.key - pygame.K_1][0]
                self.mode_popup = None
            elif k.key == pygame.K_F1:
                self.modal = ("help", None)
            elif k.key == pygame.K_F2:
                self.fog_reveal = not self.fog_reveal
                self.toast("개발자 안개 토글: " + ("전체 공개" if self.fog_reveal else "기본"))
                self.changed()
            elif k.key == pygame.K_F5:
                self.open_slots("save")
            elif k.key == pygame.K_F9:
                self.open_slots("load")
            elif k.key == pygame.K_TAB:
                self.next_idle()
            elif k.key == pygame.K_a and not pygame.key.get_mods() & pygame.KMOD_CTRL:
                from .. import ai
                n = ai.auto_slots(self.game, self.game.player_id,
                                  military=self.game.player.ai.get("auto_military", False))
                self.toast(f"슬롯 {n}곳을 자동 지정했습니다.")
            elif k.key == pygame.K_d and pygame.key.get_mods() & pygame.KMOD_CTRL:
                self.theme.set_dark(not self.theme.dark)
                self.changed()

    def next_idle(self):
        g = self.game
        idle = [r.id for r in g.regions_of(g.player_id) if not r.project and not r.occ and not g.resisting(r)]
        if not idle:
            self.toast("빈 슬롯이 없습니다.")
            return
        i = (idle.index(self.sel) + 1) % len(idle) if self.sel in idle else 0
        self.select(idle[i])
        self.tab = "action"
        self.map.center_on(idle[i])

    # ------------------------------------------------------------ 턴 종료
    def snapshot(self):
        f = self.game.player
        return {"money": f.money, "net": f.last.get("net", 0), "food": f.res["food"], "happy": round(self.game.avg_happiness(f.id)),
                "weary": round(f.war_weary), "tax": round(f.tax * 100)}

    def end_turn(self):
        g = self.game
        if g.game_over or self.active_modal():
            return
        before = self.snapshot()
        g.end_turn()
        self.enter_guard = pygame.time.get_ticks() + 400   # 턴 종료 직후 잠깐은 Enter로 대사 창을 넘기지 않는다(키 반복·연타 방지)
        self.visited = set()
        self.prev_values = before
        self.prev_t = pygame.time.get_ticks()
        self.flash_t = pygame.time.get_ticks()
        self.changed()
        if self.sel_army and self.sel_army not in g.armies:
            self.sel_army = None
        pid = g.player_id
        shown = 0
        kinds_count = {}
        for e in g.events:
            if pid not in e["fids"] and e["kind"] not in ("ranking", "victory", "eliminated", "war", "alert"):
                continue
            text = g.event_for_player(e)
            if text is None:                    # 조우하지 않은 세력끼리의 일
                continue
            kinds_count[e["kind"]] = kinds_count.get(e["kind"], 0) + 1
            if shown < 6 and e["kind"] in ("battle", "captured", "complete", "rebel", "war", "peace", "eliminated",
                                             "famine", "capital", "bomb", "victory", "diplo", "info", "alert"):
                col = {"battle": self.theme.bad, "war": self.theme.bad, "rebel": self.theme.warn,
                       "famine": self.theme.warn, "victory": self.theme.good, "alert": self.theme.bad}.get(e["kind"])
                self.toast(text, col)
                shown += 1
        if g.new_ranking:
            self.modal = ("ranking", g.new_ranking)
        if g.game_over:
            self.modal = ("gameover", None)

    # ------------------------------------------------------------ 상단 바
    def draw_topbar(self):
        """쪽빛 상단 바: 국기·국가명 / 날짜·절기 / 아이콘을 붙인 수치(마우스를 올리면 내역)."""
        from ..flags import faction_flag
        from ..leaders import GOV_BY_KEY
        from ..rules import date_of_turn
        from .art import draw_flag, indigo_band, ui_icon
        from .theme import solar_term
        g = self.game
        f = g.player
        gui = self.gui
        t = self.theme
        u = ui_scale()
        sw, _ = self.lsize()
        bar = pygame.Rect(0, 0, sw, TOP_H)
        pr = gui.R(bar)
        self.screen.blit(indigo_band(pr.w, pr.h, t.indigo, t.indigo_dk), pr.topleft)
        gui.line(t.gold, (0, TOP_H - 4), (sw, TOP_H - 4), 2)
        gui.line(mix(t.gold, t.indigo_dk, 0.4), (0, TOP_H - 1), (sw, TOP_H - 1), 1)
        gui.block(bar)
        paper = (247, 241, 227)
        dim = mix(t.gold_lt, t.indigo, 0.3)
        # 좌상단 일시정지: 저장·불러오기·도움말 등 게임 메뉴
        pc = (28, TOP_H // 2 - 1)
        pb = pygame.Rect(pc[0] - 17, pc[1] - 17, 34, 34)
        hov = gui.hover(pb)
        gui.circle(mix(t.indigo_dk, (255, 255, 255), 0.1) if hov else t.indigo_dk, pc, 17)
        gui.circle(t.gold, pc, 17, 1)
        ui_icon(self.screen, "pause", gui.P(*pc), t.gold_lt, u)
        if hov and gui.clicked:
            gui.clicked = False
            self.modal = ("pause", None)
        gui.rect(t.gold, (55, 11, 52, 34))
        draw_flag(gui, (57, 13, 48, 30), faction_flag(f))
        gov = GOV_BY_KEY.get(f.gov, {}).get("name", "체제 미정")
        gui.text((118, 5), f.name, 21, paper, "title", max_w=220)
        gui.text((120, 33), f"{f.leader_name} · {gov} · 수도 {self.world.regions[f.capital].short}", 11, dim,
                 "semibold", max_w=240)
        # 날짜 + 절기
        y_, m_, w_ = date_of_turn(g.turn)
        term, term_h = solar_term(m_, w_)
        dx = 470
        dr = gui.text((dx, 5), f"{y_}년 {m_}월 {w_}주", 19, paper, "title", anchor="midtop")
        chip = pygame.Rect(dr.right + 10, 9, 70, 20)
        gui.rect(t.indigo_dk, chip, radius=10)
        pygame.draw.rect(self.screen, t.gold, gui.R(chip), 1, border_radius=int(10 * u))
        gui.text((chip.x + 21, chip.centery), term, 11, t.gold_lt, "serif", anchor="center")
        gui.text((chip.x + 50, chip.centery), term_h, 11, t.gold_lt, "serif", anchor="center")
        gui.text((dx, 33), f"턴 {g.turn}", 11, dim, "semibold", anchor="midtop")
        x = sw - 14
        snap = self.snapshot()
        highlight = pygame.time.get_ticks() - self.prev_t < 600
        last = f.last
        good, bad = (143, 212, 174), (242, 163, 143)
        items = [
            ("happy", "face", "행복도", f"{snap['happy']:+d}", bad if snap["happy"] < 0 else None,
             f"실질 평균 행복도 {g.avg_happiness(f.id):+.1f} (피로·저항 반영 전 {g.avg_happiness(f.id, effective=False):+.1f})"),
            ("weary", "swords", "전쟁 피로", f"{snap['weary']:d}", bad if f.war_weary >= 1 else None,
             f"전쟁 피로도 {f.war_weary:.1f} / {C.WAR_WEARY_MAX:.0f}: 모든 지역 실질 행복도에서 빠집니다.\n"
             + (f"전쟁 중 턴당 +{D.war_weary_rate(g, f.id):.1f}" if D.enemies(g, f.id)
                else f"평시 턴당 {C.WAR_WEARY_RECOVERY:.0f} 회복")
),
            ("tax", "tax", "세율", f"{snap['tax']}%", None,
             f"세율 {f.tax * 100:.0f}% · 세수 {last.get('tax', 0):,.0f}/턴\n세율 효과 행복도 {g.tax_happy(f.id, f.tax * 100):+.1f}/턴"),
            ("food", "rice", "식량", f"{snap['food']:,.0f}", None,
             f"식량 생산 {last.get('food_prod',0):,.0f} / 소비 {last.get('food_cons',0):,.0f}"
             + (f"\n기근 {last.get('famine',0)*100:.0f}%" if last.get('famine') else "")),
            ("net", "coin", "턴당 순수익", f"{snap['net']:+,.0f}", good if snap["net"] >= 0 else bad,
             f"세수 {last.get('tax',0):,.0f} (세율 {f.tax*100:.0f}%)\n유지비 −{last.get('upkeep',0):,.0f}\n"
             f"구매 −{last.get('buy',0):,.0f} / 판매 +{last.get('sell',0):,.0f}\nGDP {last.get('gdp',0):,.0f}"),
            ("money", "coin", "자금(만원)", f"{snap['money']:,.0f}", bad if f.money < 0 else None,
             f"자금 {fmt_money(f.money)}원\n진행 중 슬롯 턴당 지출 "
             f"{sum(r.project.per_turn for r in g.regions_of(f.id) if r.project):,.0f}"),
        ]
        for key, ic, label, val, col, tip in items:
            vw = max(measure(val, 15, "semibold")[0], measure(label, 10, "semibold")[0]) + 30
            r = pygame.Rect(x - vw, 6, vw, TOP_H - 14)
            prev = self.prev_values.get(key)
            if highlight and prev is not None and self._differs(prev, snap[key]):
                gui.rect(mix(t.gold, t.indigo, 0.35), r, radius=4)
            ui_icon(self.screen, ic, gui.P(r.x + 10, r.y + 15), t.gold_lt, 0.85 * u)
            gui.text((r.x + 23, r.y + 2), val, 15, col or paper, "semibold")
            gui.text((r.x + 23, r.bottom - 3), label, 10, dim, "semibold", anchor="bottomleft")
            if gui.hover(r):
                gui.tooltip = tip
            x -= vw + 8

    @staticmethod
    def _differs(a, b):
        try:
            return abs(float(a) - float(b)) > 0.5
        except (TypeError, ValueError):
            return a != b

    # ------------------------------------------------------------ 하단
    def draw_mode_chips(self):
        """지도 모드: 왼쪽 아래 쪽빛 알약 막대(내용 폭만큼) + 지형 경계 토글·범례·배율."""
        from .art import indigo_band, ui_icon
        gui = self.gui
        t = self.theme
        u = ui_scale()
        sw, sh = self.lsize()
        widths = [measure(label, 13, "semibold")[0] + 38 for _, label in MAP_MODES]
        r = pygame.Rect(8, sh - 56, int(6 + sum(widths) + 4 * (len(widths) - 1) + 6), 44)
        gui.shadow(r, 22, 6)
        pr = gui.R(r)
        cache = self.__dict__.setdefault("_mode_band", {})
        band = cache.get(pr.size)
        if band is None:                       # 알약 모양 쪽빛 띠는 크기별로 한 번만 만든다
            band = indigo_band(pr.w, pr.h, t.indigo, t.indigo_dk, lattice=False).convert_alpha()
            mask = pygame.Surface(pr.size, pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=pr.h // 2)
            band.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            cache.clear()
            cache[pr.size] = band
        self.screen.blit(band, pr)
        pygame.draw.rect(self.screen, t.gold, pr, 1, border_radius=pr.h // 2)
        gui.block(r)
        popup = getattr(self, "mode_popup", None)
        bx = r.x + 6
        for (key, label), w in zip(MAP_MODES, widths):
            cell = pygame.Rect(bx, r.y + 5, w, 34)
            sel = self.mode == key
            hov = gui.hover(cell)
            if sel:
                gui.rect((247, 241, 227), cell, radius=17)
                pygame.draw.rect(self.screen, t.gold, gui.R(cell), 1, border_radius=int(17 * u))
            elif hov:
                gui.rect(mix(t.indigo, (255, 255, 255), 0.12), cell, radius=17)
            fg = t.indigo if sel else mix((247, 241, 227), t.indigo, 0.12)
            ui_icon(self.screen, MODE_ICONS.get(key, "flag"), gui.P(cell.x + 15, cell.centery), t.indigo if sel else t.gold_lt,
                    0.75 * u)
            gui.text((cell.x + 27, cell.centery), label, 13, fg, "bold" if sel else "semibold", anchor="midleft")
            if hov and gui.clicked:
                gui.clicked = False
                self.mode = key
                self.mode_popup = (None if popup == key else key) if key in SUB_MODES else None
                self.changed()
            if popup == key:
                self.draw_sub_menu(key, bx, r.y - 6, max(w, 74))
            bx += w + 4
        # 지형 경계 토글·범례·배율
        tr = pygame.Rect(r.right + 8, r.y, 186, 44)
        gui.panel(tr)
        on = gui.checkbox((tr.x + 10, tr.y + 3, 100, 20), "지형 경계", self.show_terrain, size=12)
        if on != self.show_terrain:
            self.show_terrain = on
            self.changed()
        from .mapview import TERRAIN_COLORS, draw_ridge_marks
        lx = tr.x + 12
        gui.line(TERRAIN_COLORS["도하"], (lx, tr.y + 33), (lx + 16, tr.y + 33), 3)
        gui.text((lx + 20, tr.y + 33), "강(도하)", 11, t.muted, anchor="midleft")
        mx = tr.x + 90
        draw_ridge_marks(self.screen, [gui.P(mx, tr.y + 36), gui.P(mx + 18, tr.y + 36)], u)
        gui.text((mx + 22, tr.y + 33), "산줄기", 11, t.muted, anchor="midleft")
        gui.text((tr.right - 10, tr.y + 6), f"×{self.map.z:.1f}", 11, t.muted, "semibold", anchor="topright")
        if gui.hover(tr):
            gui.tooltip = "지형 경계를 넘는 공격은 공격력 ×0.9\n강을 건너는 곳(도하)과 산줄기를 넘는 곳(산악 돌파)\n점선: 맞닿지 않은 하구·수로 경로"

    def draw_sub_menu(self, mode, x, bottom, w):
        """자원·건물·군사 세부 메뉴(칩 위로 펼침): 고른 한 가지만 지도에 단계별 색으로 표시."""
        gui = self.gui
        t = self.theme
        opts = SUB_MODES[mode]
        bh = 30
        pw = 128
        p = pygame.Rect(x, bottom - len(opts) * (bh + 4) - 12, pw, len(opts) * (bh + 4) + 8)
        gui.panel(p)
        cur = self.sub_mode(mode)[0]
        for i, (key, name, col, top) in enumerate(opts):
            row = pygame.Rect(p.x + 6, p.y + 6 + i * (bh + 4), pw - 12, bh)
            tip = None
            if gui.button(row, "", "ghost", selected=key == cur, tooltip=tip):
                self.sub_modes[mode] = key
                self.mode = mode
                self.mode_popup = None
                self.changed()
            c = hex2rgb(col)
            gui.rect(mix((241, 243, 245), c, 0.35), (row.x + 6, row.y + 8, 7, 14), radius=2)
            gui.rect(mix((241, 243, 245), c, 0.95), (row.x + 13, row.y + 8, 7, 14), radius=2)
            gui.text((row.x + 28, row.centery), name, 13, t.text, "semibold" if key == cur else "regular",
                     anchor="midleft")

    def review_queue(self):
        """아직 확인하지 않은 빈 슬롯 지역(수도 → 획득 순)."""
        g = self.game
        return [rid for rid in g.review_order(g.player_id)
                if rid not in self.visited and not g.regions[rid].project and not g.regions[rid].occ
                and not g.regions[rid].focus and not getattr(g.regions[rid], "pop_focus", False)]

    def next_region(self):
        q = self.review_queue()
        if not q:
            return False
        rid = q[0]
        self.visited.add(rid)
        self.select(rid)
        self.tab = "action"
        self.left_open = True
        self.map.center_on(rid, zoom=2.0 if self.map.z < 2.0 else None)
        return True

    def draw_end_turn(self):
        """턴 종료: 주홍 버튼(건국하기와 같은 모양). 빈 슬롯이 남았으면 [다음 지역](남은 수) + 위에 [바로 턴 종료]."""
        gui = self.gui
        g = self.game
        t = self.theme
        sw, sh = self.lsize()
        r = pygame.Rect(sw - 206, sh - 66, 194, 54)
        gui.block(r)
        queue = self.review_queue() if not g.game_over else []
        if queue:
            if gui.button(r, "다음 지역", "seal", size=19, weight="title"):
                self.next_region()
            skip = pygame.Rect(r.x, r.y - 42, r.w, 34)
            gui.block(skip)
            gui.shadow(skip, 4, 4)
            if gui.button(skip, "", "default"):
                self.end_turn()
            pygame.draw.rect(self.screen, t.vermilion, gui.R(skip), 1, border_radius=int(4 * gui.u))
            gui.text(skip.center, "바로 턴 종료", 15, t.vermilion, "title", anchor="center")
            c = (r.right - 4, r.y + 4)
            gui.circle(t.gold, c, 13)
            gui.circle(t.indigo_dk, c, 13, 2)
            gui.text(c, str(len(queue)), 12, t.indigo_dk, "bold", anchor="center")
        elif gui.button(r, "턴 종료", "seal", size=19, weight="title", enabled=not g.game_over):
            self.end_turn()

    def draw_compass(self):
        """지도 오른쪽 아래 나침반(윤도)과 축척."""
        gui = self.gui
        t = self.theme
        u = ui_scale()
        sw, sh = self.lsize()
        cx, cy = sw - 64, sh - 196
        R = 34
        pc = gui.P(cx, cy)
        Rp = int(R * u)
        o = Rp + 4
        ink = getattr(t, "sea_ink", t.muted)
        cached = getattr(self, "_compass", None)
        if cached and cached[0] == (Rp, t.dark):
            self.screen.blit(cached[1], (pc[0] - o, pc[1] - o - cached[2]))
            self._draw_scale(cx, cy, R, u, ink)
            return
        g = pygame.Surface((Rp * 2 + 8, Rp * 2 + 8), pygame.SRCALPHA)
        pygame.draw.circle(g, (*t.panel, 150), (o, o), Rp)
        pygame.draw.circle(g, (*ink, 200), (o, o), Rp, max(1, int(2 * u)))
        pygame.draw.circle(g, (*ink, 150), (o, o), int(Rp * 0.78), 1)
        for i in range(24):
            a = i / 24 * math.tau
            r1 = Rp * (0.86 if i % 3 else 0.72)
            pygame.draw.line(g, (*ink, 170), (o + math.cos(a) * r1, o + math.sin(a) * r1),
                             (o + math.cos(a) * Rp * 0.97, o + math.sin(a) * Rp * 0.97), 1)
        for i, col in enumerate((t.vermilion, ink, ink, ink)):
            a = -math.pi / 2 + i * math.pi / 2
            tip = (o + math.cos(a) * Rp * 0.7, o + math.sin(a) * Rp * 0.7)
            l_ = (o + math.cos(a + math.pi / 2) * Rp * 0.12, o + math.sin(a + math.pi / 2) * Rp * 0.12)
            r_ = (o + math.cos(a - math.pi / 2) * Rp * 0.12, o + math.sin(a - math.pi / 2) * Rp * 0.12)
            pygame.draw.polygon(g, (*col, 230), [tip, l_, (o, o), r_])
        north = __import__("korciv.ui.theme", fromlist=["render_text"]).render_text("北", 12, t.vermilion, "title")
        g2 = pygame.Surface((g.get_width(), g.get_height() + north.get_height()), pygame.SRCALPHA)
        g2.blit(g, (0, north.get_height()))
        g2.blit(north, north.get_rect(midtop=(o, 0)))
        self._compass = ((Rp, t.dark), g2, north.get_height())
        self.screen.blit(g2, (pc[0] - o, pc[1] - o - north.get_height()))
        self._draw_scale(cx, cy, R, u, ink)

    def _draw_scale(self, cx, cy, R, u, ink):
        gui = self.gui
        t = self.theme
        # 축척: 기준 좌표 1 = 위도 0.01° ≈ 1.11km
        km_per_px = 1.11 * u / max(1e-6, self.map.scale)
        target = 90 * km_per_px
        nice = min((10, 20, 25, 50, 100, 200), key=lambda v: abs(v - target))
        L = nice / km_per_px
        x0, y0 = cx - L / 2, cy + R + 14
        for i in range(4):
            gui.rect(ink if i % 2 == 0 else t.panel, (x0 + i * L / 4, y0, L / 4 + 1, 5))
        pygame.draw.rect(self.screen, ink, gui.R((x0, y0, L, 5)), 1)
        gui.text((x0, y0 + 7), "0", 10, ink, "semibold")
        gui.text((x0 + L, y0 + 7), f"{nice}km", 10, ink, "semibold", anchor="topright")

    def draw_toasts(self):
        """알림: 한지 쪽지(왼쪽에 색 띠)."""
        now = pygame.time.get_ticks()
        self.toasts = [t for t in self.toasts if now - t[2] < 6000]
        sw, _ = self.lsize()
        u = ui_scale()
        th_ = self.theme
        x = sw // 2
        y = TOP_H + 12
        for text, col, t0 in self.toasts:
            alpha = 1.0 if now - t0 < 5000 else 1 - (now - t0 - 5000) / 1000
            fg = th_.text if col is None or col == th_.text else col
            surf = render_text(text, 13, fg, "semibold")
            tw, th = surf.get_width() / u, surf.get_height() / u
            lr = pygame.Rect(0, 0, int(tw + 34), int(th + 14))
            lr.midtop = (x, y)
            pr = self.gui.R(lr)
            bg = pygame.Surface(pr.size, pygame.SRCALPHA)
            pygame.draw.rect(bg, (*th_.panel, int(240 * alpha)), bg.get_rect(), border_radius=int(4 * u))
            pygame.draw.rect(bg, (*mix(th_.gold, th_.text, 0.2), int(255 * alpha)), bg.get_rect(), 1, border_radius=int(4 * u))
            pygame.draw.rect(bg, (*(fg if fg != th_.text else th_.indigo), int(255 * alpha)), (0, 0, max(2, int(4 * u)), pr.h))
            self.screen.blit(bg, pr)
            surf.set_alpha(int(255 * alpha))
            self.screen.blit(surf, surf.get_rect(center=(pr.centerx + int(2 * u), pr.centery)))
            y += lr.h + 6

    # ------------------------------------------------------------ 외교
    def open_diplomacy(self, fid):
        self.dip_state = modals.DiploDraft(fid)
        self.modal = ("diplomacy", fid)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="한반도의 문명")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--screenshot", help="몇 프레임 뒤 스크린샷을 저장하고 종료(테스트용)")
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--quickstart", action="store_true", help="설정 화면 없이 기본값으로 바로 시작")
    ap.add_argument("--turns", type=int, default=0, help="quickstart 후 자동으로 진행할 턴 수")
    args = ap.parse_args(argv)
    app = App(args.width, args.height, screenshot=args.screenshot)
    if args.quickstart:
        app.start_game(Settings(seed=7))
        app.game.set_player_government("presidential")
        app.scene = "main"
        for _ in range(args.turns):
            app.game.pending_rebellions and [app.game.resolve_rebellion(app.game.player_id, r, "tax")
                                             for r in list(app.game.pending_rebellions)]
            app.game.pending_proposals = []
            from .. import ai
            ai.plan_turn(app.game, app.game.player_id)
            app.game.end_turn()
        app.game.pending_proposals = []
        app.changed()
    app.run(max_frames=args.frames or None)


if __name__ == "__main__":
    main(sys.argv[1:])
