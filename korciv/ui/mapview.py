"""지도 렌더링·좌표 변환·선택."""
from __future__ import annotations

import math

import numpy as np
import pygame

from .theme import font_px, mix, paper_texture, render_text, ui_scale

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


TERRAIN_COLORS = {"도하": (79, 134, 176), "돌파": (94, 107, 60)}   # 강(쪽빛) / 산줄기(먹빛 녹색)
RIDGE_FILL = (169, 178, 122)
INTERACT_IDLE_MS = 150    # 드래그·휠이 이만큼 멈추면 지도를 정식으로 다시 그린다
CACHE_MARGIN = 0.15       # 지도 캐시를 화면보다 상하좌우로 15%씩 넓게 그려, 작은 이동·휠 한 칸 축소는 다시 그리지 않는다
LABEL_CELL = 64           # 지명 겹침 검사용 격자 크기(px)


def _box(a, r):
    """상자 흐림(두 축, numpy 누적합). a: float32 2차원."""
    if r < 1:
        return a
    for ax in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[ax] = (r + 1, r)
        c = np.cumsum(np.pad(a, pad, mode="edge"), axis=ax, dtype=np.float32)
        if ax == 0:
            a = (c[2 * r + 1:] - c[:-2 * r - 1]) / (2 * r + 1)
        else:
            a = (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)
    return a


def _soft(mask, r, w, h):
    """bool 마스크를 절반 해상도에서 두 번 흐리고 원래 크기로 되돌린다(번짐·그림자용, 빠르게)."""
    half = mask[::2, ::2].astype(np.float32)
    b = _box(_box(half, r), r)
    return np.repeat(np.repeat(b, 2, axis=0), 2, axis=1)[:w, :h]


def _edges(a, both=None, thick=True):
    """이웃(오른쪽·아래)과 값이 다른 픽셀(thick 이면 양쪽 모두 = 2px 선). both 가 있으면 두 픽셀 모두 both 인 곳만."""
    out = np.zeros(a.shape, bool)
    ex = a[1:, :] != a[:-1, :]
    ey = a[:, 1:] != a[:, :-1]
    if both is not None:
        ex &= both[1:, :] & both[:-1, :]
        ey &= both[:, 1:] & both[:, :-1]
    out[1:, :] |= ex
    out[:, 1:] |= ey
    if thick:
        out[:-1, :] |= ex
        out[:, :-1] |= ey
    return out


_pattern_cache: dict = {}
_halo_cache: dict = {}


