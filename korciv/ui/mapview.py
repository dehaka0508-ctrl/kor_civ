"""지도 렌더링·좌표 변환·선택."""
from __future__ import annotations

import math

import numpy as np
import pygame

from ..data import SEA_LABELS, SEA_POLYS
from .theme import mix, render_text, ui_scale

COS = math.cos(math.radians(38.0))
LON0, LAT1 = 124.0, 43.1
BASE_W, BASE_H = 560.0, 1000.0


def proj(lon, lat):
    return (lon - LON0) * COS * 100.0, (LAT1 - lat) * 100.0


def proj_arr(ring):
    a = np.asarray(ring, dtype=np.float64)
    out = np.empty_like(a)
    out[:, 0] = (a[:, 0] - LON0) * COS * 100.0
    out[:, 1] = (LAT1 - a[:, 1]) * 100.0
    return out


def pip(x, y, poly):
    xs, ys = poly[:, 0], poly[:, 1]
    xj, yj = np.roll(xs, 1), np.roll(ys, 1)
    cond = ((ys > y) != (yj > y)) & (x < (xj - xs) * (y - ys) / (yj - ys + 1e-12) + xs)
    return bool(np.count_nonzero(cond) % 2)


TERRAIN_COLORS = {"도하": (77, 171, 247), "돌파": (148, 216, 45)}   # 하늘색 / 연두색


def dashed(surf, p1, p2, color, width=2, dash=6):
    x1, y1 = p1
    x2, y2 = p2
    d = math.hypot(x2 - x1, y2 - y1)
    n = max(2, int(d / dash))
    for i in range(0, n, 2):
        a, b = i / n, min(1, (i + 1) / n)
        pygame.draw.line(surf, color, (x1 + (x2 - x1) * a, y1 + (y2 - y1) * a),
                         (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b), width)


