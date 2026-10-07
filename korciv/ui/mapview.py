"""지도 렌더링·좌표 변환·선택."""
from __future__ import annotations

import math

import numpy as np
import pygame

from ..data import SEA_LABELS
from .theme import mix, render_text, ui_scale

COS = math.cos(math.radians(38.0))
LON0, LAT1 = 124.0, 43.1
BASE_W, BASE_H = 560.0, 1000.0
# 독도: 서도·동도 (경도, 위도, 반지름°). 지역이 아닌 지도 표시용
DOKDO = ((131.8648, 37.2422, 0.0012), (131.8697, 37.2408, 0.0010))
DOKDO_LABEL = (131.8697, 37.2415)
DOKDO_NEAR = "S209"      # 울릉군


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
INTERACT_IDLE_MS = 150    # 드래그·휠이 이만큼 멈추면 지도를 정식으로 다시 그린다
CACHE_MARGIN = 0.15       # 지도 캐시를 화면보다 상하좌우로 15%씩 넓게 그려, 작은 이동·휠 한 칸 축소는 다시 그리지 않는다
LABEL_CELL = 64           # 지명 겹침 검사용 격자 크기(px)


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
        # 해역: sid -> [(바깥 테두리, [섬 구멍...])] — 해안선에 맞춰 잘린 모양
        self.sea_polys = {sid: [(proj_arr(p["ext"]), [proj_arr(h) for h in p["holes"]]) for p in parts]
                          for sid, parts in world.sea_shapes.items()}
        self.label.update({sid: proj(*p) for sid, p in SEA_LABELS.items()})
        self.world_outlines_open = getattr(world, "outlines_open", False)
        self.province_lines = [proj_arr(r) for rings in world.province_outlines.values() for r in rings]
        self.do8_lines = [proj_arr(r) for rings in world.do8_outlines.values() for r in rings]
        # 지형 경계: (종류, [선...], 연결선 여부)
        self.terrain_lines = [("도하" if t["kind"] == "도하" else "돌파", [proj_arr(l) for l in t["lines"]],
                               t["connector"]) for t in world.terrain_lines]
        # 좌표 변환을 한 번에: 모든 꼭짓점을 한 배열에 모아 두고 다각형·선은 구간만 기억한다
        bufs, n = [], 0

        def put(arr):
            nonlocal n
            bufs.append(arr)
            n += len(arr)
            return (n - len(arr), n)
        self.poly_span = [put(arr) for _, arr, _ in self.polys]
        self.sea_span = {sid: [put(ext) for ext, _ in parts] for sid, parts in self.sea_polys.items()}
        self.province_span = [put(a) for a in self.province_lines]
        self.do8_span = [put(a) for a in self.do8_lines]
        self.terrain_span = [(kind, [put(a) for a in lines], conn) for kind, lines, conn in self.terrain_lines]
        self.verts = np.concatenate(bufs) if bufs else np.zeros((0, 2))
        self.polys_by_rid = {}
        for i, (rid, arr, bbox) in enumerate(self.polys):
            self.polys_by_rid.setdefault(rid, []).append((arr, bbox))
        self.view = pygame.Rect(0, 0, 800, 800)
        self.z = 1.0
        self.cx, self.cy = 280.0, 520.0
        self.cache = None
        self.cache_meta = None
        self.version = 0              # 내용(색·지명·경계) 버전. 시점 이동은 버전을 올리지 않는다
        self.last_interact = -10 ** 9

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
        """지도 내용이 바뀌었다(색·소유·모드 등): 다음 프레임에 다시 그린다."""
        self.version += 1

    def _touch(self):
        self.last_interact = pygame.time.get_ticks()

    def interacting(self) -> bool:
        return pygame.time.get_ticks() - self.last_interact < INTERACT_IDLE_MS

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
        self._touch()                 # 다시 그리지 않고 캐시를 늘려 보여 준다(멈추면 다시 그림)

    def pan(self, dx, dy):
        s = self.scale
        self.cx -= dx / s
        self.cy -= dy / s
        self._clamp()
        self._touch()                 # 다시 그리지 않고 캐시를 밀어 보여 준다(멈추면 다시 그림)

    def center_on(self, node, zoom=None):
        if node in self.label:
            self.cx, self.cy = self.label[node]
            if zoom:
                self.z = max(self.z, zoom)
            self._clamp()             # 조작 중이 아니므로 다음 프레임에 새 시점으로 다시 그린다

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
        for sid, parts in self.sea_polys.items():
            for ext, holes in parts:
                if pip(bx, by, ext) and not any(pip(bx, by, h) for h in holes):
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

    def draw_base(self, screen, key, theme, colors_fn, sea_colors_fn, mode, labels_fn, show_terrain=True):
        """바탕 지도(지역 색·경계·지명)를 화면에 그린다.
        - 내용이 바뀌면(key·version) 지금 시점으로 다시 그린다.
        - 드래그·휠 조작 중에는 다시 그리지 않고 마지막 캐시를 밀거나 늘려 보여 준다.
          조작이 INTERACT_IDLE_MS 동안 멈추거나 캐시가 화면을 다 덮지 못하면 다시 그린다.
        colors_fn 등은 다시 그릴 때만 부른다(매 프레임 색 계산을 하지 않는다)."""
        full_key = (key, self.version, self.view.size, theme.dark)
        meta = self.cache_meta
        need = self.cache is None or meta["key"] != full_key
        if not need and (meta["s"], meta["cx"], meta["cy"]) != (self.scale, self.cx, self.cy):
            need = not self.interacting() or not self._cache_covers()
        if need:
            self._render(full_key, theme, colors_fn(), sea_colors_fn(), mode, labels_fn(), show_terrain)
        self._blit_cache(screen, theme)

    def _cache_place(self):
        """캐시 왼쪽 위가 지금 화면에서 놓일 위치와 배율 k."""
        m = self.cache_meta
        k = self.scale / m["s"]
        ox, oy = self.offset()
        return ox - k * m["ox"], oy - k * m["oy"], k

    def _cache_covers(self) -> bool:
        dx, dy, k = self._cache_place()
        w, h = self.cache.get_size()
        return (dx <= self.view.x + 1 and dy <= self.view.y + 1
                and dx + w * k >= self.view.right - 1 and dy + h * k >= self.view.bottom - 1)

    def _blit_cache(self, screen, theme):
        dx, dy, k = self._cache_place()
        old_clip = screen.get_clip()
        screen.set_clip(self.view)
        if abs(k - 1.0) < 1e-9:
            if not self._cache_covers():
                screen.fill(theme.sea, self.view)
            screen.blit(self.cache, (round(dx), round(dy)))
        else:
            # 화면에 보이는 부분만 잘라 늘린다(전체를 늘리면 확대할수록 느려진다)
            w, h = self.cache.get_size()
            x0 = max(0, int((self.view.x - dx) / k))
            y0 = max(0, int((self.view.y - dy) / k))
            x1 = min(w, int(math.ceil((self.view.right - dx) / k)) + 1)
            y1 = min(h, int(math.ceil((self.view.bottom - dy) / k)) + 1)
            screen.fill(theme.sea, self.view)
            if x1 > x0 and y1 > y0:
                part = self.cache.subsurface((x0, y0, x1 - x0, y1 - y0))
                size = (max(1, round((x1 - x0) * k)), max(1, round((y1 - y0) * k)))
                screen.blit(pygame.transform.scale(part, size), (round(dx + x0 * k), round(dy + y0 * k)))
        screen.set_clip(old_clip)

    def _render(self, full_key, theme, colors, sea_colors, mode, labels, show_terrain=True):
        """colors: rid -> (fill, outline). 화면보다 CACHE_MARGIN 만큼 넓게 그린다."""
        mx, my = int(self.view.w * CACHE_MARGIN), int(self.view.h * CACHE_MARGIN)
        surf = pygame.Surface((self.view.w + 2 * mx, self.view.h + 2 * my))
        # 바다색으로 채운다: 해역 다각형과 해안 사이에 틈이 있어도 바다로 보이게
        surf.fill(theme.sea)
        s = self.scale
        ox, oy = self.offset()
        ox += mx - self.view.x
        oy += my - self.view.y
        T = self.verts * s + (ox, oy)          # 모든 꼭짓점을 한 번에 변환

        def sp(span):
            return T[span[0]:span[1]].tolist()

        for sid, spans in self.sea_span.items():
            for span in spans:
                pygame.draw.polygon(surf, sea_colors.get(sid, theme.sea), sp(span))
        for sid, spans in self.sea_span.items():
            for span in spans:
                pygame.draw.lines(surf, theme.sea_line, True, sp(span), 1)
        view = surf.get_rect()
        thin = s < 1.2
        for (rid, arr, bbox), span in zip(self.polys, self.poly_span):
            x0, y0, x1, y1 = bbox
            if x1 * s + ox < 0 or x0 * s + ox > view.w or y1 * s + oy < 0 or y0 * s + oy > view.h:
                continue
            fill, line = colors[rid]
            if (x1 - x0) * s < 1.5 and (y1 - y0) * s < 1.5:
                surf.set_at((int(x0 * s + ox), int(y0 * s + oy)), fill)
                continue
            pts = sp(span)
            pygame.draw.polygon(surf, fill, pts)
            if not thin:
                pygame.draw.lines(surf, line, True, pts, 1)
            else:
                pygame.draw.aalines(surf, line, True, pts)
        pw = max(1, int((2 if self.z >= 2.5 else 1) * ui_scale()))
        closed = not self.world_outlines_open
        for span in self.province_span:
            if span[1] - span[0] >= 2:
                pygame.draw.lines(surf, theme.province_line, closed, sp(span), pw)
        if mode == "do8":
            for span in self.do8_span:
                if span[1] - span[0] >= 2:
                    pygame.draw.lines(surf, theme.do8_line, closed, sp(span), 2)
        if show_terrain:
            tw = max(2, int((3 if self.z < 2 else (4 if self.z < 4 else 5)) * ui_scale()))
            for kind, spans, connector in self.terrain_span:
                col = TERRAIN_COLORS[kind]
                for span in spans:
                    pts = sp(span)
                    if len(pts) < 2:
                        continue
                    if connector:
                        dashed(surf, pts[0], pts[-1], col, tw)
                    else:
                        pygame.draw.lines(surf, (255, 255, 255), False, pts, tw + 2)
                        pygame.draw.lines(surf, col, False, pts, tw)
        # 독도(동도·서도): 지역은 아니지만 지도에 그린다. 실제 크기로는 보이지 않아 최소 크기로 키운다
        land = colors.get(DOKDO_NEAR, (theme.neutral,))[0]   # 울릉군과 같은 색
        for lon, lat, r_deg in DOKDO:
            bx, by = proj(lon, lat)
            c = (int(bx * s + ox), int(by * s + oy))
            rad = max(int(r_deg * 100 * s), int(3.5 * ui_scale() * min(2.0, max(1.0, self.z / 3))))
            pygame.draw.circle(surf, land, c, rad)
            pygame.draw.circle(surf, theme.province_line, c, rad, 1)
        bx, by = proj(*DOKDO_LABEL)
        t = render_text("독도", 11 if self.z < 3 else 13, mix(theme.sea_line, theme.text, 0.6), "bold")
        surf.blit(t, t.get_rect(midleft=(bx * s + ox + 8, by * s + oy)))
        # 해역 이름
        for sid in self.sea_polys:
            x, y = self.label[sid]
            t = render_text(labels.get(sid, ""), 15 if self.z < 2 else 18, mix(theme.sea_line, theme.text, 0.35), "bold")
            surf.blit(t, t.get_rect(center=(x * s + ox, y * s + oy)))
        # 구역 이름
        if self.z >= 2.0:
            # 겹침 검사는 격자로: 같은 칸·이웃 칸에 놓인 이름끼리만 비교한다
            grid = {}

            def cells(r):
                for gx in range(r.left // LABEL_CELL, r.right // LABEL_CELL + 1):
                    for gy in range(r.top // LABEL_CELL, r.bottom // LABEL_CELL + 1):
                        yield gx, gy

            def free(r):
                return not any(r.colliderect(p) for c in cells(r) for p in grid.get(c, ()))

            def place(r):
                for c in cells(r):
                    grid.setdefault(c, []).append(r)
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
                if not free(r):
                    skipped.append((rid, name, px, py))
                    continue
                place(r.inflate(4, 2))
                surf.blit(t, r)
            # 겹쳐서 빠진 이름: 작은 글씨로 다시, 구역이 글자보다 넓거나 충분히 확대했으면 겹쳐도 표시
            for rid, name, px, py in skipped:
                t = render_text(name, max(10, size - 2), color, "semibold")
                r = t.get_rect(center=(px, py))
                if self.z >= 10 or free(r):
                    place(r.inflate(2, 0))
                    surf.blit(t, r)
        self.cache = surf
        self.cache_meta = {"key": full_key, "s": s, "cx": self.cx, "cy": self.cy,
                           "ox": ox, "oy": oy}    # 캐시 픽셀 = 기준 좌표 × s + (ox, oy)

    def outline(self, screen, rid, color, width=2):
        for arr, bbox in self.polys_by_rid.get(rid, ()):
            if self._visible_bbox(bbox):
                pygame.draw.lines(screen, color, True, self._screen_poly(arr), width)

    def fill_overlay(self, overlay, rid, rgba):
        ox, oy = self.view.x, self.view.y
        for arr, bbox in self.polys_by_rid.get(rid, ()):
            if self._visible_bbox(bbox):
                pts = [(x - ox, y - oy) for x, y in self._screen_poly(arr)]
                pygame.draw.polygon(overlay, rgba, pts)

    def sea_outline(self, screen, sid, color, width=3):
        for ext, holes in self.sea_polys[sid]:
            pygame.draw.lines(screen, color, True, self._screen_poly(ext), width)
            for h in holes:
                pygame.draw.lines(screen, color, True, self._screen_poly(h), max(1, width - 1))

    def sea_overlay(self, overlay, sid, rgba):
        """해역을 반투명하게 칠한다. 섬(구멍)은 투명하게 비운다 — 육지 오버레이보다 먼저 호출."""
        ox, oy = self.view.x, self.view.y
        for ext, holes in self.sea_polys[sid]:
            pygame.draw.polygon(overlay, rgba, [(x - ox, y - oy) for x, y in self._screen_poly(ext)])
            for h in holes:
                pygame.draw.polygon(overlay, (0, 0, 0, 0), [(x - ox, y - oy) for x, y in self._screen_poly(h)])
