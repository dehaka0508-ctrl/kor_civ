"""간단한 즉시 모드(immediate-mode) GUI 도구.

모든 좌표·크기는 '논리 좌표'로 받는다. 그릴 때 UI 배율 u(theme.UI)를 곱해 실제 픽셀로
변환하므로 창을 키우면 글자·버튼이 흐려지지 않고 선명하게 커진다.
"""
from __future__ import annotations

import re

import pygame

from .theme import UI, measure, mix, paper_texture, render_text


class Gui:
    def __init__(self, screen, theme):
        self.screen = screen
        self.t = theme
        self.mouse = (0, 0)          # 논리 좌표
        self.mouse_phys = (0, 0)     # 실제 픽셀
        self.clicked = False
        self.rclicked = False
        self.dclicked = False
        self.down = False
        self.wheel = 0
        self.input_enabled = True
        self.tooltip = None
        self.ui_rects: list = []
        self.keys: list = []
        self.text_events: list = []
        self.focus = None
        self._inputs_drawn: set = set()   # 지난 프레임에 그린 입력칸
        self.released = False             # 이번 프레임에 왼쪽 버튼을 뗐는지(버튼이 소비해도 유지)
        self.drag_id = None
        self.scroll: dict = {}
        self._clip_stack: list = []
        self._last_click_time = 0
        self.time = 0

    # ------------------------------------------------------------ 좌표 변환
    @property
    def u(self) -> float:
        return UI["u"]

    def P(self, x, y):
        u = UI["u"]
        return int(round(x * u)), int(round(y * u))

    def R(self, rect) -> pygame.Rect:
        r = pygame.Rect(rect) if not isinstance(rect, pygame.Rect) else rect
        u = UI["u"]
        x0, y0 = int(round(r.x * u)), int(round(r.y * u))
        x1, y1 = int(round(r.right * u)), int(round(r.bottom * u))
        return pygame.Rect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))

    def W(self, width) -> int:
        return max(1, int(round(width * UI["u"])))

    def size(self):
        """화면 크기(논리 좌표)."""
        w, h = self.screen.get_size()
        u = UI["u"]
        return int(w / u), int(h / u)

    # ------------------------------------------------------------ 프레임
    def begin(self, events):
        self.clicked = self.rclicked = self.dclicked = False
        self.wheel = 0
        self.keys = []
        self.text_events = []
        self.tooltip = None
        self.ui_rects = []
        self.released_id = None
        self.released = False
        # 포커스된 입력칸이 더는 그려지지 않으면(화면 전환·창 닫힘) 포커스를 푼다.
        # 남아 있으면 Enter 등 모든 단축키가 입력칸으로 간 것으로 처리돼 무시된다.
        if self.focus is not None and self.focus not in self._inputs_drawn:
            self.blur()
        self._inputs_drawn = set()
        self.time = pygame.time.get_ticks()
        mx, my = pygame.mouse.get_pos()
        self.mouse_phys = (mx, my)
        u = UI["u"]
        self.mouse = (int(mx / u), int(my / u))
        for e in events:
            if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                self.clicked = True
                self.released = True
                self.down = False
                self.released_id = self.drag_id   # 방금 놓은 슬라이더는 이번 프레임에 값을 확정
                self.drag_id = None
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                self.down = True
                if self.time - self._last_click_time < 350:
                    self.dclicked = True
                self._last_click_time = self.time
            elif e.type == pygame.MOUSEBUTTONUP and e.button == 3:
                self.rclicked = True
            elif e.type == pygame.MOUSEWHEEL:
                self.wheel += e.y
            elif e.type == pygame.KEYDOWN:
                self.keys.append(e)
            elif e.type == pygame.TEXTINPUT:
                self.text_events.append(e.text)

    def block(self, rect):
        self.ui_rects.append(pygame.Rect(rect))

    def over_ui(self, pos=None) -> bool:
        pos = pos or self.mouse
        return any(r.collidepoint(pos) for r in self.ui_rects)

    def consume(self):
        self.clicked = False
        self.rclicked = False

    # ------------------------------------------------------------ 클립
    def push_clip(self, rect):
        rect = pygame.Rect(rect)
        if self._clip_stack:
            rect = rect.clip(self._clip_stack[-1])
        self._clip_stack.append(rect)
        self.screen.set_clip(self.R(rect))

    def pop_clip(self):
        self._clip_stack.pop()
        self.screen.set_clip(self.R(self._clip_stack[-1]) if self._clip_stack else None)

    def hover(self, rect) -> bool:
        if not self.input_enabled:
            return False
        r = pygame.Rect(rect)
        if self._clip_stack and not self._clip_stack[-1].collidepoint(self.mouse):
            return False
        return r.collidepoint(self.mouse)

    # ------------------------------------------------------------ 기본 도형 (논리 좌표)
    def rect(self, color, rect, width=0, radius=0):
        pygame.draw.rect(self.screen, color, self.R(rect), self.W(width) if width else 0,
                         border_radius=int(radius * self.u))

    def line(self, color, p1, p2, width=1):
        pygame.draw.line(self.screen, color, self.P(*p1), self.P(*p2), self.W(width))

    def lines(self, color, closed, pts, width=1):
        pygame.draw.lines(self.screen, color, closed, [self.P(*p) for p in pts], self.W(width))

    def circle(self, color, center, radius, width=0):
        pygame.draw.circle(self.screen, color, self.P(*center), max(1, int(round(radius * self.u))),
                           self.W(width) if width else 0)

    def polygon(self, color, pts, width=0):
        pygame.draw.polygon(self.screen, color, [self.P(*p) for p in pts], self.W(width) if width else 0)

    def icon(self, key, center, color, s=1.0):
        from .panels import unit_icon
        unit_icon(self.screen, key, self.P(*center), color, s * self.u)

    # ------------------------------------------------------------ 장식
    def paper(self, rect, radius=0):
        """한지 결을 곱하기로 덮는다(패널 바탕 위에)."""
        pr = self.R(rect).inflate(-2 * int(radius * self.u * 0.3), -2 * int(radius * self.u * 0.3))
        if pr.w <= 0 or pr.h <= 0 or self.t.dark:
            return
        tex = paper_texture()
        tw, th = tex.get_size()
        old = self.screen.get_clip()
        self.screen.set_clip(pr.clip(old) if old else pr)
        for y in range(pr.y, pr.bottom, th):
            for x in range(pr.x, pr.right, tw):
                self.screen.blit(tex, (x, y), special_flags=pygame.BLEND_RGB_MULT)
        self.screen.set_clip(old)

    def ornament(self, rect, color, size=10, width=2):
        """단청·창살풍 모서리 꺾쇠."""
        r = self.R(rect)
        k = self.u
        sz, s2 = size * k, size * k * 0.45
        w = max(1, int(width * k))
        for cx, cy, sx, sy in ((r.x, r.y, 1, 1), (r.right - 1, r.y, -1, 1), (r.x, r.bottom - 1, 1, -1),
                               (r.right - 1, r.bottom - 1, -1, -1)):
            pygame.draw.lines(self.screen, color, False, [(cx + sx * sz, cy), (cx, cy), (cx, cy + sy * sz)], w)
            pygame.draw.lines(self.screen, color, False, [(cx + sx * sz * 0.95, cy + sy * s2), (cx + sx * s2, cy + sy * s2),
                                                         (cx + sx * s2, cy + sy * sz * 0.95)], max(1, w // 2))

    _shadow_cache: dict = {}

    def shadow(self, rect, radius=6, spread=6, alpha=None):
        pr = self.R(rect)
        m = self.W(spread)
        a = self.t.shadow[3] if alpha is None else alpha
        key = (pr.w, pr.h, m, a, self.t.shadow[:3], int((radius + spread) * self.u))
        sh = Gui._shadow_cache.get(key)
        if sh is None:                        # 같은 크기의 그림자는 한 번만 만든다
            sh = pygame.Surface((pr.w + 2 * m, pr.h + 2 * m), pygame.SRCALPHA)
            for i in range(3):                # 겹친 사각형으로 번진 그림자
                pygame.draw.rect(sh, (*self.t.shadow[:3], a // 3), sh.get_rect().inflate(-m * (1 + i) // 2, -m * (1 + i) // 2),
                                 border_radius=key[5])
            if len(Gui._shadow_cache) > 300:
                Gui._shadow_cache.clear()
            Gui._shadow_cache[key] = sh
        self.screen.blit(sh, (pr.x - m, pr.y - m + self.W(spread * 0.4)))

    # ------------------------------------------------------------ 그리기
    def panel(self, rect, color=None, radius=6, shadow=True, border=True, block=True, ornament=False):
        """한지 패널: 바탕 + 결 + 금빛 테두리(ornament=True 면 안쪽 선과 모서리 꺾쇠)."""
        r = pygame.Rect(rect)
        pr = self.R(r)
        t = self.t
        radius = min(radius, 6)
        if shadow:
            self.shadow(r, radius)
        pygame.draw.rect(self.screen, color or t.panel, pr, border_radius=int(radius * self.u))
        if color is None or color == t.panel:
            self.paper(r, radius)
        if border:
            pygame.draw.rect(self.screen, mix(t.border, t.text, 0.15), pr, 1, border_radius=int(radius * self.u))
        if ornament:
            inner = r.inflate(-10, -10)
            pygame.draw.rect(self.screen, mix(t.border, t.panel, 0.3), self.R(inner), 1,
                             border_radius=int(max(0, radius - 3) * self.u))
            self.ornament(inner, mix(t.gold, t.text, 0.1), 11, 2)
        if block:
            self.block(r)
        return r

    def text(self, pos, s, size=14, color=None, weight="regular", anchor="topleft", max_w=None, tip=True):
        s = str(s)
        col = color or self.t.text
        u = self.u
        surf = render_text(s, size, col, weight)
        full = None
        if max_w and surf.get_width() > max_w * u:
            full = s
            while len(s) > 1 and render_text(s + "…", size, col, weight).get_width() > max_w * u:
                s = s[:-1]
            surf = render_text(s + "…", size, col, weight)
        lw, lh = surf.get_width() / u, surf.get_height() / u
        lr = pygame.Rect(0, 0, max(1, int(round(lw))), max(1, int(round(lh))))
        setattr(lr, anchor, (int(round(pos[0])), int(round(pos[1]))))
        if full is not None and tip and self.hover(lr):
            self.tooltip = full               # '…'로 잘린 글자는 마우스를 올리면 전체를 보여 준다
        # 실제 픽셀 위치: 논리 기준점을 변환한 뒤 같은 기준으로 맞춘다
        pr = surf.get_rect()
        setattr(pr, anchor, self.P(*pos))
        self.screen.blit(surf, pr)
        return lr

    def wrap(self, pos, s, width, size=13, color=None, weight="regular", line_h=None, words=False, center=False):
        """폭에 맞춰 줄바꿈. words=True 면 띄어쓰기 단위로 끊고(외국어 대사), 한 낱말이 폭보다 길 때만 글자 단위.
        center=True 면 줄마다 가운데 정렬. 다음 줄의 y 를 돌려준다."""
        x, y = pos
        line_h = line_h or int(size * 1.5 * 1.2)

        def put(line):
            if center:
                self.text((x + width / 2, y), line, size, color, weight, anchor="midtop")
            else:
                self.text((x, y), line, size, color, weight)

        for para in str(s).split("\n"):
            tokens = re.findall(r"\S+\s*", para) if words else list(para)
            line = ""
            for tok in tokens:
                if measure(line + tok.rstrip(), size, weight)[0] <= width or not line:
                    if words and measure(tok.rstrip(), size, weight)[0] > width:
                        for ch in tok:                   # 폭보다 긴 낱말(띄어쓰기 없는 한문 등)은 글자 단위
                            if measure(line + ch, size, weight)[0] > width and line:
                                put(line)
                                y += line_h
                                line = ch
                            else:
                                line += ch
                    else:
                        line += tok
                else:
                    put(line.rstrip())
                    y += line_h
                    line = tok
            put(line.rstrip())
            y += line_h
        return y

    def button(self, rect, label, kind="default", enabled=True, selected=False, size=13, tooltip=None,
               weight="semibold", radius=4, color=None):
        """kind: default(한지·금테) / primary(쪽빛) / danger(주홍) / seal(주홍 + 모서리 꺾쇠, 건국하기·턴 종료) /
        ghost(바탕 없음)."""
        r = pygame.Rect(rect)
        hov = enabled and self.hover(r)
        t = self.t
        radius = min(radius, 6)
        line = None
        if kind == "primary":
            bg, fg, line = (color or t.accent), (255, 255, 255), t.gold
        elif kind in ("danger", "seal"):
            bg, fg = (color or t.vermilion), (255, 248, 236)
        elif kind == "ghost":
            bg, fg = None, t.text
        else:
            bg, fg, line = t.panel, (t.accent if not t.dark else t.text), mix(t.border, t.text, 0.15)
        if selected:
            bg, fg, line = (color or t.accent), (255, 255, 255), t.gold
        if not enabled:
            bg = mix(bg or t.panel, t.panel, 0.55) if bg else None
            fg = mix(fg, t.panel, 0.55)
            line = mix(line, t.panel, 0.5) if line else None
        elif hov and bg:
            bg = mix(bg, (0, 0, 0) if not t.dark else (255, 255, 255), 0.08)
        if kind == "seal" and enabled:
            self.shadow(r, radius, 8)
        if bg:
            self.rect(bg, r, radius=radius)
        if kind == "ghost" and hov:
            self.rect(t.panel_alt, r, radius=radius)
        if line:
            pygame.draw.rect(self.screen, line, self.R(r), 1, border_radius=int(radius * self.u))
        if kind == "seal":
            inner = r.inflate(-8, -8)
            pygame.draw.rect(self.screen, mix(bg, (255, 230, 200), 0.5), self.R(inner), 1, border_radius=int(3 * self.u))
            self.ornament(inner, t.gold_lt, 9, 2)
        self.text(r.center, label, size, fg, weight, anchor="center", max_w=r.w - 6)
        if tooltip and self.hover(r):          # 비활성 버튼도 이유·미리보기를 보여 준다
            self.tooltip = tooltip
        if hov and self.clicked:
            self.clicked = False
            return True
        return False

    def checkbox(self, rect, label, value, enabled=True, size=13):
        r = pygame.Rect(rect)
        bs = 18
        box = pygame.Rect(r.x, r.centery - bs // 2, bs, bs)
        t = self.t
        self.rect(t.accent if value else t.panel, box, radius=3)
        pygame.draw.rect(self.screen, t.gold if value else t.muted, self.R(box), max(1, self.W(1)),
                         border_radius=int(3 * self.u))
        if value:
            self.lines((255, 255, 255), False,
                       [(box.x + 4, box.centery), (box.x + 8, box.bottom - 4), (box.right - 3, box.y + 4)], 2)
        self.text((box.right + 8, r.centery), label, size, t.text if enabled else t.muted, anchor="midleft",
                  max_w=r.w - bs - 10)
        if enabled and self.hover(r) and self.clicked:
            self.clicked = False
            return not value
        return value

    def segmented(self, rect, options, index, size=12, enabled=True):
        r = pygame.Rect(rect)
        n = len(options)
        w = r.w / n
        new = index
        t = self.t
        self.rect(t.panel, r, radius=4)
        for i, opt in enumerate(options):
            cell = pygame.Rect(int(r.x + i * w) + 2, r.y + 2, int(w) - 4, r.h - 4)
            if i == index:
                self.rect(t.accent, cell, radius=3)
            elif i and i != index + 1:
                self.line(t.border, (cell.x - 2, cell.y + 6), (cell.x - 2, cell.bottom - 6))
            col = (255, 255, 255) if i == index else (t.text if enabled else t.muted)
            self.text(cell.center, opt, size, col, "semibold", anchor="center", max_w=cell.w - 4)
            if enabled and self.hover(cell) and self.clicked:
                self.clicked = False
                new = i
        pygame.draw.rect(self.screen, mix(t.border, t.text, 0.15), self.R(r), 1, border_radius=int(4 * self.u))
        return new

    def slider(self, rect, value, lo, hi, step, sid, enabled=True, track=None):
        """(값, 확정 여부). 끄는 동안 값이 따라 움직이고, 놓는 순간 확정(True)된다.
        track: 왼쪽→오른쪽 색 목록을 주면 막대를 그 색 그라데이션으로 그린다(색조 스펙트럼 등)."""
        r = pygame.Rect(rect)
        t = self.t
        if not hasattr(self, "_slider_vals"):
            self._slider_vals = {}
        result, done = value, False
        if enabled and self.drag_id is None and self.down and self.hover(r.inflate(0, 14)) \
                and self.released_id is None:
            self.drag_id = sid
        if enabled and self.drag_id == sid:
            f = max(0.0, min(1.0, (self.mouse[0] - r.x) / r.w))
            result = round(round((lo + f * (hi - lo)) / step) * step, 6)
            self._slider_vals[sid] = result
        elif self.released_id == sid:
            result = self._slider_vals.pop(sid, value)
            done = True
        value = result
        frac = (value - lo) / (hi - lo) if hi > lo else 0
        if track:
            n = len(track)
            seg = r.w / n
            for i, c in enumerate(track):
                self.rect(c, (r.x + i * seg, r.centery - 6, seg + 1, 12))
            self.rect(t.border, (r.x, r.centery - 6, r.w, 12), 1, radius=2)
        else:
            self.rect(t.panel_alt, (r.x, r.centery - 3, r.w, 6), radius=3)
            self.rect(t.accent if enabled else t.muted, (r.x, r.centery - 3, max(1, int(r.w * frac)), 6), radius=3)
        knob = (int(r.x + r.w * frac), r.centery)
        self.circle(t.panel, knob, 10)
        self.circle(t.accent if enabled else t.muted, knob, 10, 3)
        return value, done

    def progress(self, rect, frac, color=None, bg=None):
        r = pygame.Rect(rect)
        self.rect(bg or self.t.panel_alt, r, radius=r.h // 2)
        if frac > 0:
            w = max(r.h, int(r.w * min(1.0, frac)))
            self.rect(color or self.t.accent, (r.x, r.y, w, r.h), radius=r.h // 2)

    def blur(self):
        """입력칸 포커스 해제. IME 입력도 꺼서 한글 입력기가 단축키를 가로채지 않게 한다."""
        self.focus = None
        try:
            pygame.key.stop_text_input()
        except pygame.error:
            pass

    def text_input(self, rect, tid, value, size=14, max_len=20):
        r = pygame.Rect(rect)
        t = self.t
        self._inputs_drawn.add(tid)
        if self.focus == tid and self.released and not r.collidepoint(self.mouse):
            self.blur()                   # 입력칸 밖을 클릭하면 포커스 해제
        focused = self.focus == tid
        self.rect(t.panel, r, radius=3)
        pygame.draw.rect(self.screen, t.accent if focused else mix(t.border, t.text, 0.15), self.R(r),
                         self.W(2 if focused else 1), border_radius=int(3 * self.u))
        if self.hover(r) and self.clicked:
            self.focus = tid
            self.clicked = False
            pygame.key.start_text_input()
        if focused:
            for s in self.text_events:
                if len(value) < max_len:
                    value += s
            for k in self.keys:
                if k.key == pygame.K_BACKSPACE:
                    value = value[:-1]
                elif k.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_TAB):
                    self.blur()
            self.keys = [k for k in self.keys if k.key not in (pygame.K_BACKSPACE, pygame.K_RETURN, pygame.K_KP_ENTER)]
        caret = "|" if focused and (self.time // 500) % 2 == 0 else ""
        self.text((r.x + 10, r.centery), value + caret, size, t.text, anchor="midleft", max_w=r.w - 16)
        return value

    def stepper(self, rect, value, lo, hi, step=1, big=None, fmt="{:,}", size=13):
        """[-] 값 [+] (Shift 클릭은 big 단위)."""
        r = pygame.Rect(rect)
        bw = min(r.h + 4, r.w // 3)
        mods = pygame.key.get_mods()
        s = big if (big and mods & pygame.KMOD_SHIFT) else step
        if self.button((r.x, r.y, bw, r.h), "−", size=size + 1):
            value = max(lo, value - s)
        if self.button((r.right - bw, r.y, bw, r.h), "+", size=size + 1):
            value = min(hi, value + s)
        self.text(r.center, fmt.format(value), size, self.t.text, "semibold", anchor="center",
                  max_w=r.w - 2 * bw - 4)
        return value

    # ------------------------------------------------------------ 스크롤
    def begin_scroll(self, sid, rect, content_h):
        r = pygame.Rect(rect)
        off = self.scroll.get(sid, 0)
        if self.hover(r) and self.wheel:
            off -= self.wheel * 60
            self.wheel = 0
        off = max(0, min(off, max(0, content_h - r.h)))
        self.scroll[sid] = off
        self.push_clip(r)
        return off

    def end_scroll(self, sid, rect, content_h):
        r = pygame.Rect(rect)
        self.pop_clip()
        if content_h > r.h:
            off = self.scroll.get(sid, 0)
            bar_h = max(30, r.h * r.h / content_h)
            y = r.y + (r.h - bar_h) * off / (content_h - r.h)
            self.rect(mix(self.t.border, self.t.panel, 0.4), (r.right - 6, r.y, 4, r.h), radius=2)
            self.rect(mix(self.t.gold, self.t.text, 0.2), (r.right - 6, y, 4, bar_h), radius=2)

    def draw_tooltip(self):
        if not self.tooltip:
            return
        lines = str(self.tooltip).split("\n")
        size = 13
        lh = measure("가", size)[1] + 4
        w = max(measure(l, size)[0] for l in lines) + 24
        h = len(lines) * lh + 14
        x, y = self.mouse[0] + 18, self.mouse[1] + 20
        sw, sh = self.size()
        if x + w > sw - 4:
            x = self.mouse[0] - w - 10
        if y + h > sh - 4:
            y = self.mouse[1] - h - 10
        t = self.t
        self.shadow((x, y, w, h), 4, 6)
        self.rect(t.panel, (x, y, w, h), radius=4)
        self.paper((x, y, w, h))
        pygame.draw.rect(self.screen, mix(t.gold, t.text, 0.2), self.R((x, y, w, h)), 1, border_radius=int(4 * self.u))
        self.rect(t.vermilion, (x, y, 3, h))
        for i, l in enumerate(lines):
            self.text((x + 12, y + 7 + i * lh), l, size, t.text)
