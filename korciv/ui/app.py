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
from ..state import NEUTRAL, Settings
from . import modals, panels
from .gui import Gui
from .mapview import MapView
from .theme import Theme, desaturate, fmt_money, hex2rgb, mix, render_text

SAVE_DIR = os.path.join(os.path.expanduser("~"), ".korciv", "saves")
TOP_H = 56
LEFT_W = 360
RIGHT_W = 320
MAP_MODES = [("political", "정치"), ("happy", "행복도"), ("pop", "인구"), ("resource", "자원"),
             ("military", "군사"), ("opinion", "우호도"), ("do8", "조선 8도")]
DO8_COLORS = {"경기": "#A5D8FF", "충청": "#B2F2BB", "전라": "#FFEC99", "경상": "#FFC9C9",
              "강원": "#D0BFFF", "황해": "#FFD8A8", "평안": "#99E9F2", "함경": "#E9ECEF"}


class App:
    def __init__(self, width=1440, height=900, screenshot=None):
        pygame.init()
        pygame.display.set_caption("한반도 시군구 문명")
        flags = pygame.RESIZABLE
        self.screen = pygame.display.set_mode((width, height), flags)
        self.clock = pygame.time.Clock()
        self.theme = Theme()
        self.gui = Gui(self.screen, self.theme)
        self.world = load_world()
        self.map = MapView(self.world)
        self.game: Game | None = None
        self.scene = "setup"
        self.setup = modals.SetupState()
        self.running = True
        self.screenshot = screenshot
        self.reset_ui()

    def reset_ui(self):
        self.sel = None              # 선택한 구역/해역 ID
        self.sel_army = None
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

    # ------------------------------------------------------------ 게임 시작·저장
    def start_game(self, settings: Settings):
        self.game = Game(settings, self.world)
        self.reset_ui()
        self.scene = "government"
        self.map.z = 1.0
        self.map.center_on(self.game.player.capital, zoom=2.2)
        self.sel = self.game.player.capital

    def save(self, name="quicksave"):
        if not self.game:
            return
        os.makedirs(SAVE_DIR, exist_ok=True)
        path = os.path.join(SAVE_DIR, name + ".sav")
        with open(path, "wb") as f:
            pickle.dump(self.game, f)
        self.toast(f"저장했습니다: {path}")

    def load(self, name="quicksave"):
        path = os.path.join(SAVE_DIR, name + ".sav")
        if not os.path.exists(path):
            self.toast("저장 파일이 없습니다.", self.theme.bad)
            return
        with open(path, "rb") as f:
            self.game = pickle.load(f)
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
                    w, h = max(1280, e.w), max(800, e.h)
                    self.screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)
                    self.gui.screen = self.screen
            self.gui.begin(events)
            self.frame()
            pygame.display.flip()
            self.clock.tick(60)
            frames += 1
            if max_frames and frames >= max_frames:
                if self.screenshot:
                    pygame.image.save(self.screen, self.screenshot)
                break
        pygame.quit()

    def frame(self):
        self.screen.fill(self.theme.bg)
        if self.scene == "setup":
            modals.draw_setup(self)
        elif self.scene == "pick_start":
            self.draw_pick_start()
        elif self.scene in ("government", "main"):
            self.draw_main()
        self.gui.draw_tooltip()

    # ------------------------------------------------------------ 시작 구역 고르기
    def draw_pick_start(self):
        sw, sh = self.screen.get_size()
        self.map.set_view((0, TOP_H, sw, sh - TOP_H))
        self.draw_map(pick_mode=True)
        g = self.gui
        g.panel((0, 0, sw, TOP_H), radius=0, shadow=False)
        g.text((20, TOP_H // 2), "시작 구역을 클릭해 고르세요", 18, weight="bold", anchor="midleft")
        chosen = self.setup.start
        if chosen:
            info = self.world.regions[chosen]
            g.text((360, TOP_H // 2), f"선택: {info.name} · 인구 {info.pop0:.1f}만 · 산출 {info.output0:,.0f}",
                   15, anchor="midleft")
        if g.button((sw - 300, 10, 130, 36), "이 구역에서 시작", "primary", enabled=bool(chosen)):
            self.scene = "setup"
        if g.button((sw - 160, 10, 140, 36), "취소(무작위)"):
            self.setup.start = None
            self.scene = "setup"
        self.map_input(pick_mode=True)

    # ------------------------------------------------------------ 메인 화면
    def draw_main(self):
        game = self.game
        sw, sh = self.screen.get_size()
        self.map.set_view((0, TOP_H, sw, sh - TOP_H))
        modal_open = self.scene == "government" or self.active_modal() is not None
        self.gui.input_enabled = not modal_open
        self.draw_map()
        self.draw_topbar()
        if self.sel and self.left_open:
            panels.draw_left(self, pygame.Rect(12, TOP_H + 12, LEFT_W, sh - TOP_H - 90))
        elif self.sel:
            if self.gui.button((12, TOP_H + 12, 36, 36), "›", tooltip="구역 정보 펼치기"):
                self.left_open = True
        panels.draw_right(self, pygame.Rect(sw - RIGHT_W - 12, TOP_H + 12, RIGHT_W, sh - TOP_H - 96))
        self.draw_mode_chips()
        self.draw_end_turn()
        self.draw_toasts()
        if self.ctx_menu:
            self.draw_ctx_menu()
        if not modal_open:
            self.map_input()
            self.keyboard()
        self.gui.input_enabled = True
        if self.scene == "government":
            modals.draw_government(self)
        else:
            modals.draw_active_modal(self)

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
            if not g:
                fill = t.neutral
                if pick_mode and self.setup.start == rid:
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
            h = r.happy
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
        key = ("pick", self.setup.start) if pick_mode else (self.mode, self.fog_reveal, id(self.game),
                                                              self.game.turn if self.game else 0)
        base = mv.render_base(key, self.theme, self.region_colors(pick_mode), self.sea_colors(), self.mode,
                              self.map_labels())
        self.screen.blit(base, mv.view.topleft)
        self.gui.push_clip(mv.view)
        if pick_mode:
            if self.hover and self.hover in self.world.regions:
                mv.outline(self.screen, self.hover, self.theme.text, 2)
            if self.setup.start:
                mv.outline(self.screen, self.setup.start, (255, 255, 255), 3)
            self.gui.pop_clip()
            return
        g = self.game
        # 이동 범위
        army = g.armies.get(self.sel_army) if self.sel_army else None
        if army and army.owner == g.player_id:
            reach = g.reachable(army)
            ov = pygame.Surface(mv.view.size, pygame.SRCALPHA)
            for node, opt in reach.items():
                col = {"move": (47, 111, 222), "attack": (201, 42, 42), "land": (12, 166, 120),
                       "bombard": (230, 119, 0)}[opt["action"]]
                a = 115 if opt["strong"] else 60
                if self.world.is_sea(node):
                    pts = [(x - mv.view.x, y - mv.view.y) for x, y in mv._screen_poly(mv.sea_polys[node])]
                    pygame.draw.polygon(ov, (*col, 45), pts)
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
                mv.outline(self.screen, self.sel, (255, 255, 255), 4)
                mv.outline(self.screen, self.sel, self.theme.text, 2)
        # 전투 강조 (1초)
        dt = pygame.time.get_ticks() - self.flash_t
        if dt < 1200 and g.battle_regions:
            a = 1 - dt / 1200
            col = mix((255, 255, 255), (224, 49, 49), a)
            for rid in set(g.battle_regions):
                if rid in self.world.regions:
                    mv.outline(self.screen, rid, col, 3)
        self.draw_capitals()
        self.draw_occupations()
        self.draw_orders()
        self.draw_armies()
        self.gui.pop_clip()

    def dashed(self, p1, p2, color, dash=6):
        x1, y1 = p1
        x2, y2 = p2
        d = math.hypot(x2 - x1, y2 - y1)
        if d < 1:
            return
        n = int(d / dash)
        for i in range(0, n, 2):
            a, b = i / n, min(1, (i + 1) / n)
            pygame.draw.line(self.screen, color, (x1 + (x2 - x1) * a, y1 + (y2 - y1) * a),
                             (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b), 2)

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
            self.star((x, y - (14 if self.map.z >= 2 else 0)), 7 if self.map.z < 2 else 9,
                      mix(self.faction_rgb(f.id), (0, 0, 0), 0.2))

    def draw_occupations(self):
        g = self.game
        for r in g.regions.values():
            if not r.occ or not (g.is_visible(g.player_id, r.id) or self.fog_reveal):
                continue
            x, y = self.map.label_screen(r.id)
            col = self.faction_rgb(r.occ["by"])
            rect = pygame.Rect(0, 0, 30, 6)
            rect.center = (x, y + 14)
            self.gui.progress(rect, r.occ["progress"] / max(1, r.occ["need"]), col, (255, 255, 255))
            pygame.draw.rect(self.screen, col, rect, 1, border_radius=3)

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
                pygame.draw.lines(self.screen, (47, 111, 222), False, pts, 3)
                self.arrowhead(pts[-2], pts[-1], (47, 111, 222))
            elif o["type"] in ("attack", "land"):
                pts = [p0] + [mv.label_screen(n) for n in o.get("path", [])]
                if pts[-1] != mv.label_screen(o["target"]):
                    pts.append(mv.label_screen(o["target"]))
                col = (201, 42, 42) if o["type"] == "attack" else (12, 166, 120)
                pygame.draw.lines(self.screen, col, False, pts, 3)
                self.arrowhead(pts[-2], pts[-1], col)
            elif o["type"] == "bombard":
                self.dashed(p0, mv.label_screen(o["target"]), (230, 119, 0))
                self.arrowhead(p0, mv.label_screen(o["target"]), (230, 119, 0))

    def arrowhead(self, p1, p2, color):
        ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        pts = [p2, (p2[0] - 12 * math.cos(ang - 0.45), p2[1] - 12 * math.sin(ang - 0.45)),
               (p2[0] - 12 * math.cos(ang + 0.45), p2[1] - 12 * math.sin(ang + 0.45))]
        pygame.draw.polygon(self.screen, color, pts)

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
            w = 30 if mv.z < 2 else 38
            n = len(arms)
            start = x - (n * (w + 2)) / 2
            yy = y + (8 if mv.z >= 2 else 4)
            if mv.z >= 4 and not self.world.is_sea(loc):
                yy += 12
            for i, a in enumerate(arms):
                r = pygame.Rect(int(start + i * (w + 2)), int(yy), w, 16)
                col = (120, 120, 120) if a.owner == NEUTRAL else self.faction_rgb(a.owner)
                pygame.draw.rect(self.screen, col, r, border_radius=4)
                if a.id == self.sel_army:
                    pygame.draw.rect(self.screen, (255, 212, 59), r.inflate(4, 4), 2, border_radius=5)
                else:
                    pygame.draw.rect(self.screen, mix(col, (0, 0, 0), 0.35), r, 1, border_radius=4)
                icon_key = max(a.units, key=lambda k: a.units[k] * C.UNITS[k]["cost"])
                panels.unit_icon(self.screen, icon_key, (r.x + 8, r.centery), (255, 255, 255))
                t = render_text(str(a.count()), 11, (255, 255, 255), "bold")
                self.screen.blit(t, t.get_rect(midright=(r.right - 3, r.centery)))
                if a.order and a.owner == pid:
                    pygame.draw.circle(self.screen, (255, 212, 59), (r.right - 1, r.y + 1), 3)
        # 줌 4배 이상: 인구 배지
        if mv.z >= 4:
            for rid in self.world.order:
                x, y = mv.label_screen(rid)
                if not mv.view.collidepoint(x, y):
                    continue
                if not (g.is_explored(pid, rid) or self.fog_reveal):
                    continue
                t = render_text(f"{g.regions[rid].pop:.1f}만", 10, self.theme.muted, "semibold")
                self.screen.blit(t, t.get_rect(center=(x, y + 8)))

    # ------------------------------------------------------------ 지도 입력
    def map_input(self, pick_mode=False):
        gui = self.gui
        mv = self.map
        pos = gui.mouse
        over_ui = gui.over_ui(pos) or not mv.view.collidepoint(pos)
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
                    self.setup.start = node
                    mv.invalidate()
                return
            self.select(node)
        if gui.rclicked and not pick_mode:
            self.right_click(self.hover, pos)
        if not pick_mode and self.hover and self.sel_army:
            self.order_tooltip(self.hover)

    def select(self, node):
        g = self.game
        self.sel = node
        self.split = {}
        if node is None:
            self.sel_army = None
            return
        mine = [a for a in g.armies_at(node, g.player_id)]
        cur = g.armies.get(self.sel_army) if self.sel_army else None
        if not cur or cur.loc != node:
            self.sel_army = mine[0].id if mine else None
        self.left_open = True
        if mine and self.tab == "action" and g.regions.get(node) is None:
            self.tab = "army"

    def right_click(self, node, pos):
        g = self.game
        if not node:
            return
        army = g.armies.get(self.sel_army) if self.sel_army else None
        if army and army.owner == g.player_id:
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
                self.end_turn()
            elif k.key == pygame.K_ESCAPE:
                if self.sel_army:
                    self.sel_army = None
                else:
                    self.sel = None
                self.ctx_menu = None
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
                self.save()
            elif k.key == pygame.K_F9:
                self.load()
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
                "coal": f.res["coal"], "elec": f.res["elec"], "happy": round(self.game.avg_happiness(f.id))}

    def end_turn(self):
        g = self.game
        if g.game_over or self.active_modal():
            return
        before = self.snapshot()
        g.end_turn()
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
                                             "famine", "capital", "bomb", "victory", "diplo"):
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
        sw, _ = self.screen.get_size()
        gui.panel((0, 0, sw, TOP_H), radius=0, shadow=True, border=False)
        pygame.draw.line(self.screen, self.theme.border, (0, TOP_H - 1), (sw, TOP_H - 1))
        pygame.draw.rect(self.screen, self.faction_rgb(f.id), (16, 14, 8, 28), border_radius=3)
        from ..leaders import GOV_BY_KEY
        gov = GOV_BY_KEY.get(f.gov, {}).get("name", "체제 미정")
        gui.text((32, 8), f.name, 18, weight="bold")
        gui.text((32, 32), f"{f.leader_name} · {gov} · 수도 {self.world.regions[f.capital].short}", 12,
                 self.theme.muted)
        gui.text((sw // 2 - 90, TOP_H // 2), g.date_label(), 16, weight="bold", anchor="center")
        x = sw - 16
        snap = self.snapshot()
        highlight = pygame.time.get_ticks() - self.prev_t < 600
        last = f.last
        items = [
            ("happy", "행복도", f"{snap['happy']:+d}", None,
             f"평균 행복도 {g.avg_happiness(f.id):+.1f}\n세율 효과 {0.1*(10-f.tax*100):+.1f}/턴"),
            ("elec", "전기", f"{snap['elec']:.0f}", None, "전기: 발전소·자체 발전으로 생산, 공장 연료(φ 1.25)"),
            ("coal", "석탄", f"{snap['coal']:.0f}", None, "석탄: 탄광 생산, 공장 연료·발전·액화"),
            ("oil", "석유", f"{snap['oil']:.0f}", None, "석유: 정유 생산, 공장 연료·군 생산"),
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
            from .theme import font
            vw = max(font(15, "semibold").size(val)[0], font(11).size(label)[0]) + 22
            r = pygame.Rect(x - vw, 6, vw, TOP_H - 12)
            prev = self.prev_values.get(key)
            if highlight and prev is not None and self._differs(prev, snap[key]):
                pygame.draw.rect(self.screen, (255, 243, 191), r, border_radius=6)
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
        sw, sh = self.screen.get_size()
        w = 74
        r = pygame.Rect(12, sh - 60, len(MAP_MODES) * (w + 4) + 12, 48)
        gui.panel(r)
        for i, (key, label) in enumerate(MAP_MODES):
            if gui.button((r.x + 8 + i * (w + 4), r.y + 8, w, 32), label, selected=self.mode == key,
                          tooltip=f"지도 모드 ({i+1})"):
                self.mode = key
                self.changed()
        # 줌 표시
        gui.text((r.right + 12, r.centery), f"×{self.map.z:.1f}", 12, self.theme.muted, anchor="midleft")

    def draw_end_turn(self):
        gui = self.gui
        g = self.game
        sw, sh = self.screen.get_size()
        r = pygame.Rect(sw - 172, sh - 68, 160, 56)
        gui.block(r)
        if gui.button(r, "턴 종료", "primary", size=17, weight="bold", tooltip="Enter", radius=10,
                      enabled=not g.game_over):
            self.end_turn()
        idle = g.idle_slots(g.player_id)
        if idle:
            c = (r.right - 6, r.y + 6)
            pygame.draw.circle(self.screen, self.theme.warn, c, 13)
            gui.text(c, str(idle), 12, (255, 255, 255), "bold", anchor="center")
            if gui.hover(pygame.Rect(c[0] - 13, c[1] - 13, 26, 26)):
                gui.tooltip = f"미지정 슬롯 {idle}곳 (Tab으로 순회)"

    def draw_toasts(self):
        now = pygame.time.get_ticks()
        self.toasts = [t for t in self.toasts if now - t[2] < 6000]
        sw, _ = self.screen.get_size()
        x = sw // 2
        y = TOP_H + 12
        for text, col, t0 in self.toasts:
            alpha = 1.0 if now - t0 < 5000 else 1 - (now - t0 - 5000) / 1000
            surf = render_text(text, 13, (255, 255, 255), "semibold")
            r = surf.get_rect(midtop=(x, y)).inflate(28, 14)
            bg = pygame.Surface(r.size, pygame.SRCALPHA)
            base = (33, 37, 41) if col is None or col == self.theme.text else col
            pygame.draw.rect(bg, (*base, int(230 * alpha)), bg.get_rect(), border_radius=8)
            self.screen.blit(bg, r)
            surf.set_alpha(int(255 * alpha))
            self.screen.blit(surf, surf.get_rect(center=r.center))
            y += r.h + 6

    # ------------------------------------------------------------ 외교
    def open_diplomacy(self, fid):
        self.dip_state = modals.DiploDraft(fid)
        self.modal = ("diplomacy", fid)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="한반도 시군구 문명")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
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