def sea_pattern(R, col, alpha):
    """청해파(겹친 반원 비늘) 타일. 가로 2R·세로 R 주기로 이어진다."""
    key = (R, col, alpha)
    t = _pattern_cache.get(key)
    if t is None:
        tw, th = 2 * R * 3, R * 2
        big = pygame.Surface((tw + 4 * R, th + 4 * R), pygame.SRCALPHA)
        row, y = 0, 0
        while y < th + 4 * R:
            x = -2 * R + (0 if row % 2 == 0 else R)
            while x < tw + 6 * R:
                for i in range(4):
                    rr = max(1, int(R * (1 - i / 4)))
                    pygame.draw.circle(big, (0, 0, 0, 0), (x, y), rr)
                    pygame.draw.circle(big, (*col, alpha), (x, y), rr, max(1, R // 18))
                x += 2 * R
            y += R // 2
            row += 1
        t = big.subsurface((2 * R, 2 * R, tw, th)).copy()
        _pattern_cache[key] = t
    return t


def halo_text(text, size, color, halo, weight="semibold", rad=1):
    """테두리(후광)를 두른 글자(실제 픽셀, 캐시)."""
    key = (text, font_px(size), color, halo, weight, rad)
    s = _halo_cache.get(key)
    if s is None:
        base = render_text(text, size, color, weight)
        hl = render_text(text, size, halo, weight)
        s = pygame.Surface((base.get_width() + 2 * rad, base.get_height() + 2 * rad), pygame.SRCALPHA)
        for dx in range(-rad, rad + 1):
            for dy in range(-rad, rad + 1):
                if (dx or dy) and dx * dx + dy * dy <= rad * rad + 1:
                    s.blit(hl, (rad + dx, rad + dy))
        s.blit(base, (rad, rad))
        if len(_halo_cache) > 3000:
            _halo_cache.clear()
        _halo_cache[key] = s
    return s


def draw_ridge_marks(surf, pts, k=1.0, spacing=11):
    """산줄기: 경로를 따라 작은 산 모양(∧)을 찍는다(대동여지도식)."""
    col = TERRAIN_COLORS["돌파"]
    step = spacing * k
    h, w = 6 * k, 5.5 * k
    lw = max(1, int(1.3 * k))
    acc = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        d = math.hypot(x2 - x1, y2 - y1)
        t = 0.0
        while acc + (d - t) >= step:
            t += step - acc
            acc = 0.0
            f = t / d if d else 0
            x, y = x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
            tri = [(x - w, y + h * 0.45), (x, y - h * 0.65), (x + w, y + h * 0.45)]
            pygame.draw.polygon(surf, RIDGE_FILL, tri)
            pygame.draw.lines(surf, col, False, tri, lw)
        acc += d - t


def dashed(surf, p1, p2, color, width=2, dash=6):
    x1, y1 = p1
    x2, y2 = p2
    d = math.hypot(x2 - x1, y2 - y1)
    n = max(2, int(d / dash))
    for i in range(0, n, 2):
        a, b = i / n, min(1, (i + 1) / n)
        pygame.draw.line(surf, color, (x1 + (x2 - x1) * a, y1 + (y2 - y1) * a),
                         (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b), width)


def _chains(segs):
    """선분 목록 [(a, b), ...] 을 끝점끼리 이어 꺾은선 목록으로."""
    adj = {}
    for i, (a, b) in enumerate(segs):
        adj.setdefault(a, []).append(i)
        adj.setdefault(b, []).append(i)
    used = [False] * len(segs)
    out = []
    for i in range(len(segs)):
        if used[i]:
            continue
        used[i] = True
        a, b = segs[i]
        line = [a, b]
        for end in (1, 0):                  # 뒤로, 앞으로 늘린다
            while True:
                p = line[-1] if end else line[0]
                nxt = next((j for j in adj.get(p, ()) if not used[j]), None)
                if nxt is None:
                    break
                used[nxt] = True
                q = segs[nxt][1] if segs[nxt][0] == p else segs[nxt][0]
                if end:
                    line.append(q)
                else:
                    line.insert(0, q)
        out.append(np.array(line, np.float64))
    return out


class MapView:
    MIN_Z, MAX_Z = 0.8, 40.0
    FX_RES = 1.5            # 번짐·전선 그림자 층: 기준 좌표 1당 픽셀(지도 전체를 한 번에 만들어 두고 잘라 쓴다)

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
        self.label.update({sid: proj(*p) for sid, p in world.sea_labels.items()})
        self.world_outlines_open = getattr(world, "outlines_open", False)
        self.province_lines = [proj_arr(r) for rings in world.province_outlines.values() for r in rings]
        # 지형 경계: (종류, [선...], 연결선 여부)
        self.terrain_lines = [("도하" if t["kind"] == "도하" else "돌파", [proj_arr(l) for l in t["lines"]],
                               t["connector"]) for t in world.terrain_lines]
        # 지역 경계 선분: 두 지역이 함께 쓰는 선분(국경 후보)과 한 지역만 쓰는 선분(해안·바깥 경계)
        seg = {}
        for rid, arr, bbox in self.polys:
            pts = [(round(x, 4), round(y, 4)) for x, y in arr.tolist()]
            for p0, p1 in zip(pts, pts[1:] + pts[:1]):
                if p0 != p1:
                    seg.setdefault((p0, p1) if p0 < p1 else (p1, p0), []).append(rid)
        shared, coast = {}, {}
        for k, rids in seg.items():
            rs = sorted(set(rids))
            if len(rs) == 2:
                shared.setdefault((rs[0], rs[1]), []).append(k)
            elif len(rs) == 1:
                coast.setdefault(rs[0], []).append(k)
        self.pair_lines = [(a_, b_, c) for (a_, b_), segs in shared.items() for c in _chains(segs)]
        self.coast_lines = [(r_, c) for r_, segs in coast.items() for c in _chains(segs)]
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
        self.terrain_span = [(kind, [put(a) for a in lines], conn) for kind, lines, conn in self.terrain_lines]
        self.pair_span = [(a_, b_, put(c)) for a_, b_, c in self.pair_lines]
        self.coast_span = [(r_, put(c)) for r_, c in self.coast_lines]
        # 경계 사슬의 사각형(화면 밖 사슬은 건너뛴다)
        self.pair_box = np.array([[*c.min(axis=0), *c.max(axis=0)] for _, _, c in self.pair_lines] or np.zeros((0, 4)))
        self.coast_box = np.array([[*c.min(axis=0), *c.max(axis=0)] for _, c in self.coast_lines] or np.zeros((0, 4)))
        self.verts = np.concatenate(bufs) if bufs else np.zeros((0, 2))
        self.rid_list = list(world.order)
        self.ridx = {rid: i for i, rid in enumerate(self.rid_list, 1)}     # 번호 지도용(1부터)
        self._fx = None             # (키, 번짐 층 Surface, 기준 좌표 원점)
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

    def draw_base(self, screen, key, theme, colors_fn, sea_colors_fn, mode, labels_fn, show_terrain=True, extra_fn=None):
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
            self._render(full_key, theme, colors_fn(), sea_colors_fn(), mode, labels_fn(), show_terrain,
                         extra_fn() if extra_fn else None)
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

    def _render(self, full_key, theme, colors, sea_colors, mode, labels, show_terrain=True, extra=None):
        """colors: rid -> (fill, outline). 화면보다 CACHE_MARGIN 만큼 넓게 그린다.
        extra: {"owners": rid -> 세력 코드(1=중립·미상, 2+세력 id), "deep": 코드 -> 진한 색, "wars": {(코드, 코드)},
                "glow": 국경 안쪽 번짐 여부} — 국경선·번짐·전선 그림자에 쓴다.
        국경·해안선은 미리 이어 둔 경계 사슬로 바로 긋고, 번짐·전선 그림자는 지도 전체 층(_fx_layer)을 잘라 붙인다."""
        extra = extra or {}
        u = ui_scale()
        mx, my = int(self.view.w * CACHE_MARGIN), int(self.view.h * CACHE_MARGIN)
        W_, H_ = self.view.w + 2 * mx, self.view.h + 2 * my
        surf = pygame.Surface((W_, H_))
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
        # 청해파 무늬(화면 기준으로 깔아서 확대해도 굵기가 같다)
        R = max(10, int(24 * u))
        pat = sea_pattern(R, mix(theme.sea, (255, 255, 255), 0.55 if not theme.dark else 0.25), 46 if not theme.dark else 30)
        pw_, ph_ = pat.get_size()
        px0, py0 = int(ox) % pw_ - pw_, int(oy) % ph_ - ph_
        for yy in range(py0, H_, ph_):
            for xx in range(px0, W_, pw_):
                surf.blit(pat, (xx, yy))
        for sid, spans in self.sea_span.items():
            for span in spans:
                pygame.draw.lines(surf, theme.sea_line, True, sp(span), 1)
        view = surf.get_rect()
        owners = extra.get("owners", {})

        def on_screen(boxes):
            if not len(boxes):
                return np.zeros(0, bool)
            return ((boxes[:, 2] * s + ox >= 0) & (boxes[:, 0] * s + ox <= W_)
                    & (boxes[:, 3] * s + oy >= 0) & (boxes[:, 1] * s + oy <= H_))
        coast_vis = [cs for cs, v in zip(self.coast_span, on_screen(self.coast_box)) if v]
        pair_vis = [ps for ps, v in zip(self.pair_span, on_screen(self.pair_box))
                    if v and owners.get(ps[0], 1) != owners.get(ps[1], 1)]
        # 얕은 바다: 해안선을 굵고 밝게 먼저 긋고, 땅을 칠하면 바다 쪽 절반만 남는다
        light = mix(theme.sea, (255, 255, 255), 0.3 if not theme.dark else 0.1)
        cw = max(4, int(9 * u))
        for rid, span in coast_vis:
            pts = sp(span)
            if len(pts) >= 2:
                pygame.draw.lines(surf, light, False, pts, cw)
        # 땅 칠하기
        for (rid, arr, bbox), span in zip(self.polys, self.poly_span):
            x0, y0, x1, y1 = bbox
            if x1 * s + ox < 0 or x0 * s + ox > view.w or y1 * s + oy < 0 or y0 * s + oy > view.h:
                continue
            fill = colors[rid][0]
            if (x1 - x0) * s < 1.5 and (y1 - y0) * s < 1.5:
                p0 = (int(x0 * s + ox), int(y0 * s + oy))
                if view.collidepoint(p0):
                    surf.set_at(p0, fill)
                continue
            pygame.draw.polygon(surf, fill, sp(span))
        # 국경 안쪽 번짐 + 전선 그림자: 지도 전체 층을 한 번 만들어 두고 보이는 부분만 잘라 붙인다
        fx = self._fx_layer(extra)
        if fx is not None:
            layer, (bx0, by0) = fx
            res = self.FX_RES
            # 캐시 화면 → 기준 좌표 → 층 픽셀
            vx0, vy0 = (0 - ox) / s, (0 - oy) / s
            vx1, vy1 = (W_ - ox) / s, (H_ - oy) / s
            lx0, ly0 = max(0.0, (vx0 - bx0) * res), max(0.0, (vy0 - by0) * res)
            lx1, ly1 = min(layer.get_width(), (vx1 - bx0) * res), min(layer.get_height(), (vy1 - by0) * res)
            if lx1 - lx0 >= 1 and ly1 - ly0 >= 1:
                ix0, iy0 = int(lx0), int(ly0)
                ix1, iy1 = int(math.ceil(lx1)), int(math.ceil(ly1))
                part = layer.subsurface((ix0, iy0, ix1 - ix0, iy1 - iy0))
                tx, ty = (ix0 / res + bx0) * s + ox, (iy0 / res + by0) * s + oy
                tw, th = (ix1 - ix0) / res * s, (iy1 - iy0) / res * s
                if tw * th < 6e7:
                    surf.blit(pygame.transform.smoothscale(part, (max(1, round(tw)), max(1, round(th)))),
                              (round(tx), round(ty)))
        # 한지 결
        if not theme.dark:
            tex = paper_texture()
            tw_, th_ = tex.get_size()
            for yy in range(0, H_, th_):
                for xx in range(0, W_, tw_):
                    surf.blit(tex, (xx, yy), special_flags=pygame.BLEND_RGB_MULT)
        # 시군구 경계(가는 선)
        thin = s < 1.2
        for (rid, arr, bbox), span in zip(self.polys, self.poly_span):
            x0, y0, x1, y1 = bbox
            if x1 * s + ox < 0 or x0 * s + ox > view.w or y1 * s + oy < 0 or y0 * s + oy > view.h:
                continue
            if (x1 - x0) * s < 1.5 and (y1 - y0) * s < 1.5:
                continue
            line = mix(colors[rid][0], (40, 32, 24), 0.2)
            if thin:
                pygame.draw.aalines(surf, line, True, sp(span))
            else:
                pygame.draw.lines(surf, line, True, sp(span), 1)
        # 해안선·국경(먹선): 미리 이어 둔 경계 사슬을 바로 긋는다
        coast_ink = (62, 74, 76) if not theme.dark else (140, 160, 165)
        for rid, span in coast_vis:
            pts = sp(span)
            if len(pts) >= 2:
                pygame.draw.lines(surf, coast_ink, False, pts, max(1, int(1.3 * u)))
        border_ink = (74, 60, 46) if not theme.dark else (12, 10, 8)
        bw = max(2, int(2.2 * u))
        for a_, b_, span in pair_vis:
            pts = sp(span)
            if len(pts) >= 2:
                pygame.draw.lines(surf, border_ink, False, pts, bw)

        pw = max(1, int((2 if self.z >= 2.5 else 1) * u))
        closed = not self.world_outlines_open
        prov = mix(theme.province_line, theme.paper, 0.35)
        for span in self.province_span:
            if span[1] - span[0] >= 2:
                pygame.draw.lines(surf, prov, closed, sp(span), max(1, pw - 1))
        if show_terrain:
            tw = max(2, int((2 if self.z < 2 else (3 if self.z < 4 else 4)) * u))
            halo = mix(theme.sea, (255, 255, 255), 0.4)
            for kind, spans, connector in self.terrain_span:
                col = TERRAIN_COLORS[kind]
                for span in spans:
                    pts = sp(span)
                    if len(pts) < 2:
                        continue
                    if connector:
                        dashed(surf, pts[0], pts[-1], col, tw)
                    elif kind == "도하":
                        pygame.draw.lines(surf, halo, False, pts, tw + 2)
                        pygame.draw.lines(surf, col, False, pts, tw)
                    else:
                        draw_ridge_marks(surf, pts, u * (0.8 if self.z < 2 else 1.0))
        # 독도(동도·서도): 지역은 아니지만 지도에 그린다. 실제 크기로는 보이지 않아 최소 크기로 키운다
        land_c = colors.get(DOKDO_NEAR, (theme.neutral,))[0]   # 울릉군과 같은 색
        for lon, lat, r_deg in DOKDO:
            bx, by = proj(lon, lat)
            c = (int(bx * s + ox), int(by * s + oy))
            rad = max(int(r_deg * 100 * s), int(3.5 * u * min(2.0, max(1.0, self.z / 3))))
            pygame.draw.circle(surf, land_c, c, rad)
            pygame.draw.circle(surf, (62, 74, 76), c, rad, 1)
        sea_ink = getattr(theme, "sea_ink", theme.sea_line)
        sea_halo = mix(theme.sea, (255, 255, 255), 0.35 if not theme.dark else 0.0)
        bx, by = proj(*DOKDO_LABEL)
        t = halo_text("독도", 11 if self.z < 3 else 13, sea_ink, sea_halo, "bold")
        surf.blit(t, t.get_rect(midleft=(bx * s + ox + 8, by * s + oy)))
        # 해역 이름(명조, 글자 간격)
        for sid in self.sea_polys:
            x, y = self.label[sid]
            name = labels.get(sid, "")
            t = halo_text(" ".join(name) if len(name) <= 4 else name, 15 if self.z < 2 else 18, sea_ink, sea_halo, "title", 2)
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
            nhalo = (247, 241, 227) if not theme.dark else (20, 24, 30)
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
                t = halo_text(name, size, color, nhalo)
                r = t.get_rect(center=(px, py - (6 if self.z >= 4 else 0)))
                if not free(r.inflate(-2, -2)):
                    skipped.append((rid, name, px, py))
                    continue
                place(r.inflate(2, 0))
                surf.blit(t, r)
            # 겹쳐서 빠진 이름: 작은 글씨로 다시, 구역이 글자보다 넓거나 충분히 확대했으면 겹쳐도 표시
            for rid, name, px, py in skipped:
                t = halo_text(name, max(10, size - 2), color, nhalo)
                r = t.get_rect(center=(px, py))
                if self.z >= 10 or free(r.inflate(-2, -2)):
                    place(r)
                    surf.blit(t, r)
        self.cache = surf
        self.cache_meta = {"key": full_key, "s": s, "cx": self.cx, "cy": self.cy,
                           "ox": ox, "oy": oy}    # 캐시 픽셀 = 기준 좌표 × s + (ox, oy)

    def _fx_layer(self, extra):
        """국경 안쪽 번짐(정치 지도)과 전쟁 국경 그림자: 지도 전체 크기의 반투명 층(내용이 바뀔 때만 다시 만든다).
        돌려주는 값: (층, 층 원점의 기준 좌표) 또는 None."""
        if not extra:
            return None
        owners = extra.get("owners", {})
        deep = extra.get("deep", {}) if extra.get("glow") else {}
        wars = extra.get("wars") or set()
        if not deep and not wars:
            return None
        key = (tuple(owners.get(r, 1) for r in self.rid_list), tuple(sorted(deep.items())), tuple(sorted(wars)))
        if self._fx is not None and self._fx[0] == key:
            return self._fx[1]
        res = self.FX_RES
        vx0, vy0 = self.verts.min(axis=0) - 4
        vx1, vy1 = self.verts.max(axis=0) + 4
        w, h = int((vx1 - vx0) * res) + 1, int((vy1 - vy0) * res) + 1
        idm = pygame.Surface((w, h))
        idm.fill((0, 0, 0))
        for rid, arr, bbox in self.polys:
            code = owners.get(rid, 1)
            pts = ((arr - (vx0, vy0)) * res).tolist()
            if len(pts) >= 3:
                pygame.draw.polygon(idm, (code, 0, 0), pts)
        own = pygame.surfarray.array3d(idm)[..., 0].astype(np.int32)
        land = own > 0
        fb = _edges(own, land, thick=False)
        rgb = np.zeros(own.shape + (3,), np.float32)
        alp = np.zeros(own.shape, np.float32)
        r1 = max(1, int(2.5 * res))
        if deep and fb.any():
            g = np.clip(_box(_box(fb.astype(np.float32), r1), r1) * 2.6, 0, 1) ** 1.3 * 0.55
            g *= own >= 2
            lut = np.zeros((max(int(own.max()), max(deep)) + 1, 3), np.float32)
            for k, c in deep.items():
                lut[k] = c
            rgb = lut[own]
            alp = g
        if wars:
            m = max(int(own.max()), max(max(p) for p in wars)) + 1
            wl = np.zeros((m, m), bool)
            for a_, b_ in wars:
                wl[a_, b_] = wl[b_, a_] = True
            wb = np.zeros(own.shape, bool)
            ex = wl[own[1:, :], own[:-1, :]]
            ey = wl[own[:, 1:], own[:, :-1]]
            wb[1:, :] |= ex
            wb[:-1, :] |= ex
            wb[:, 1:] |= ey
            wb[:, :-1] |= ey
            if wb.any():
                wv = np.clip(_box(_box(wb.astype(np.float32), r1), r1) * 2.0, 0, 1) * 0.34 * land
                k = wv / np.maximum(alp + wv, 1e-6)
                rgb += (np.array((150, 52, 40), np.float32) - rgb) * k[..., None]
                alp = alp + wv * (1 - alp)
        layer = pygame.Surface((w, h), pygame.SRCALPHA)
        px = pygame.surfarray.pixels3d(layer)
        px[...] = np.clip(rgb, 0, 255).astype(np.uint8)
        del px
        pa = pygame.surfarray.pixels_alpha(layer)
        pa[...] = np.clip(alp * 255, 0, 255).astype(np.uint8)
        del pa
        out = (layer, (float(vx0), float(vy0)))
        self._fx = (key, out)
        return out

    def outline_overlay(self, overlay, rid, rgba, width=2, origin=None):
        """반투명 윤곽(overlay 의 왼쪽 위 = 화면 좌표 origin, 기본은 지도 view 왼쪽 위)."""
        ox, oy = origin or (self.view.x, self.view.y)
        for arr, bbox in self.polys_by_rid.get(rid, ()):
            if self._visible_bbox(bbox):
                pts = [(x - ox, y - oy) for x, y in self._screen_poly(arr)]
                if len(pts) > 2:
                    pygame.draw.lines(overlay, rgba, True, pts, width)

    def outline(self, screen, rid, color, width=2):
        for arr, bbox in self.polys_by_rid.get(rid, ()):
            if self._visible_bbox(bbox):
                pygame.draw.lines(screen, color, True, self._screen_poly(arr), width)

    def screen_bbox(self, nodes, pad=0):
        """지역·해역들의 화면 사각형(지도 view 안으로 자름). 반투명 덮개를 필요한 크기만 만들 때 쓴다."""
        s = self.scale
        ox, oy = self.offset()
        r = None
        for n in nodes:
            if n in self.rbbox:
                x0, y0, x1, y1 = self.rbbox[n]
            elif n in self.sea_polys:
                pts = np.concatenate([ext for ext, _ in self.sea_polys[n]])
                (x0, y0), (x1, y1) = pts.min(axis=0), pts.max(axis=0)
            else:
                continue
            rr = pygame.Rect(int(x0 * s + ox) - pad, int(y0 * s + oy) - pad,
                             int((x1 - x0) * s) + 2 * pad + 2, int((y1 - y0) * s) + 2 * pad + 2)
            r = rr if r is None else r.union(rr)
        return r.clip(self.view) if r is not None else None

    def fill_overlay(self, overlay, rid, rgba, origin=None):
        ox, oy = origin or (self.view.x, self.view.y)
        for arr, bbox in self.polys_by_rid.get(rid, ()):
            if self._visible_bbox(bbox):
                pts = [(x - ox, y - oy) for x, y in self._screen_poly(arr)]
                pygame.draw.polygon(overlay, rgba, pts)

    def sea_outline(self, screen, sid, color, width=3):
        for ext, holes in self.sea_polys[sid]:
            pygame.draw.lines(screen, color, True, self._screen_poly(ext), width)
            for h in holes:
                pygame.draw.lines(screen, color, True, self._screen_poly(h), max(1, width - 1))

    def sea_overlay(self, overlay, sid, rgba, origin=None):
        """해역을 반투명하게 칠한다. 섬(구멍)은 투명하게 비운다 — 육지 오버레이보다 먼저 호출."""
        ox, oy = origin or (self.view.x, self.view.y)
        for ext, holes in self.sea_polys[sid]:
            pygame.draw.polygon(overlay, rgba, [(x - ox, y - oy) for x, y in self._screen_poly(ext)])
            for h in holes:
                pygame.draw.polygon(overlay, (0, 0, 0, 0), [(x - ox, y - oy) for x, y in self._screen_poly(h)])
