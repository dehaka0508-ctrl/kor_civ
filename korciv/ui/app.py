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
from ..game import Game
from ..state import NEUTRAL, Army, Settings
from . import modals, panels
from .gui import Gui
from .mapview import MapView
from .theme import Theme, desaturate, fmt_money, hex2rgb, measure, mix, render_text, set_ui_scale, ui_scale

SAVE_DIR = os.path.join(os.path.expanduser("~"), ".korciv", "saves")
TOP_H = 56
LEFT_W = 360
RIGHT_W = 320
MAP_MODES = [("political", "정치"), ("happy", "행복도"), ("pop", "인구"), ("resource", "자원"),
             ("military", "군사"), ("opinion", "우호도"), ("do8", "조선 8도")]
DO8_COLORS = {"경기": "#A5D8FF", "충청": "#B2F2BB", "전라": "#FFEC99", "경상": "#FFC9C9",
              "강원": "#D0BFFF", "황해": "#FFD8A8", "평안": "#99E9F2", "함경": "#E9ECEF"}


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
        self.scene = "setup"
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
        self.lm_name = ""
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
            pickle.dump(self.game, f)
        self.toast(f"저장했습니다: {path}")
        return True

    @staticmethod
    def slot_info(slot: int):
        """저장 슬롯(1~3) 정보: 없으면 None, 있으면 {"path", "mtime", "label"}."""
        path = os.path.join(SAVE_DIR, f"slot{slot}.sav")
        if not os.path.exists(path):
            return None
        info = {"path": path, "mtime": os.path.getmtime(path), "label": ""}
        try:
            with open(path, "rb") as f:
                g = pickle.load(f)
            info["label"] = f"{g.player.name} · {g.date_label()} · 지역 {g.region_count(g.player_id)}곳"
        except Exception:
            info["label"] = "(읽을 수 없는 파일)"
        return info

    def open_slots(self, mode):
        """mode: save / save_exit / load — 슬롯 선택 창."""
        self.slot_cache = {i: self.slot_info(i) for i in range(1, C.SAVE_SLOTS + 1)}
        self.modal = ("saveslots", mode)

    def load(self, name="slot1"):
        path = os.path.join(SAVE_DIR, name + ".sav")
        if not os.path.exists(path):
            self.toast("저장 파일이 없습니다.", self.theme.bad)
            return
        with open(path, "rb") as f:
            self.game = pickle.load(f)
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
        if self.scene == "setup":
            slots_open = bool(self.modal and self.modal[0] == "saveslots")
            flag_open = self.setup.flag_draft is not None
            self.gui.input_enabled = not (slots_open or flag_open)
            modals.draw_setup(self)
            self.gui.input_enabled = True
            if slots_open:
                modals.draw_save_slots(self)
            elif flag_open:
                modals.draw_flag_editor(self)
        elif self.scene == "pick_start":
            self.draw_pick_start()
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
        for rid in self.world.order:
            info = self.world.regions[rid]
            if not g or pick_mode:
                fill = t.neutral
                if pick_mode and rid in (self.pick_popup, self.setup.start):
                    fill = t.accent
                out[rid] = (fill, mix(fill, (255, 255, 255), 0.7))
                continue
            r = g.regions[rid]
            owner = r.owner
            explored = not fog_on or g.is_explored(pid, rid)
            visible = not fog_on or g.is_visible(pid, rid)
            if not explored:
                fill = t.unexplored
                out[rid] = (fill, mix(fill, (255, 255, 255), 0.5))
                continue
            if not visible:
                owner = g.player.last_seen.get(rid, owner)
            fill = self.mode_color(rid, r, owner, info)
            if self.mode == "political" and visible and owner == pid and r.project:
                # 생산·행동이 진행 중인 내 지역은 더 진한 색
                fill = mix(self.faction_rgb(owner), (0, 0, 0), 0.18)
            if not visible:
                fill = mix(desaturate(fill, 0.7), (0, 0, 0), 0.25)
            out[rid] = (fill, mix(fill, (255, 255, 255), 0.7))
        return out

    def faction_rgb(self, fid):
        if fid == NEUTRAL:
            return self.theme.neutral
        return hex2rgb(self.game.factions[fid].color)

    def owner_fill(self, owner):
        if owner == NEUTRAL:
            return self.theme.neutral
        return mix(self.faction_rgb(owner), (255, 255, 255), 0.3)

    def mode_color(self, rid, r, owner, info):
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
        if m == "resource":
            base = mix(self.owner_fill(owner), t.neutral, 0.75)
            if info.is_oil:
                return hex2rgb("#343A40")
            if info.is_coal:
                return hex2rgb("#8D6E63")
            if info.power_self:
                return hex2rgb("#FAB005")
            if info.power_site:
                return hex2rgb("#FFD8A8")
            if info.specialty:
                return mix(base, hex2rgb("#40C057"), 0.45)
            return base
        if m == "military":
            base = mix(self.owner_fill(owner), t.neutral, 0.7)
            if not g.is_visible(g.player_id, rid):
                return base
            pw = sum(g.army_power(a) for a in g.armies_at(rid) if a.owner != NEUTRAL)
            if pw <= 0:
                return base
            mine = owner == g.player_id
            x = min(1.0, pw / 400)
            return mix(base, hex2rgb("#1C7ED6") if mine else hex2rgb("#E03131"), 0.25 + 0.75 * x)
        if m == "opinion":
            if owner == NEUTRAL:
                return t.neutral
            if owner == g.player_id:
                return mix(self.faction_rgb(owner), (255, 255, 255), 0.3)
            if D.at_war(g, owner, g.player_id):
                return hex2rgb("#C92A2A")
            op = D.opinion(g, owner, g.player_id)
            return mix(t.happy_mid, t.happy_pos, op / 100) if op >= 0 else mix(t.happy_mid, t.happy_neg, -op / 100)
        if m == "do8":
            c = hex2rgb(DO8_COLORS[info.do8])
            if owner != NEUTRAL:
                c = mix(c, self.faction_rgb(owner), 0.35)
            return c
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
        key = ("pick", self.setup.start, self.pick_popup) if pick_mode else (self.mode, self.fog_reveal, id(self.game),
                                                              self.game.turn if self.game else 0,
                                                              self.show_terrain, busy)
        # 색·지명은 지도를 다시 그릴 때만 계산한다(매 프레임 계산하지 않음)
        mv.draw_base(self.screen, key, self.theme, lambda: self.region_colors(pick_mode), self.sea_colors,
                     self.mode, self.map_labels, show_terrain=self.show_terrain)
        self.screen.set_clip(mv.view)
        u = ui_scale()
        if pick_mode:
            if self.hover and self.hover in self.world.regions:
                mv.outline(self.screen, self.hover, self.theme.text, max(2, int(2 * u)))
            if self.setup.start:
                mv.outline(self.screen, self.setup.start, (255, 255, 255), max(3, int(3 * u)))
            self.screen.set_clip(None)
            return
        g = self.game
        # 이동 범위
        army = g.armies.get(self.sel_army) if self.sel_army else None
        if army and army.owner == g.player_id:
            reach = g.reachable(army)
            ov = pygame.Surface(mv.view.size, pygame.SRCALPHA)
            # 해역을 먼저 칠해야 섬 구멍을 비워도 육지 오버레이가 지워지지 않는다
            for node, opt in sorted(reach.items(), key=lambda kv: not self.world.is_sea(kv[0])):
                col = {"move": (47, 111, 222), "attack": (201, 42, 42), "land": (12, 166, 120),
                       "bombard": (230, 119, 0)}[opt["action"]]
                a = 115 if opt["strong"] else 60
                if self.world.is_sea(node):
                    mv.sea_overlay(ov, node, (*col, 45))
                else:
                    mv.fill_overlay(ov, node, (*col, a))
            self.screen.blit(ov, mv.view.topleft)
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
                mv.outline(self.screen, self.sel, (255, 255, 255), max(4, int(4 * u)))
                mv.outline(self.screen, self.sel, self.theme.text, max(2, int(2 * u)))
        # 전투 강조 (1초)
        dt = pygame.time.get_ticks() - self.flash_t
        if dt < 1200 and g.battle_regions:
            a = 1 - dt / 1200
            col = mix((255, 255, 255), (224, 49, 49), a)
            for rid in set(g.battle_regions):
                if rid in self.world.regions:
                    mv.outline(self.screen, rid, col, 3)
        self.draw_landmarks()
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
        cx, cy = center
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.45
            pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
        pygame.draw.polygon(self.screen, color, pts)
        pygame.draw.polygon(self.screen, (255, 255, 255), pts, 1)

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
            self.star((x, y - (16 * u if self.map.z >= 2 else 0)), (8 if self.map.z < 2 else 10) * u,
                      mix(self.faction_rgb(f.id), (0, 0, 0), 0.2))

    def draw_landmarks(self):
        g = self.game
        mv = self.map
        pid = g.player_id
        for r in g.regions.values():
            building = r.project and r.project.kind == "landmark"
            if not (r.landmark or building):
                continue
            if not (r.owner == pid or g.is_explored(pid, r.id) or self.fog_reveal):
                continue
            x, y = mv.label_screen(r.id)
            if not mv.view.collidepoint(x, y):
                continue
            u = ui_scale()
            x += (18 if mv.z >= 2 else 9) * u
            y -= (16 if mv.z >= 2 else 7) * u
            col = (241, 196, 15) if r.landmark else (180, 180, 180)
            tri = [(x, y - 11 * u), (x + 5 * u, y + 7 * u), (x - 5 * u, y + 7 * u)]
            pygame.draw.polygon(self.screen, col, tri)
            pygame.draw.polygon(self.screen, mix(col, (0, 0, 0), 0.4), tri, 1)
            pygame.draw.line(self.screen, mix(col, (0, 0, 0), 0.4), (x - 7 * u, y + 7 * u), (x + 7 * u, y + 7 * u),
                             max(2, int(2 * u)))
            if mv.z >= 3 and r.landmark:
                t = render_text(r.landmark_name or g.default_landmark_name(r.id), 11, (122, 88, 0), "bold")
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
                self.arrow(pts, ORDER_COLORS["move"])
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
                    self.dashed(p, q, ORDER_COLORS["move"])
                self.arrowhead(pts[-2], pts[-1], ORDER_COLORS["move"], outline=True)

    def arrow(self, pts, color):
        """영토 색과 겹치지 않도록 검은 테두리를 두른 굵은 화살표."""
        u = ui_scale()
        pygame.draw.lines(self.screen, (255, 255, 255), False, pts, max(5, int(5 * u)))
        pygame.draw.lines(self.screen, color, False, pts, max(3, int(3 * u)))
        self.arrowhead(pts[-2], pts[-1], color, outline=True)

    def arrowhead(self, p1, p2, color, outline=False):
        ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        L = 13 * ui_scale()
        pts = [p2, (p2[0] - L * math.cos(ang - 0.45), p2[1] - L * math.sin(ang - 0.45)),
               (p2[0] - L * math.cos(ang + 0.45), p2[1] - L * math.sin(ang + 0.45))]
        pygame.draw.polygon(self.screen, color, pts)
        if outline:
            pygame.draw.polygon(self.screen, (255, 255, 255), pts, max(1, int(1 * ui_scale())))

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
        for loc, arms in by_loc.items():
            x, y = mv.label_screen(loc)
            if not mv.view.collidepoint(x, y):
                continue
            arms.sort(key=lambda a: (a.owner != pid, a.owner, a.id))
            u = ui_scale()
            w = int((34 if mv.z < 2 else 42) * u)
            ph = int(19 * u)
            n = len(arms)
            start = x - (n * (w + 2)) / 2
            yy = y + (10 if mv.z >= 2 else 5) * u
            if mv.z >= 4 and not self.world.is_sea(loc):
                yy += 14 * u
            for i, a in enumerate(arms):
                r = pygame.Rect(int(start + i * (w + 2)), int(yy), w, ph)
                col = (120, 120, 120) if a.owner == NEUTRAL else self.faction_rgb(a.owner)
                pygame.draw.rect(self.screen, col, r, border_radius=4)
                if a.id == self.sel_army:
                    pygame.draw.rect(self.screen, (255, 212, 59), r.inflate(4, 4), 2, border_radius=5)
                else:
                    pygame.draw.rect(self.screen, mix(col, (0, 0, 0), 0.35), r, 1, border_radius=4)
                icon_key = max(a.units, key=lambda k: a.units[k] * C.UNITS[k]["cost"])
                panels.unit_icon(self.screen, icon_key, (r.x + int(9 * u), r.centery), (255, 255, 255), 1.1 * u)
                t = render_text(str(a.count()), 11, (255, 255, 255), "bold")
                self.screen.blit(t, t.get_rect(midright=(r.right - int(3 * u), r.centery)))
                if a.order and a.owner == pid:
                    pygame.draw.circle(self.screen, (255, 212, 59), (r.right - 1, r.y + 1), max(3, int(3.5 * u)))
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
        self.left_open = True
        if hidden is not None:
            # 시야 밖 타국 영토: 외교 탭의 그 세력 상세 화면
            self.left_tab, self.dip_view, self.war_confirm = "diplo", hidden, None
        elif g.regions.get(node) is None:
            # 해역: 내 함대가 있으면 [부대], 없으면 해역 정보
            self.left_tab, self.tab = "region", ("army" if mine else "info")
        else:
            # 지역을 누르면 [행동](내 지역이 아니면 할 행동이 없으니 [지역 정보])
            self.left_tab, self.tab = "region", ("action" if g.regions[node].owner == g.player_id else "info")

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
        g.text((r.x + 12, r.y + 8), self.game.fname(fid), 13, weight="bold")
        if g.button((r.x + 8, r.y + 30, 154, 22), "외교", "ghost"):
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
                    lines.append(f"공격력 A {pv['A']:.0f} / 방어력 D {pv['D']:.0f} (방어선 {pv['line']}단계)")
                    if pv.get("terrain"):
                        tr = pv["terrain"]
                        lines.append(f"{tr['label']}({tr['name']}·{tr['note']}) 공격 ×{tr['mult']}")
                    if mode == "surprise":
                        lines.append(f"기습 성공률 {pv['surprise_p']*100:.0f}%")
                        lines.append(f"성공 시 적 피해 {pv['def_dmg_win']:.0f} / 아군 {pv['att_dmg_win']:.0f}")
                        lines.append(f"실패 시 적 피해 {pv['def_dmg_fail']:.0f} / 아군 {pv['att_dmg_fail']:.0f}")
                    else:
                        lines.append(f"기대 피해: 적 {pv['def_dmg']:.0f} / 아군 {pv['att_dmg']:.0f} (체력 기준)")
                    lines.append(f"적 총 체력 {pv['def_hp']:.0f}")
        self.gui.tooltip = "\n".join(lines)

    def keyboard(self):
        g = self.gui
        for k in list(g.keys):
            if g.focus:
                continue
            if k.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
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
            elif k.key == pygame.K_LEFT:
                self.map.pan(80, 0)
            elif k.key == pygame.K_RIGHT:
                self.map.pan(-80, 0)
            elif k.key == pygame.K_UP:
                self.map.pan(0, 80)
            elif k.key == pygame.K_DOWN:
                self.map.pan(0, -80)
            elif pygame.K_1 <= k.key <= pygame.K_7:
                self.mode = MAP_MODES[k.key - pygame.K_1][0]
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
        idle = [r.id for r in g.regions_of(g.player_id) if not r.project and not r.occ]
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
        return {"money": f.money, "net": f.last.get("net", 0), "food": f.res["food"], "oil": f.res["oil"],
                "coal": f.res["coal"], "elec": f.res["elec"], "happy": round(self.game.avg_happiness(f.id)),
                "weary": round(f.war_weary)}

    def end_turn(self):
        g = self.game
        if g.game_over or self.active_modal():
            return
        before = self.snapshot()
        g.end_turn()
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
            if pid not in e["fids"] and e["kind"] not in ("ranking", "victory", "eliminated", "war"):
                continue
            kinds_count[e["kind"]] = kinds_count.get(e["kind"], 0) + 1
            if shown < 6 and e["kind"] in ("battle", "captured", "complete", "rebel", "war", "peace", "eliminated",
                                             "famine", "capital", "bomb", "victory", "diplo", "info"):
                col = {"battle": self.theme.bad, "war": self.theme.bad, "rebel": self.theme.warn,
                       "famine": self.theme.warn, "victory": self.theme.good}.get(e["kind"])
                self.toast(e["text"], col)
                shown += 1
        if g.new_ranking:
            self.modal = ("ranking", g.new_ranking)
        if g.game_over:
            self.modal = ("gameover", None)

    # ------------------------------------------------------------ 상단 바
    def draw_topbar(self):
        g = self.game
        f = g.player
        gui = self.gui
        sw, _ = self.lsize()
        gui.panel((0, 0, sw, TOP_H), radius=0, shadow=True, border=False)
        gui.line(self.theme.border, (0, TOP_H - 1), (sw, TOP_H - 1))
        # 좌상단 일시정지: 저장·불러오기·도움말 등 게임 메뉴
        pb = pygame.Rect(10, 10, 36, 36)
        if gui.button(pb, "", tooltip="일시정지 (P, 선택이 없을 때 Esc) — 저장·불러오기·도움말"):
            self.modal = ("pause", None)
        for dx in (-5, 5):
            gui.rect(self.theme.text, (pb.centerx + dx - 2, pb.centery - 8, 5, 16), radius=1)
        from ..flags import faction_flag
        from .art import draw_flag
        draw_flag(gui, (56, 12, 48, 32), faction_flag(f))
        from ..leaders import GOV_BY_KEY
        gov = GOV_BY_KEY.get(f.gov, {}).get("name", "체제 미정")
        gui.text((114, 8), f.name, 18, weight="bold")
        gui.text((114, 32), f"{f.leader_name} · {gov} · 수도 {self.world.regions[f.capital].short}", 12,
                 self.theme.muted)
        gui.text((sw // 2 - 90, TOP_H // 2), g.date_label(), 16, weight="bold", anchor="center")
        x = sw - 16
        snap = self.snapshot()
        highlight = pygame.time.get_ticks() - self.prev_t < 600
        last = f.last
        items = [
            ("happy", "행복도", f"{snap['happy']:+d}", None,
             f"실질 평균 행복도 {g.avg_happiness(f.id):+.1f}\n(전쟁 피로·징집 피로·점령 저항 반영 전 "
             f"{g.avg_happiness(f.id, effective=False):+.1f})\n세율 효과 {0.1*(10-f.tax*100):+.1f}/턴"),
            ("weary", "전쟁 피로", f"{snap['weary']:d}", self.theme.bad if f.war_weary >= 1 else None,
             f"전쟁 피로도 {f.war_weary:.1f} / {C.WAR_WEARY_MAX:.0f}: 모든 지역 실질 행복도에서 빠집니다.\n"
             + (f"전쟁 중 턴당 +{D.war_weary_rate(g, f.id):.1f}" if D.enemies(g, f.id)
                else f"평시 턴당 {C.WAR_WEARY_RECOVERY:.0f} 회복")
             + f"\n선전포고 +{C.WAR_WEARY_START['aggressor']:.0f}·턴당 +{C.WAR_WEARY_TURN['aggressor']:g}, "
             f"당하면 +{C.WAR_WEARY_START['defender']:.0f}·턴당 +{C.WAR_WEARY_TURN['defender']:g}"),
            ("elec", "전기", f"{snap['elec']:.0f}", None, "전기: 발전소(석탄 1→2, 석유 1→4)·자체 발전으로 생산, 공장 연료\n"
             "에너지 자원은 살 수 없고 팔 수만 있습니다. 배정: 국가 현황 옆 [자원 배정] 탭"),
            ("coal", "석탄", f"{snap['coal']:.0f}", None, "석탄: 탄광 생산, 공장 연료·발전소 연료, 석유 대신 군 생산(석유 1 = 석탄 2)"),
            ("oil", "석유", f"{snap['oil']:.0f}", None, "석유: 유전 생산, 군 생산·발전소(전기 4)·공장 연료"),
            ("food", "식량", f"{snap['food']:,.0f}", None,
             f"식량 생산 {last.get('food_prod',0):,.0f} / 소비 {last.get('food_cons',0):,.0f}"
             + (f"\n기근 {last.get('famine',0)*100:.0f}%" if last.get('famine') else "")),
            ("net", "턴당 순수익", f"{snap['net']:+,.0f}", self.theme.good if snap["net"] >= 0 else self.theme.bad,
             f"세수 {last.get('tax',0):,.0f} (세율 {f.tax*100:.0f}%)\n유지비 −{last.get('upkeep',0):,.0f}\n"
             f"시장 구매 −{last.get('buy',0):,.0f} / 판매 +{last.get('sell',0):,.0f}\nGDP {last.get('gdp',0):,.0f}"),
            ("money", "자금(만원)", f"{snap['money']:,.0f}", self.theme.bad if f.money < 0 else None,
             f"자금 {fmt_money(f.money)}원\n진행 중 슬롯 턴당 지출 "
             f"{sum(r.project.per_turn for r in g.regions_of(f.id) if r.project):,.0f}"),
        ]
        for key, label, val, col, tip in items:
            vw = max(measure(val, 15, "semibold")[0], measure(label, 11)[0]) + 22
            r = pygame.Rect(x - vw, 6, vw, TOP_H - 12)
            prev = self.prev_values.get(key)
            if highlight and prev is not None and self._differs(prev, snap[key]):
                gui.rect((255, 243, 191), r, radius=6)
            gui.text((r.centerx, r.y + 4), label, 11, self.theme.muted, anchor="midtop")
            gui.text((r.centerx, r.bottom - 4), val, 15, col or self.theme.text, "semibold", anchor="midbottom")
            if gui.hover(r):
                gui.tooltip = tip
            x -= vw + 4

    @staticmethod
    def _differs(a, b):
        try:
            return abs(float(a) - float(b)) > 0.5
        except (TypeError, ValueError):
            return a != b

    # ------------------------------------------------------------ 하단
    def draw_mode_chips(self):
        gui = self.gui
        sw, sh = self.lsize()
        w = 74
        r = pygame.Rect(12, sh - 60, len(MAP_MODES) * (w + 4) + 12, 48)
        gui.panel(r)
        for i, (key, label) in enumerate(MAP_MODES):
            tip = f"지도 모드 ({i+1})" + ("\n내 영토 중 진한 색 = 생산·행동 진행 중" if key == "political" else "")
            if gui.button((r.x + 8 + i * (w + 4), r.y + 8, w, 32), label, selected=self.mode == key,
                          tooltip=tip):
                self.mode = key
                self.changed()
        # 지형 경계 토글·범례
        t = pygame.Rect(r.right + 8, r.y, 176, 48)
        gui.panel(t)
        on = gui.checkbox((t.x + 10, t.y + 4, 150, 20), "지형 경계", self.show_terrain, size=12)
        if on != self.show_terrain:
            self.show_terrain = on
            self.changed()
        from .mapview import TERRAIN_COLORS
        for i, (kind, label) in enumerate((("도하", "도하"), ("돌파", "산악 돌파"))):
            lx = t.x + 12 + i * 70
            gui.line(TERRAIN_COLORS[kind], (lx, t.y + 36), (lx + 16, t.y + 36), 4)
            gui.text((lx + 20, t.y + 36), label, 11, self.theme.muted, anchor="midleft")
        if gui.hover(t):
            gui.tooltip = "지형 경계를 넘는 공격은 공격력 ×0.9\n점선: 맞닿지 않은 하구·수로 경로"
        # 줌 표시
        gui.text((t.right + 10, r.centery), f"×{self.map.z:.1f}", 12, self.theme.muted, anchor="midleft")

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
        gui = self.gui
        g = self.game
        sw, sh = self.lsize()
        r = pygame.Rect(sw - 172, sh - 68, 160, 56)
        gui.block(r)
        queue = self.review_queue() if not g.game_over else []
        if queue:
            if gui.button(r, "다음 지역", "primary", size=17, weight="bold", radius=10, color=self.theme.warn,
                          tooltip="생산·행동이 비어 있는 지역을 수도부터 획득 순서대로 엽니다 (Enter)"):
                self.next_region()
            skip = pygame.Rect(r.x, r.y - 36, r.w, 30)
            gui.block(skip)
            if gui.button(skip, "바로 턴 종료", "default", size=12, tooltip="남은 지역을 건너뛰고 턴 종료 (Shift+Enter)"):
                self.end_turn()
            c = (r.right - 6, r.y + 6)
            gui.circle(self.theme.bad, c, 14)
            gui.text(c, str(len(queue)), 12, (255, 255, 255), "bold", anchor="center")
            if gui.hover(pygame.Rect(c[0] - 13, c[1] - 13, 26, 26)):
                gui.tooltip = f"확인하지 않은 빈 슬롯 지역 {len(queue)}곳"
        elif gui.button(r, "턴 종료", "primary", size=17, weight="bold", tooltip="Enter", radius=10,
                        enabled=not g.game_over):
            self.end_turn()

    def draw_toasts(self):
        now = pygame.time.get_ticks()
        self.toasts = [t for t in self.toasts if now - t[2] < 6000]
        sw, _ = self.lsize()
        u = ui_scale()
        x = sw // 2
        y = TOP_H + 12
        for text, col, t0 in self.toasts:
            alpha = 1.0 if now - t0 < 5000 else 1 - (now - t0 - 5000) / 1000
            surf = render_text(text, 13, (255, 255, 255), "semibold")
            tw, th = surf.get_width() / u, surf.get_height() / u
            lr = pygame.Rect(0, 0, int(tw + 30), int(th + 14))
            lr.midtop = (x, y)
            pr = self.gui.R(lr)
            bg = pygame.Surface(pr.size, pygame.SRCALPHA)
            base = (33, 37, 41) if col is None or col == self.theme.text else col
            pygame.draw.rect(bg, (*base, int(230 * alpha)), bg.get_rect(), border_radius=int(8 * u))
            self.screen.blit(bg, pr)
            surf.set_alpha(int(255 * alpha))
            self.screen.blit(surf, surf.get_rect(center=pr.center))
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
