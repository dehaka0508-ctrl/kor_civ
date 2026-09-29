"""간단한 즉시 모드(immediate-mode) GUI 도구.

모든 좌표·크기는 '논리 좌표'로 받는다. 그릴 때 UI 배율 u(theme.UI)를 곱해 실제 픽셀로
변환하므로 창을 키우면 글자·버튼이 흐려지지 않고 선명하게 커진다.
"""
from __future__ import annotations

import pygame

from .theme import UI, measure, mix, render_text


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
        self.time = pygame.time.get_ticks()
        mx, my = pygame.mouse.get_pos()
        self.mouse_phys = (mx, my)
        u = UI["u"]
        self.mouse = (int(mx / u), int(my / u))
        for e in events:
            if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                self.clicked = True
                self.down = False
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

    # ------------------------------------------------------------ 그리기
    def panel(self, rect, color=None, radius=10, shadow=True, border=True, block=True):
        r = pygame.Rect(rect)
        pr = self.R(r)
        if shadow:
            m = self.W(4)
            sh = pygame.Surface((pr.w + 2 * m, pr.h + 2 * m), pygame.SRCALPHA)
            pygame.draw.rect(sh, self.t.shadow, sh.get_rect().inflate(-m, -m).move(0, m // 2),
                             border_radius=int((radius + 2) * self.u))
            self.screen.blit(sh, (pr.x - m, pr.y - m + m // 4))
        pygame.draw.rect(self.screen, color or self.t.panel, pr, border_radius=int(radius * self.u))
        if border:
            pygame.draw.rect(self.screen, self.t.border, pr, 1, border_radius=int(radius * self.u))
        if block:
            self.block(r)
        return r

    def text(self, pos, s, size=14, color=None, weight="regular", anchor="topleft", max_w=None):
        s = str(s)
        col = color or self.t.text
        u = self.u
        surf = render_text(s, size, col, weight)
        if max_w and surf.get_width() > max_w * u:
            while len(s) > 1 and render_text(s + "…", size, col, weight).get_width() > max_w * u:
                s = s[:-1]
            surf = render_text(s + "…", size, col, weight)
        lw, lh = surf.get_width() / u, surf.get_height() / u
        lr = pygame.Rect(0, 0, max(1, int(round(lw))), max(1, int(round(lh))))
        setattr(lr, anchor, (int(round(pos[0])), int(round(pos[1]))))
        # 실제 픽셀 위치: 논리 기준점을 변환한 뒤 같은 기준으로 맞춘다
        pr = surf.get_rect()
        setattr(pr, anchor, self.P(*pos))
        self.screen.blit(surf, pr)
        return lr

    def wrap(self, pos, s, width, size=13, color=None, weight="regular", line_h=None):
        x, y = pos
        line_h = line_h or int(size * 1.5 * 1.2)
        for para in str(s).split("\n"):
            line = ""
            for ch in para:
                if measure(line + ch, size, weight)[0] > width and line:
                    self.text((x, y), line, size, color, weight)
                    y += line_h
                    line = ch
                else:
                    line += ch
            self.text((x, y), line, size, color, weight)
            y += line_h
        return y

    def button(self, rect, label, kind="default", enabled=True, selected=False, size=13, tooltip=None,
               weight="semibold", radius=8, color=None):
        r = pygame.Rect(rect)
        hov = enabled and self.hover(r)
        t = self.t
        if kind == "primary":
            bg, fg = (color or t.accent), (255, 255, 255)
        elif kind == "danger":
            bg, fg = t.bad, (255, 255, 255)
        elif kind == "ghost":
            bg, fg = None, t.text
        else:
            bg, fg = t.panel_alt, t.text
        if selected:
            bg, fg = (color or t.accent), (255, 255, 255)
        if not enabled:
            bg = mix(bg or t.panel, t.panel, 0.55) if bg else None
            fg = mix(fg, t.panel, 0.55)
        elif hov and bg:
            bg = mix(bg, (0, 0, 0) if not t.dark else (255, 255, 255), 0.08)
        if bg:
            self.rect(bg, r, radius=radius)
        if kind == "ghost" and hov:
            self.rect(t.panel_alt, r, radius=radius)
        if kind == "default" and not selected:
            pygame.draw.rect(self.screen, t.border, self.R(r), 1, border_radius=int(radius * self.u))
        self.text(r.center, label, size, fg, weight, anchor="center", max_w=r.w - 6)
        if hov and tooltip:
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
        self.rect(t.accent if value else t.panel, box, radius=4)
        pygame.draw.rect(self.screen, t.accent if value else t.muted, self.R(box), max(1, self.W(1)),
                         border_radius=int(4 * self.u))
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
        self.rect(self.t.panel_alt, r, radius=8)
        for i, opt in enumerate(options):
            cell = pygame.Rect(int(r.x + i * w) + 2, r.y + 2, int(w) - 4, r.h - 4)
            if i == index:
                self.rect(self.t.accent, cell, radius=6)
            col = (255, 255, 255) if i == index else (self.t.text if enabled else self.t.muted)
            self.text(cell.center, opt, size, col, "semibold", anchor="center", max_w=cell.w - 4)
            if enabled and self.hover(cell) and self.clicked:
                self.clicked = False
                new = i
        return new

    def slider(self, rect, value, lo, hi, step, sid, enabled=True):
        r = pygame.Rect(rect)
        t = self.t
        frac = (value - lo) / (hi - lo) if hi > lo else 0
        self.rect(t.panel_alt, (r.x, r.centery - 3, r.w, 6), radius=3)
        self.rect(t.accent if enabled else t.muted, (r.x, r.centery - 3, max(1, int(r.w * frac)), 6), radius=3)
        knob = (int(r.x + r.w * frac), r.centery)
        self.circle(t.panel, knob, 10)
        self.circle(t.accent if enabled else t.muted, knob, 10, 2)
        if enabled and self.hover(r.inflate(0, 14)) and self.down and self.drag_id is None:
            self.drag_id = sid
        if self.drag_id == sid and enabled:
            f = max(0.0, min(1.0, (self.mouse[0] - r.x) / r.w))
            v = lo + f * (hi - lo)
            v = round(round(v / step) * step, 6)
            return v, not self.down
        return value, False

    def progress(self, rect, frac, color=None, bg=None):
        r = pygame.Rect(rect)
        self.rect(bg or self.t.panel_alt, r, radius=r.h // 2)
        if frac > 0:
            w = max(r.h, int(r.w * min(1.0, frac)))
            self.rect(color or self.t.accent, (r.x, r.y, w, r.h), radius=r.h // 2)

    def text_input(self, rect, tid, value, size=14, max_len=20):
        r = pygame.Rect(rect)
        t = self.t
        focused = self.focus == tid
        self.rect(t.panel, r, radius=6)
        pygame.draw.rect(self.screen, t.accent if focused else t.border, self.R(r), self.W(2 if focused else 1),
                         border_radius=int(6 * self.u))
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
                elif k.key in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_TAB):
                    self.focus = None
            self.keys = [k for k in self.keys if k.key not in (pygame.K_BACKSPACE, pygame.K_RETURN)]
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
            self.rect(self.t.border, (r.right - 6, y, 5, bar_h), radius=2)

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
        self.rect((33, 37, 41), (x, y, w, h), radius=6)
        for i, l in enumerate(lines):
            self.text((x + 12, y + 7 + i * lh), l, size, (240, 242, 245))
