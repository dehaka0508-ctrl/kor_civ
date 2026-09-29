"""간단한 즉시 모드(immediate-mode) GUI 도구."""
from __future__ import annotations

import pygame

from .theme import mix, render_text


class Gui:
    def __init__(self, screen, theme):
        self.screen = screen
        self.t = theme
        self.mouse = (0, 0)
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
        sc = getattr(self, "mouse_scale", 1.0) or 1.0
        self.mouse = (int(mx / sc), int(my / sc))
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
        self.screen.set_clip(rect)

    def pop_clip(self):
        self._clip_stack.pop()
        self.screen.set_clip(self._clip_stack[-1] if self._clip_stack else None)

    def hover(self, rect) -> bool:
        if not self.input_enabled:
            return False
        r = pygame.Rect(rect)
        if self._clip_stack and not self._clip_stack[-1].collidepoint(self.mouse):
            return False
        return r.collidepoint(self.mouse)

    # ------------------------------------------------------------ 그리기
    def panel(self, rect, color=None, radius=10, shadow=True, border=True, block=True):
        r = pygame.Rect(rect)
        if shadow:
            sh = pygame.Surface((r.w + 8, r.h + 8), pygame.SRCALPHA)
            pygame.draw.rect(sh, self.t.shadow, sh.get_rect().inflate(-4, -4).move(0, 2), border_radius=radius + 2)
            self.screen.blit(sh, (r.x - 4, r.y - 3))
        pygame.draw.rect(self.screen, color or self.t.panel, r, border_radius=radius)
        if border:
            pygame.draw.rect(self.screen, self.t.border, r, 1, border_radius=radius)
        if block:
            self.block(r)
        return r

    def text(self, pos, s, size=14, color=None, weight="regular", anchor="topleft", max_w=None):
        s = str(s)
        surf = render_text(s, size, color or self.t.text, weight)
        if max_w and surf.get_width() > max_w:
            while len(s) > 1 and render_text(s + "…", size, color or self.t.text, weight).get_width() > max_w:
                s = s[:-1]
            surf = render_text(s + "…", size, color or self.t.text, weight)
        r = surf.get_rect(**{anchor: pos})
        self.screen.blit(surf, r)
        return r

    def wrap(self, pos, s, width, size=13, color=None, weight="regular", line_h=None):
        from .theme import font
        f = font(size, weight)
        x, y = pos
        line_h = line_h or int(size * 1.5)
        for para in str(s).split("\n"):
            line = ""
            for ch in para:
                if f.size(line + ch)[0] > width and line:
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
            pygame.draw.rect(self.screen, bg, r, border_radius=radius)
        if kind == "ghost" and hov:
            pygame.draw.rect(self.screen, t.panel_alt, r, border_radius=radius)
        if kind == "default" and not selected:
            pygame.draw.rect(self.screen, t.border, r, 1, border_radius=radius)
        self.text(r.center, label, size, fg, weight, anchor="center", max_w=r.w - 8)
        if hov and tooltip:
            self.tooltip = tooltip
        if hov and self.clicked:
            self.clicked = False
            return True
        return False

    def checkbox(self, rect, label, value, enabled=True, size=13):
        r = pygame.Rect(rect)
        box = pygame.Rect(r.x, r.centery - 8, 16, 16)
        t = self.t
        pygame.draw.rect(self.screen, t.accent if value else t.panel, box, border_radius=4)
        pygame.draw.rect(self.screen, t.accent if value else t.muted, box, 1, border_radius=4)
        if value:
            pygame.draw.lines(self.screen, (255, 255, 255), False,
                              [(box.x + 3, box.centery), (box.x + 7, box.bottom - 4), (box.right - 3, box.y + 4)], 2)
        self.text((box.right + 8, r.centery), label, size, t.text if enabled else t.muted, anchor="midleft")
        if enabled and self.hover(r) and self.clicked:
            self.clicked = False
            return not value
        return value

    def segmented(self, rect, options, index, size=12, enabled=True):
        r = pygame.Rect(rect)
        n = len(options)
        w = r.w / n
        new = index
        pygame.draw.rect(self.screen, self.t.panel_alt, r, border_radius=8)
        for i, opt in enumerate(options):
            cell = pygame.Rect(int(r.x + i * w) + 2, r.y + 2, int(w) - 4, r.h - 4)
            if i == index:
                pygame.draw.rect(self.screen, self.t.accent, cell, border_radius=6)
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
        pygame.draw.rect(self.screen, t.panel_alt, (r.x, r.centery - 3, r.w, 6), border_radius=3)
        pygame.draw.rect(self.screen, t.accent if enabled else t.muted,
                         (r.x, r.centery - 3, int(r.w * frac), 6), border_radius=3)
        knob = (int(r.x + r.w * frac), r.centery)
        pygame.draw.circle(self.screen, t.panel, knob, 9)
        pygame.draw.circle(self.screen, t.accent if enabled else t.muted, knob, 9, 2)
        if enabled and self.hover(r.inflate(0, 10)) and self.down and self.drag_id is None:
            self.drag_id = sid
        if self.drag_id == sid and enabled:
            f = max(0.0, min(1.0, (self.mouse[0] - r.x) / r.w))
            v = lo + f * (hi - lo)
            v = round(round(v / step) * step, 6)
            return v, not self.down
        return value, False

    def progress(self, rect, frac, color=None, bg=None):
        r = pygame.Rect(rect)
        pygame.draw.rect(self.screen, bg or self.t.panel_alt, r, border_radius=r.h // 2)
        if frac > 0:
            w = max(r.h, int(r.w * min(1.0, frac)))
            pygame.draw.rect(self.screen, color or self.t.accent, (r.x, r.y, w, r.h), border_radius=r.h // 2)

    def text_input(self, rect, tid, value, size=14, max_len=20):
        r = pygame.Rect(rect)
        t = self.t
        focused = self.focus == tid
        pygame.draw.rect(self.screen, t.panel, r, border_radius=6)
        pygame.draw.rect(self.screen, t.accent if focused else t.border, r, 2 if focused else 1, border_radius=6)
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
        self.text((r.x + 8, r.centery), value + caret, size, t.text, anchor="midleft", max_w=r.w - 12)
        return value

    def stepper(self, rect, value, lo, hi, step=1, big=None, fmt="{:,}", size=13):
        """[-] 값 [+] (Shift 클릭은 big 단위)."""
        r = pygame.Rect(rect)
        bw = 26
        mods = pygame.key.get_mods()
        s = big if (big and mods & pygame.KMOD_SHIFT) else step
        if self.button((r.x, r.y, bw, r.h), "−", size=14):
            value = max(lo, value - s)
        if self.button((r.right - bw, r.y, bw, r.h), "+", size=14):
            value = min(hi, value + s)
        self.text(r.center, fmt.format(value), size, self.t.text, "semibold", anchor="center")
        return value

    # ------------------------------------------------------------ 스크롤
    def begin_scroll(self, sid, rect, content_h):
        r = pygame.Rect(rect)
        off = self.scroll.get(sid, 0)
        if self.hover(r) and self.wheel:
            off -= self.wheel * 40
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
            bar_h = max(24, r.h * r.h / content_h)
            y = r.y + (r.h - bar_h) * off / (content_h - r.h)
            pygame.draw.rect(self.screen, self.t.border, (r.right - 4, y, 3, bar_h), border_radius=2)

    def draw_tooltip(self):
        if not self.tooltip:
            return
        from .theme import font
        lines = str(self.tooltip).split("\n")
        f = font(13)
        w = max(f.size(l)[0] for l in lines) + 20
        h = len(lines) * 19 + 12
        x, y = self.mouse[0] + 16, self.mouse[1] + 18
        sw, sh = self.screen.get_size()
        if x + w > sw - 4:
            x = self.mouse[0] - w - 10
        if y + h > sh - 4:
            y = self.mouse[1] - h - 10
        r = pygame.Rect(x, y, w, h)
        pygame.draw.rect(self.screen, (33, 37, 41), r, border_radius=6)
        for i, l in enumerate(lines):
            self.text((x + 10, y + 6 + i * 19), l, 13, (240, 242, 245))