class MapView:
    MIN_Z, MAX_Z = 0.8, 40.0

    def __init__(self, world):
        self.world = world
        self.polys = []          # (rid, arr, bbox)
        self.rbbox = {}
        self.label = {}
        self.area = {}
        for rid, geo in world.geometry.items():
            self.area[rid] = geo["area"]
            bx0 = by0 = 1e9
            bx1 = by1 = -1e9
            for ring in geo["polys"]:
                arr = proj_arr(ring)
                x0, y0 = arr.min(axis=0)
                x1, y1 = arr.max(axis=0)
                self.polys.append((rid, arr, (x0, y0, x1, y1)))
                bx0, by0, bx1, by1 = min(bx0, x0), min(by0, y0), max(bx1, x1), max(by1, y1)
            self.rbbox[rid] = (bx0, by0, bx1, by1)
            self.label[rid] = proj(*geo["label"])
        self.polys.sort(key=lambda p: -self.area[p[0]])
        self.sea_polys = {sid: proj_arr(p) for sid, p in SEA_POLYS.items()}
        self.label.update({sid: proj(*p) for sid, p in SEA_LABELS.items()})
        self.province_lines = [proj_arr(r) for rings in world.province_outlines.values() for r in rings]
        self.do8_lines = [proj_arr(r) for rings in world.do8_outlines.values() for r in rings]
        # 지형 경계: (종류, [선...], 연결선 여부)
        self.terrain_lines = [("도하" if t["kind"] == "도하" else "돌파", [proj_arr(l) for l in t["lines"]],
                               t["connector"]) for t in world.terrain_lines]
        self.view = pygame.Rect(0, 0, 800, 800)
        self.z = 1.0
        self.cx, self.cy = 280.0, 520.0
        self.cache = None
        self.cache_key = None
        self.version = 0

    # ------------------------------------------------------------ 좌표
    @property
    def fit(self):
        return min(self.view.w / BASE_W, self.view.h / BASE_H) * 0.96

    @property
    def scale(self):
        return self.fit * self.z

    def offset(self):
        s = self.scale
        return self.view.centerx - self.cx * s, self.view.centery - self.cy * s

    def to_screen(self, bx, by):
        s = self.scale
        ox, oy = self.offset()
        return bx * s + ox, by * s + oy

    def to_base(self, sx, sy):
        s = self.scale
        ox, oy = self.offset()
        return (sx - ox) / s, (sy - oy) / s

    def set_view(self, rect):
        rect = pygame.Rect(rect)
        if rect != self.view:
            self.view = rect
            self.invalidate()

    def invalidate(self):
        self.version += 1

    def zoom_at(self, pos, factor):
        bx, by = self.to_base(*pos)
        nz = max(self.MIN_Z, min(self.MAX_Z, self.z * factor))
        if nz == self.z:
            return
        self.z = nz
        # 커서 아래 지점을 고정
        s = self.scale
        self.cx = bx - (pos[0] - self.view.centerx) / s
        self.cy = by - (pos[1] - self.view.centery) / s
        self._clamp()
        self.invalidate()

    def pan(self, dx, dy):
        s = self.scale
        self.cx -= dx / s
        self.cy -= dy / s
        self._clamp()
        self.invalidate()

    def center_on(self, node, zoom=None):
        if node in self.label:
            self.cx, self.cy = self.label[node]
            if zoom:
                self.z = max(self.z, zoom)
            self._clamp()
            self.invalidate()

    def _clamp(self):
        self.cx = max(-50, min(BASE_W + 80, self.cx))
        self.cy = max(-20, min(BASE_H + 20, self.cy))

    def label_screen(self, node):
        return self.to_screen(*self.label[node])

    # ------------------------------------------------------------ 선택
    def pick(self, pos):
        if not self.view.collidepoint(pos):
            return None
        bx, by = self.to_base(*pos)
        best, best_area = None, 1e18
        for rid, arr, (x0, y0, x1, y1) in self.polys:
            if x0 <= bx <= x1 and y0 <= by <= y1 and self.area[rid] < best_area and pip(bx, by, arr):
                best, best_area = rid, self.area[rid]
        if best:
            return best
        for sid, arr in self.sea_polys.items():
            if pip(bx, by, arr):
                return sid
        return None

    # ------------------------------------------------------------ 렌더
    def _screen_poly(self, arr):
        s = self.scale
        ox, oy = self.offset()
        return (arr * s + (ox, oy)).tolist()

    def _visible_bbox(self, bbox):
        s = self.scale
        ox, oy = self.offset()
        x0, y0, x1, y1 = bbox
        return not (x1 * s + ox < self.view.x or x0 * s + ox > self.view.right
                    or y1 * s + oy < self.view.y or y0 * s + oy > self.view.bottom)

    def render_base(self, key, theme, colors, sea_colors, mode, labels, show_terrain=True):
        """colors: rid -> (fill, outline). 캐시가 유효하면 그대로 쓴다."""
        full_key = (key, self.version, self.view.size, theme.dark)
        if self.cache is not None and self.cache_key == full_key:
            return self.cache
        surf = pygame.Surface(self.view.size)
        surf.fill(theme.paper)
        s = self.scale
        ox, oy = self.offset()
        ox -= self.view.x
        oy -= self.view.y

        def sp(arr):
            return (arr * s + (ox, oy)).tolist()

        for sid, arr in self.sea_polys.items():
            pygame.draw.polygon(surf, sea_colors.get(sid, theme.sea), sp(arr))
        for sid, arr in self.sea_polys.items():
            pygame.draw.lines(surf, theme.sea_line, True, sp(arr), 1)
        view = pygame.Rect(0, 0, *self.view.size)
        thin = s < 1.2
        for rid, arr, bbox in self.polys:
            x0, y0, x1, y1 = bbox
            if x1 * s + ox < 0 or x0 * s + ox > view.w or y1 * s + oy < 0 or y0 * s + oy > view.h:
                continue
            fill, line = colors[rid]
            if (x1 - x0) * s < 1.5 and (y1 - y0) * s < 1.5:
                surf.set_at((int(x0 * s + ox), int(y0 * s + oy)), fill)
                continue
            pts = sp(arr)
            pygame.draw.polygon(surf, fill, pts)
            if not thin:
                pygame.draw.lines(surf, line, True, pts, 1)
            else:
                pygame.draw.aalines(surf, line, True, pts)
        pw = max(1, int((2 if self.z >= 2.5 else 1) * ui_scale()))
        for arr in self.province_lines:
            pygame.draw.lines(surf, theme.province_line, True, sp(arr), pw)
        if mode == "do8":
            for arr in self.do8_lines:
                pygame.draw.lines(surf, theme.do8_line, True, sp(arr), 2)
        if show_terrain:
            tw = max(2, int((3 if self.z < 2 else (4 if self.z < 4 else 5)) * ui_scale()))
            for kind, lines, connector in self.terrain_lines:
                col = TERRAIN_COLORS[kind]
                for arr in lines:
                    pts = sp(arr)
                    if len(pts) < 2:
                        continue
                    if connector:
                        dashed(surf, pts[0], pts[-1], col, tw)
                    else:
                        pygame.draw.lines(surf, (255, 255, 255), False, pts, tw + 2)
                        pygame.draw.lines(surf, col, False, pts, tw)
        # 해역 이름
        for sid in self.sea_polys:
            x, y = self.label[sid]
            t = render_text(labels.get(sid, ""), 15 if self.z < 2 else 18, mix(theme.sea_line, theme.text, 0.35), "bold")
            surf.blit(t, t.get_rect(center=(x * s + ox, y * s + oy)))
        # 구역 이름
        if self.z >= 2.0:
            placed = []
            size = 11 if self.z < 3 else (12 if self.z < 5 else (13 if self.z < 10 else 15))
            color = theme.text if not theme.dark else (230, 232, 235)
            order = sorted(self.rbbox, key=lambda r: -self.area[r])
            skipped = []
            for rid in order:
                x, y = self.label[rid]
                px, py = x * s + ox, y * s + oy
                if not view.collidepoint(px, py):
                    continue
                name = labels.get(rid)
                if not name:
                    continue
                t = render_text(name, size, color, "semibold")
                r = t.get_rect(center=(px, py - (6 if self.z >= 4 else 0)))
                if any(r.colliderect(p) for p in placed):
                    skipped.append((rid, name, px, py))
                    continue
                placed.append(r.inflate(4, 2))
                surf.blit(t, r)
            # 겹쳐서 빠진 이름: 작은 글씨로 다시, 구역이 글자보다 넓거나 충분히 확대했으면 겹쳐도 표시
            for rid, name, px, py in skipped:
                t = render_text(name, max(10, size - 2), color, "semibold")
                r = t.get_rect(center=(px, py))
                if self.z >= 10 or not any(r.colliderect(p) for p in placed):
                    placed.append(r.inflate(2, 0))
                    surf.blit(t, r)
        self.cache = surf
        self.cache_key = full_key
        return surf

    def outline(self, screen, rid, color, width=2):
        for r, arr, bbox in self.polys:
            if r == rid and self._visible_bbox(bbox):
                pygame.draw.lines(screen, color, True, self._screen_poly(arr), width)

    def fill_overlay(self, overlay, rid, rgba):
        ox, oy = self.view.x, self.view.y
        for r, arr, bbox in self.polys:
            if r == rid and self._visible_bbox(bbox):
                pts = [(x - ox, y - oy) for x, y in self._screen_poly(arr)]
                pygame.draw.polygon(overlay, rgba, pts)

    def sea_outline(self, screen, sid, color, width=3):
        pygame.draw.lines(screen, color, True, self._screen_poly(self.sea_polys[sid]), width)
