"""설정 화면과 모달: 정치체제, 반란, 조약 제안, 외교, 반기 랭킹, 로그, 도움말, 게임 종료."""
from __future__ import annotations

import math
import os
import random

import pygame

from .. import config as C
from .. import diplomacy as D
from .. import flags as FL
from .. import rules as R
from ..leaders import GOVERNMENTS, LEADERS, LEADER_BY_KEY, LEADER_CATEGORIES, gov_buff_scale
from ..state import NEUTRAL, Settings
from .art import draw_flag, draw_portrait, render_flag
from .theme import hex2rgb, measure, mix


class SetupState:
    def __init__(self):
        self.name = "대한"
        self.leader = "sej"
        self.custom_name = ""
        self.n_enemies = 7
        self.difficulty = 2
        self.fog = 1
        self.victories = {k: True for k in C.VICTORY_TYPES}
        self.start = None
        self.ai_leaders = []          # 빈 칸은 무작위
        self.ai_starts = []           # 칸별 시작 지역(빈 칸은 무작위)
        self.ai_place = 0             # 적 국가 지역 선택 화면에서 고른 칸
        self.seed = ""
        self.max_turns = C.TIME_VICTORY_TURNS
        self.flag = FL.normalize({"bg": "solid", "c1": FL.hex2rgb(C.FACTION_COLORS[0]), "em": "disc"})
        self.flag_draft = None        # 국기 편집 창이 열려 있으면 편집 중인 사본
        self.ai_pick = None           # 적 지도자 고르기 창이 열려 있으면 그 칸 번호
        self.flag_target = 0          # FLAG_TARGETS 순번: 배경 색 1·2, 문양 색 1·2


def modal_frame(app, w, h, title=None):
    dim = pygame.Surface(app.screen.get_size(), pygame.SRCALPHA)
    dim.fill((17, 30, 49, 110))
    app.screen.blit(dim, (0, 0))
    sw, sh = app.gui.size()
    r = pygame.Rect(0, 0, w, h)
    r.center = (sw // 2, sh // 2)
    app.gui.panel(r, radius=6, ornament=True)
    if title:
        app.gui.text((r.x + 26, r.y + 18), title, 22, weight="title")
    return r


# ------------------------------------------------------------------ 수량 고르기 (슬라이더)
def open_qty(app, title, max_value, value, on_ok, preview=None, step=1, ok_label="확인"):
    """0 ~ max_value 슬라이더로 수량을 고르는 작은 창. on_ok(값)을 부른다. preview(값) -> 설명 문자열."""
    max_value = max(0, int(max_value))
    app.qty = {"title": title, "max": max_value, "value": max(0, min(max_value, int(value))), "on_ok": on_ok,
               "preview": preview, "step": max(1, int(step)), "ok": ok_label}


def draw_qty(app):
    gui = app.gui
    t = app.theme
    q = app.qty
    r = modal_frame(app, 520, 250, q["title"])
    mx, step = q["max"], q["step"]
    v = q["value"]
    gui.text((r.right - 24, r.y + 24), f"최대 {mx:,}", 13, t.muted, anchor="topright")
    gui.text((r.centerx, r.y + 64), f"{v:,}", 26, weight="bold", anchor="midtop")
    if mx > 0:
        nv, _ = gui.slider((r.x + 40, r.y + 118, r.w - 80, 20), v, 0, mx, step, "qty_slider")
        v = int(nv)
    else:
        gui.text((r.centerx, r.y + 118), "고를 수 있는 양이 없습니다.", 13, t.bad, anchor="midtop")
    gui.text((r.x + 40, r.y + 136), "0", 11, t.muted)
    gui.text((r.right - 40, r.y + 136), f"{mx:,}", 11, t.muted, anchor="topright")
    bw = 56
    for i, (lab, dv) in enumerate((("−10", -10 * step), ("−1", -step), ("+1", step), ("+10", 10 * step))):
        if gui.button((r.x + 40 + i * (bw + 6), r.y + 160, bw, 28), lab, size=12, enabled=mx > 0):
            v += dv
    if gui.button((r.x + 40 + 4 * (bw + 6), r.y + 160, 70, 28), "최대", size=12, enabled=mx > 0):
        v = mx
    v = max(0, min(mx, v))
    q["value"] = v
    if q["preview"]:
        gui.text((r.x + 24, r.bottom - 34), q["preview"](v), 12, t.muted, max_w=r.w - 230)
    if gui.button((r.right - 200, r.bottom - 50, 84, 36), "취소"):
        app.qty = None
        return
    if gui.button((r.right - 108, r.bottom - 50, 84, 36), q["ok"], "primary", enabled=v > 0 or q["ok"] == "확인"):
        on_ok = q["on_ok"]
        app.qty = None
        on_ok(v)
    for k in list(gui.keys):
        if k.key == pygame.K_ESCAPE:
            app.qty = None
            gui.keys.remove(k)
        elif k.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and app.qty:
            on_ok = q["on_ok"]
            app.qty = None
            gui.keys.remove(k)
            on_ok(v)


def rgb_hsl(rgb):
    """RGB(0~255) → (색조 0~360, 채도 0~100, 명도 0~100)."""
    import colorsys
    h, l, s_ = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return round(h * 360) % 361, round(s_ * 100), round(l * 100)


def hsl_rgb(h, s_, l):
    """(색조 0~360, 채도 0~100, 명도 0~100) → RGB(0~255)."""
    import colorsys
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb((h % 360) / 360, l / 100, s_ / 100))


def parse_byte(text: str) -> int:
    """0~255 직접 입력: 255를 넘으면 255, 숫자가 아니면(빈칸·음수·문자) 0."""
    text = (text or "").strip()
    if not text.isdigit():
        return 0
    return min(255, int(text))


def _num_input(gui, owner, rect, tid, value):
    """숫자 입력칸. 입력하는 동안은 글자 그대로 두고, Enter·다른 곳 클릭으로 끝나면 parse_byte 로 반영."""
    drafts = owner.__dict__.setdefault("num_drafts", {})
    shown = drafts.get(tid, str(value))
    new = gui.text_input(rect, tid, shown, size=13, max_len=6)
    if gui.focus == tid:
        drafts[tid] = new
        return value
    if tid in drafts:
        drafts.pop(tid)
        return parse_byte(new)
    return value


VICTORY_TIPS = {
    "conquest": f"정복승리: 전체 지역의 3분의 2 이상을 차지하고, 반란이 일어날 수 있는 지역\n"
                f"(반란 판정 행복도 {C.REBEL_THRESHOLD:.0f} 이하)이 하나도 없으면 승리. 다른 세력을 모두 멸망시켜도 승리",
    "science": "과학승리: ① 수도에 항공우주연구소 → ② 산맥과 맞닿은 지역에 천체관측소 → ③ 은행 5단계(금융 단지) 지역에서\n"
               "예산 편성 → ④ 바다와 맞닿은 지역에 로켓 발사대 → ⑤ 공장 5단계 지역에서 로켓 추진체 →\n"
               "⑥ 공장 5단계 지역에서 탑승 모듈 → ⑦ 석유 생산 지역에서 발사체 연료. 세 유닛을 발사대 지역에 모으고 턴을 마치면 승리\n"
               f"(단계마다 {C.SCIENCE_TURNS}턴, 턴당 {C.SCIENCE_COST_PER_TURN:,}부터 단계가 오를 때마다 ×{C.SCIENCE_COST_GROWTH:g})\n"
               "천체관측소가 폭격으로 파괴되면 다른 단계를 다 마쳤어도 다시 지을 때까지 발사할 수 없습니다",
    "economic": f"경제승리: ① 수도를 포함해 서로 맞닿은 금융 단지(은행 5단계) {C.ECON_CLUSTER}곳 → ② 금융 권역에\n"
                f"증권거래소(수도 포함 {C.ECON_EXCHANGES}곳) → ③ 수도에 경제특구 → ④ 우호 선언 이상 관계 {C.ECON_IFC_FRIENDS}개국이면\n"
                f"국제금융센터 → ⑤ 우호 선언 이상 {C.ECON_CURRENCY_FRIENDS}개국(동맹 {C.ECON_CURRENCY_ALLIES}곳 이상)이면 "
                "수도에서 기축통화 지정. 완료하면 승리\n(건설 중 조건이 깨지면 중단·50% 환급, 다시 지으려면 처음부터)",
    "diplomatic": "외교승리: 살아 있는 모든 나라가 하나의 연합에 속하면 연합 전원이 함께 승리",
    "time": f"시간 종료 승리: 정해진 턴(아래 슬라이더, 기본 {C.TIME_VICTORY_TURNS}턴)이 되면\n"
            "점수(점유 지역·GDP·인구 비율의 평균)가 가장 높은 세력이 승리",
}


# ------------------------------------------------------------------ 시작 페이지
_logo = {}
_bg = {}
ASSET_UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ui")


def draw_backdrop(app):
    """시작·설정 화면 배경(수묵 산수, assets/ui/title_bg.jpg — tools/build_title_bg.py): 창을 꽉 채운다."""
    screen = app.gui.screen
    size = screen.get_size()
    if "src" not in _bg:
        try:
            _bg["src"] = pygame.image.load(os.path.join(ASSET_UI, "title_bg.jpg")).convert()
        except Exception:
            _bg["src"] = None
    src = _bg["src"]
    if src is None:
        screen.fill(app.theme.indigo_dk)
        return
    if _bg.get("size") != size:
        bw, bh = src.get_size()
        k = max(size[0] / bw, size[1] / bh)
        big = pygame.transform.smoothscale(src, (max(1, round(bw * k)), max(1, round(bh * k))))
        _bg["img"] = big.subsurface(((big.get_width() - size[0]) // 2, (big.get_height() - size[1]) // 2,
                                     size[0], size[1])).copy()
        _bg["size"] = size
    screen.blit(_bg["img"], (0, 0))


def _latest_save(app):
    """가장 최근 저장 슬롯 설명(시작 화면 [이어하기] 아래 줄). 저장 파일이 바뀌었을 때만 다시 읽는다."""
    from .app import SAVE_DIR
    stamp = []
    for i in range(1, C.SAVE_SLOTS + 1):
        path = os.path.join(SAVE_DIR, f"slot{i}.sav")
        stamp.append(os.path.getmtime(path) if os.path.exists(path) else None)
    stamp = tuple(stamp)
    c = getattr(app, "_title_save", None)
    if c is None or c[0] != stamp:
        infos = [(i, app.slot_info(i)) for i, m in enumerate(stamp, 1) if m is not None]
        infos = [(i, inf) for i, inf in infos if inf]
        text = None
        if infos:
            i, inf = max(infos, key=lambda p: p[1]["mtime"])
            text = f"슬롯 {i} · {inf['label']}"
        c = (stamp, text)
        app._title_save = c
    return c[1]


def draw_title(app):
    """시작 페이지: 수묵 산수 배경, 가운데 로고, 아래 메뉴([새로 시작]·[이어하기]·[도움말]·[종료])."""
    gui = app.gui
    t = app.theme
    sw, sh = gui.size()
    draw_backdrop(app)
    if "src" not in _logo:
        try:
            _logo["src"] = pygame.image.load(os.path.join(ASSET_UI, "logo.png"))
        except Exception:
            _logo["src"] = None
    src = _logo["src"]
    bw = 300
    lw = min(sw * 0.62, (sh - 330) * (src.get_width() / src.get_height()) if src else 600, 900)
    lh = lw * src.get_height() / src.get_width() if src else 120
    top = max(20, (sh - (lh + 28 + 50 + 50 + 40 + 40 + 30)) / 2 - 10)
    lr = pygame.Rect(int((sw - lw) / 2), int(top), int(lw), int(lh))
    if src:
        pr = gui.R(lr)
        if _logo.get("size") != pr.size:
            _logo["size"], _logo["img"] = pr.size, pygame.transform.smoothscale(src, pr.size)
        gui.screen.blit(_logo["img"], pr.topleft)
    else:
        gui.text(lr.center, "한반도의 문명", 48, (247, 241, 227), "title", anchor="center")
    paper = (247, 241, 227)
    y = lr.bottom + 26
    # 새로 시작: 한지 버튼 + 금테 + 모서리 꺾쇠 + 좌우 장식선
    r = pygame.Rect(int(sw / 2 - bw / 2), int(y), bw, 50)
    hov = gui.hover(r)
    gui.shadow(r, 4, 8, 120)
    gui.rect(mix((244, 236, 219), (255, 255, 255), 0.3) if hov else (244, 236, 219), r)
    gui.paper(r)
    pygame.draw.rect(gui.screen, t.gold, gui.R(r), max(1, int(2 * gui.u)))
    pygame.draw.rect(gui.screen, mix(t.gold, paper, 0.3), gui.R(r.inflate(-8, -8)), 1)
    gui.ornament(r.inflate(-8, -8), mix(t.gold, t.ink, 0.3), 9, 2)
    gui.text((r.centerx, r.y + 7), "새로 시작", 19, t.indigo_dk, "title", anchor="midtop")
    gui.text((r.centerx, r.y + 33), "새 나라를 세웁니다", 10, mix(t.indigo, paper, 0.25), "semibold", anchor="midtop")
    for sx in (-1, 1):
        x0, x1 = r.centerx + sx * (bw / 2 + 14), r.centerx + sx * (bw / 2 + 84)
        gui.line(t.gold, (x0, r.centery), (x1, r.centery), 1)
        gui.polygon(t.gold, [(x0, r.centery - 4), (x0 + sx * 6, r.centery), (x0, r.centery + 4), (x0 - sx * 6, r.centery)])
    if hov and gui.clicked:
        gui.clicked = False
        app.scene = "setup"
    y = r.bottom + 10
    latest = _latest_save(app)

    def dark_button(rect, label, sub=None, enabled=True):
        rr = pygame.Rect(rect)
        hv = enabled and gui.hover(rr)
        g = pygame.Surface(gui.R(rr).size, pygame.SRCALPHA)
        g.fill((*mix(t.indigo_dk, (255, 255, 255), 0.08 if hv else 0.0), 170))
        gui.screen.blit(g, gui.R(rr).topleft)
        pygame.draw.rect(gui.screen, mix(t.gold, t.indigo, 0.2 if hv else 0.35), gui.R(rr), 1)
        fg = paper if enabled else mix(paper, t.indigo, 0.5)
        if sub:
            gui.text((rr.centerx, rr.y + 6), label, 17, fg, "title", anchor="midtop")
            gui.text((rr.centerx, rr.y + 30), sub, 10, mix(t.gold_lt, t.indigo, 0.2), "semibold", anchor="midtop",
                     max_w=rr.w - 20)
        else:
            gui.text(rr.center, label, 15, fg, "title", anchor="center")
        gui.block(rr)
        if hv and gui.clicked:
            gui.clicked = False
            return True
        return False

    if dark_button((r.x, y, bw, 48 if latest else 40), "이어하기", latest or None):
        app.open_slots("load")
    y += (48 if latest else 40) + 10
    if dark_button((r.x, y, bw, 38), "도움말"):
        app.modal = ("help", None)
    y += 48
    if dark_button((r.x, y, bw, 38), "종료"):
        app.running = False
    from ..version import RELEASE_DATE, VERSION
    gui.text((sw - 16, sh - 12), f"v{VERSION} · {RELEASE_DATE} 업데이트", 11, mix(t.gold_lt, t.indigo, 0.4), "semibold",
             anchor="bottomright")


# ------------------------------------------------------------------ 게임 설정
_mini = {}


def _minimap(app, rect):
    """시작 지역 미니맵(실제 지도, 크기별 캐시)."""
    gui = app.gui
    pr = gui.R(rect)
    key = (pr.size, app.theme.dark)
    img = _mini.get(key)
    if img is None:
        mv = app.map
        img = pygame.Surface(pr.size)
        img.fill(app.theme.sea)
        from .mapview import BASE_H, BASE_W
        k = min(pr.w / (BASE_W - 60), pr.h / (BASE_H - 40)) * 1.02
        ox, oy = pr.w / 2 - 285 * k, pr.h / 2 - 500 * k
        land, line = app.theme.neutral, mix(app.theme.neutral, (40, 32, 24), 0.35)
        for rid, arr, bbox in mv.polys:
            pts = (arr * k + (ox, oy)).tolist()
            if len(pts) >= 3:
                pygame.draw.polygon(img, land, pts)
        for rid, arr, bbox in mv.polys:
            pts = (arr * k + (ox, oy)).tolist()
            if len(pts) >= 3 and (bbox[2] - bbox[0]) * k > 2:
                pygame.draw.aalines(img, line, True, pts)
        _mini.clear()
        _mini[key] = img
        _mini["xf"] = (k, ox, oy)
    gui.screen.blit(img, pr.topleft)
    k, ox, oy = _mini["xf"]

    def at(rid):
        x, y = app.map.label[rid]
        return pr.x + x * k + ox, pr.y + y * k + oy
    return at


def _star_poly(cx, cy, r):
    return [(cx + (r if i % 2 == 0 else r * 0.42) * math.cos(-math.pi / 2 + i * math.pi / 5),
             cy + (r if i % 2 == 0 else r * 0.42) * math.sin(-math.pi / 2 + i * math.pi / 5)) for i in range(10)]


def _scroll_rods(gui, r):
    """두루마리 좌우 나무 축."""
    for x in (r.x - 16, r.right - 8):
        rod = pygame.Rect(x, r.y - 12, 24, r.h + 24)
        gui.shadow(rod, 6, 4, 110)
        gui.rect((58, 42, 30), rod, radius=8)
        gui.rect((90, 66, 48), rod.inflate(-10, -4), radius=6)
        for yy in (rod.y - 9, rod.bottom - 7):
            gui.rect(gui.t.gold, (rod.x + 3, yy, 18, 16), radius=4)
            pygame.draw.rect(gui.screen, mix(gui.t.gold, gui.t.ink, 0.4), gui.R((rod.x + 3, yy, 18, 16)), 1,
                             border_radius=int(4 * gui.u))


def _label(gui, x, y, text, hanja=None):
    t = gui.t
    r = gui.text((x, y), text, 14, t.accent if not t.dark else t.gold_lt, "serif")
    if hanja:
        gui.text((r.right + 6, y + 1), hanja, 12, mix(t.accent if not t.dark else t.gold_lt, t.panel, 0.4), "serif")
    return r


def draw_setup(app):
    """게임 설정(건국): 두루마리처럼 펼친 한지 위에 왼쪽 국호·국기·지도자, 오른쪽 천하의 형세·시작 지역."""
    from ..game import player_color
    from .art import portrait_path
    gui = app.gui
    t = app.theme
    s = app.setup
    sw, sh = app.gui.size()
    draw_backdrop(app)
    dim = pygame.Surface(gui.screen.get_size(), pygame.SRCALPHA)
    dim.fill((*t.indigo_dk, 110))
    gui.screen.blit(dim, (0, 0))
    r = pygame.Rect(0, 0, 1180, 760)
    r.center = (sw // 2, sh // 2)
    gui.shadow(r, 4, 14, 140)
    gui.rect(t.panel, r)
    gui.paper(r)
    pygame.draw.rect(gui.screen, mix(t.gold, t.panel, 0.2), gui.R(r.inflate(-20, -20)), 1)
    pygame.draw.rect(gui.screen, mix(t.gold, t.panel, 0.45), gui.R(r.inflate(-26, -26)), 1)
    gui.block(r)
    _scroll_rods(gui, r)
    # 머리글
    hr = gui.text((r.x + 40, r.y + 22), "건국", 28, t.text, "title")
    gui.text((hr.right + 10, r.y + 27), "建國", 22, mix(t.text, t.vermilion, 0.55), "title")
    gui.text((hr.right + 80, r.y + 34), "새 나라를 세웁니다 · 426개 시군구 · 1턴 = 1주 · 2026년 1월 1주(소한) 시작 · 정치체제는 첫 턴에 고릅니다",
             11, t.muted, "semibold", max_w=r.right - 60 - hr.right - 80)
    gui.line(t.text, (r.x + 40, r.y + 66), (r.right - 40, r.y + 66), 2)
    gui.line(t.text, (r.x + 40, r.y + 70), (r.right - 40, r.y + 70), 1)

    # ---------------------------------------------------------- 왼쪽: 국호·국기·지도자
    x, w = r.x + 40, 600
    y = r.y + 84
    _label(gui, x, y, "국호", "國號")
    s.name = gui.text_input((x, y + 24, 230, 34), "name", s.name, max_len=10)
    fx = x + 270
    _label(gui, fx, y, "국기", "國旗")
    fr = pygame.Rect(fx, y + 22, 60, 40)
    gui.rect(t.gold, fr.inflate(4, 4))
    draw_flag(gui, fr, s.flag)
    if gui.button((fx + 74, y + 27, 112, 32), "국기 만들기"):
        s.flag_draft = dict(s.flag)
    y += 76
    _label(gui, x, y, "지도자", "君主")
    y += 24
    # 분류 책갈피 탭
    cur_cat = getattr(s, "leader_cat", None)
    if cur_cat is None:
        cur_cat = next((i for i, c in enumerate(LEADER_CATEGORIES) if s.leader in c[2]), 0)
    tx = x
    for i, c in enumerate(LEADER_CATEGORIES):
        tw = measure(c[1], 11, "semibold")[0] + 20
        tr = pygame.Rect(tx, y, tw, 28)
        act = i == cur_cat
        hov = gui.hover(tr)
        gui.rect(t.accent if act else (mix(t.panel_alt, t.text, 0.06) if hov else t.panel_alt), tr, radius=5)
        gui.text(tr.center, c[1], 11, (255, 255, 255) if act else t.muted, "bold" if act else "semibold", anchor="center")
        if hov and gui.clicked and not act:
            gui.clicked = False
            cur_cat = i
        tx += tw + 4
    s.leader_cat = cur_cat
    gui.line(t.accent, (x, y + 28), (x + w, y + 28), 2)
    y += 38
    # 지도자 초상 카드(7열 × 2줄)
    shown = [LEADER_BY_KEY[k] for k in LEADER_CATEGORIES[s.leader_cat][2]] + [LEADER_BY_KEY["cus"]]
    cols, gap = 7, 6
    cw = (w - (cols - 1) * gap) / cols
    pw = int(cw) - 8
    ph = pw * 4 // 3                          # 초상화 칸은 세로 3:4(그림이 잘리지 않게)
    ch = ph + 26
    for i, l in enumerate(shown):
        cx = x + (i % cols) * (cw + gap)
        cy = y + (i // cols) * (ch + gap)
        cr = pygame.Rect(int(cx), int(cy), int(cw), ch)
        sel = s.leader == l["key"]
        hov = gui.hover(cr)
        gui.shadow(cr, 3, 3, 90 if sel else 40)
        gui.rect(t.panel, cr, radius=3)
        pr_ = pygame.Rect(cr.x + 4, cr.y + 4, pw, ph)
        if portrait_path(l["key"]) and l["key"] != "cus":
            draw_portrait(gui, pr_, l["key"], t)
            if not sel and not hov:                 # 고르지 않은 카드는 살짝 바랜 느낌
                fade = pygame.Surface(gui.R(pr_).size, pygame.SRCALPHA)
                fade.fill((*t.panel, 60))
                gui.screen.blit(fade, gui.R(pr_).topleft)
        else:
            gui.rect(mix(t.panel_alt, t.indigo, 0.1), pr_)
            col = mix(t.panel_alt, t.indigo, 0.35)
            if l["key"] == "cus":
                gui.text(pr_.center, "+", 30, col, "bold", anchor="center")
            else:
                gui.circle(col, (pr_.centerx, pr_.y + ph * 0.36), pw * 0.17)
                gui.rect(col, (pr_.centerx - pw * 0.28, pr_.y + ph * 0.58, pw * 0.56, ph * 0.42), radius=12)
        nm = "직접 입력" if l["key"] == "cus" else l["name"]
        gui.text((cr.centerx, cr.bottom - 14), nm, 11 if len(nm) <= 5 else 10, t.text if sel else mix(t.text, t.panel, 0.2),
                 "serif", anchor="center", max_w=cr.w - 4)
        if sel:
            pygame.draw.rect(gui.screen, t.vermilion, gui.R(cr.inflate(4, 4)), max(2, int(2 * gui.u)), border_radius=int(4 * gui.u))
        else:
            pygame.draw.rect(gui.screen, t.border, gui.R(cr), 1, border_radius=int(3 * gui.u))
        if hov:
            gui.tooltip = f"{l['name']}\n버프 {l['buff'][0]}: {l['buff'][1]}\n디버프 {l['debuff'][0]}: {l['debuff'][1]}"
            if gui.clicked:
                gui.clicked = False
                s.leader = l["key"]
    y += 2 * (ch + gap) + 6
    # 고른 지도자: 족자 초상 + 이름 + 버프·디버프 패
    lead = LEADER_BY_KEY[s.leader]
    fr2 = pygame.Rect(x + 8, y + 10, 96, 136)    # 안쪽 초상화 84×112(3:4)
    gui.shadow(fr2, 2, 6, 90)
    gui.rect((60, 78, 94), fr2)
    inner = fr2.inflate(-12, -24)
    inner.y += 1
    draw_portrait(gui, inner, s.leader, t)
    pygame.draw.rect(gui.screen, t.gold_lt, gui.R(inner), 1)
    for yy in (fr2.y - 4, fr2.bottom - 5):
        gui.rect(t.indigo_dk, (fr2.x - 6, yy, fr2.w + 12, 9), radius=4)
        gui.rect(t.gold, (fr2.x - 10, yy + 1, 5, 7), radius=2)
        gui.rect(t.gold, (fr2.right + 5, yy + 1, 5, 7), radius=2)
    dx = x + 128
    if s.leader == "cus":
        gui.text((dx, y + 4), "지도자 이름", 12, t.muted, "semibold")
        s.custom_name = gui.text_input((dx + 80, y, 200, 32), "custom", s.custom_name, max_len=10)
    else:
        gui.text((dx, y), lead["name"], 22, t.text, "title")
    cat = next((c[1] for c in LEADER_CATEGORIES if lead["key"] in c[2]), "직접 입력")
    gui.text((dx, y + 36), cat, 11, t.muted, "semibold")
    for j, (kind, (nm, desc), col) in enumerate((("버프", lead["buff"], t.good), ("디버프", lead["debuff"], t.bad))):
        tg = pygame.Rect(dx, y + 56 + j * 46, w - (dx - x), 40)
        gui.rect(mix(t.panel, col, 0.08), tg, radius=3)
        gui.rect(col, (tg.x, tg.y, 4, tg.h))
        kr = gui.text((tg.x + 12, tg.y + 4), kind, 11, col, "bold")
        gui.text((kr.right + 8, tg.y + 3), nm, 13, t.text, "serif", max_w=tg.right - kr.right - 18)
        gui.text((tg.x + 12, tg.y + 22), desc, 11, t.text, max_w=tg.w - 20)

    # 가운데 세로 구분선
    mx_ = r.x + 655
    gui.line(mix(t.gold, t.panel, 0.2), (mx_, r.y + 84), (mx_, r.bottom - 90))
    gui.polygon(t.gold, [(mx_, r.y + 380), (mx_ + 5, r.y + 386), (mx_, r.y + 392), (mx_ - 5, r.y + 386)])

    # ---------------------------------------------------------- 오른쪽: 천하의 형세
    x2 = r.x + 676
    w2 = r.right - 40 - x2
    y = r.y + 84
    _label(gui, x2, y, "천하의 형세", "天下形勢")
    y += 30
    gui.text((x2, y + 7), "적 세력", 13, t.text, "semibold")
    s.n_enemies = gui.stepper((x2 + 64, y, 120, 30), s.n_enemies, 1, C.MAX_ENEMIES)
    gui.text((x2 + 192, y + 7), "나라", 12, t.muted, "semibold")
    gui.text((x2 + w2 - 160, y + 7), "시드", 13, t.text, "semibold")
    s.seed = gui.text_input((x2 + w2 - 120, y, 120, 30), "seed", s.seed, max_len=9)
    y += 42
    gui.text((x2, y), "난이도", 13, t.text, "semibold")
    d = C.DIFFICULTIES[s.difficulty]
    gui.text((x2 + w2, y + 2), f"AI 인구 성장률 ×{d[1]:.2f} · 생산 수입 ×{d[2]:.2f}", 11, t.muted, anchor="topright")
    s.difficulty = gui.segmented((x2, y + 22, w2, 30), [d[0] for d in C.DIFFICULTIES], s.difficulty, size=11)
    y += 62
    gui.text((x2, y), "전장의 안개", 13, t.text, "semibold")
    s.fog = gui.segmented((x2, y + 22, w2, 30), C.FOG_MODES, s.fog, size=12)
    y += 62
    gui.text((x2, y), "승리 조건", 13, t.text, "semibold")
    gui.text((x2 + w2, y + 2), "켠 조건으로만 승부가 납니다", 11, t.muted, anchor="topright")
    y += 22
    keys = list(C.VICTORY_TYPES)
    vw = (w2 - (len(keys) - 1) * 6) / len(keys)
    short = {"time": "시간승리"}
    for i, k in enumerate(keys):
        vr = pygame.Rect(int(x2 + i * (vw + 6)), y, int(vw), 32)
        on = s.victories[k]
        hov = gui.hover(vr)
        if on:
            gui.rect(t.accent, vr, radius=3)
            pygame.draw.rect(gui.screen, t.gold, gui.R(vr), 1, border_radius=int(3 * gui.u))
            gui.lines(t.gold_lt, False, [(vr.x + 8, vr.centery), (vr.x + 12, vr.centery + 4), (vr.x + 18, vr.centery - 4)], 2)
        else:
            gui.rect(t.panel, vr, radius=3)
            pygame.draw.rect(gui.screen, t.border, gui.R(vr), 1, border_radius=int(3 * gui.u))
        gui.text((vr.x + 23, vr.centery), short.get(k, C.VICTORY_TYPES[k]), 12,
                 (255, 255, 255) if on else mix(t.text, t.panel, 0.45), "serif", anchor="midleft", max_w=vr.w - 26)
        if hov:
            gui.tooltip = VICTORY_TIPS.get(k, C.VICTORY_TYPES[k])
            if gui.clicked:
                gui.clicked = False
                s.victories[k] = not on
    y += 44
    on = s.victories.get("time", False)
    gui.text((x2, y + 2), f"시간 종료  {s.max_turns}턴 ({s.max_turns / C.TURNS_PER_YEAR:g}년)", 12,
             t.text if on else t.muted, "semibold")
    v, _ = gui.slider((x2 + 200, y + 4, w2 - 206, 16), s.max_turns, C.TIME_VICTORY_MIN, C.TIME_VICTORY_MAX,
                      C.TIME_VICTORY_STEP, "max_turns", enabled=on)
    s.max_turns = int(v)
    y += 32
    _label(gui, x2, y, "시작 지역", "封地")
    y += 26
    # 내 시작 지역: 지도에서 선택 · 무작위
    pr2 = pygame.Rect(x2, y, w2, 32)
    gui.rect(mix(t.panel, t.accent, 0.07), pr2, radius=3)
    pygame.draw.rect(gui.screen, t.accent, gui.R(pr2), 1, border_radius=int(3 * gui.u))
    draw_flag(gui, (pr2.x + 8, pr2.y + 8, 24, 16), s.flag)
    gui.text((pr2.x + 40, pr2.centery), "내 나라", 11, t.accent if not t.dark else t.gold_lt, "bold", anchor="midleft")
    st_name = app.world.regions[s.start].name if s.start else "무작위"
    if s.start and app.world.regions[s.start].island == "무연륙 섬":
        st_name += " (섬 도전)"             # 무작위로는 나오지 않는 섬 시작
    gui.text((pr2.x + 92, pr2.centery), st_name, 13, t.text, "bold", anchor="midleft", max_w=w2 - 270)

    def go_pick(scene):
        app.scene = scene
        app.pick_popup = None
        app.map.z = 1.0
        app.map.cx, app.map.cy = 280, 520
        app.map.invalidate()
    if gui.button((pr2.right - 170, pr2.y + 4, 104, 24), "지도에서 선택", size=12):
        go_pick("pick_start")
    if gui.button((pr2.right - 60, pr2.y + 4, 54, 24), "무작위", size=12):
        s.start = None
    y += 40
    # 미니맵 + 적 국가 목록
    fit_ai_slots(s)
    mm = pygame.Rect(x2, y, 130, 176)
    at = _minimap(app, mm)
    pygame.draw.rect(gui.screen, mix(t.gold, t.text, 0.2), gui.R(mm), 1)
    if gui.hover(mm):
        gui.tooltip = "누르면 지도에서 내 시작 지역을 고릅니다"
        if gui.clicked:
            gui.clicked = False
            go_pick("pick_start")
    u = gui.u
    gui.screen.set_clip(gui.R(mm))
    for i in range(s.n_enemies):
        rid = s.ai_starts[i]
        if rid:
            px, py = at(rid)
            col = hex2rgb(C.FACTION_COLORS[(i + 1) % len(C.FACTION_COLORS)])
            pygame.draw.circle(gui.screen, col, (int(px), int(py)), max(3, int(4 * u)))
            pygame.draw.circle(gui.screen, (247, 241, 227), (int(px), int(py)), max(3, int(4 * u)), 1)
    if s.start:
        px, py = at(s.start)
        pc = hex2rgb(player_color(s.flag) or C.FACTION_COLORS[0])
        pts = _star_poly(px, py, 5.5 * u)
        pygame.draw.polygon(gui.screen, pc, pts)
        pygame.draw.polygon(gui.screen, (247, 241, 227), pts, 1)
    gui.screen.set_clip(None)
    ax = mm.right + 10
    aw = x2 + w2 - ax
    two = s.n_enemies > 7
    colw = (aw - 6) / 2 if two else aw
    for i in range(s.n_enemies):
        col_i, row_i = (i // 8, i % 8) if two else (0, i)
        rr = pygame.Rect(int(ax + col_i * (colw + 6)), y + row_i * 22, int(colw), 20)
        cur = s.ai_leaders[i]
        lab = LEADER_BY_KEY[cur]["name"] if cur else "무작위"
        rid = s.ai_starts[i]
        place = app.world.regions[rid].name if rid else "무작위 지역"
        hov = gui.hover(rr)
        gui.rect(mix(t.panel, t.panel_alt, 0.8 if hov else 0.4), rr, radius=3)
        gui.rect(hex2rgb(C.FACTION_COLORS[(i + 1) % len(C.FACTION_COLORS)]), (rr.x + 5, rr.y + 5, 14, 10))
        gui.text((rr.x + 24, rr.centery), f"AI {i + 1}", 10, t.muted, "bold", anchor="midleft")
        nr_ = gui.text((rr.x + 56, rr.centery), lab, 12, t.text, "serif", anchor="midleft", max_w=colw - 60 if two else 100)
        if not two:
            gui.text((rr.right - 6, rr.centery), place, 10, t.muted if not rid else t.text, "semibold", anchor="midright",
                     max_w=rr.right - nr_.right - 14)
        if hov:
            gui.tooltip = f"AI {i + 1}: {lab}\n{place}\n누르면 지도자를 고릅니다"
            if gui.clicked:
                gui.clicked = False
                s.ai_pick = i                        # 지도자 고르기 창
    yb = y + (8 if two else max(1, s.n_enemies)) * 22 + 4
    yb = max(yb, y + 150)
    for j, (lab, tip) in enumerate((("모두 무작위 지도자", "기존 규칙대로 남은 지도자 가운데 무작위로 정합니다"),
                                    ("모두 무작위 지역", "기존 규칙(수도끼리 6칸 이상 등)대로 시작 지역을 정합니다.\n"
                                                      "내 시작 지역을 골랐으면 거기에 맞춰서"),
                                    ("지도에서 고르기", "지도에서 적 국가마다 시작 지역을 고릅니다"))):
        bw_ = (aw - 8) / 3
        br = pygame.Rect(int(ax + j * (bw_ + 4)), yb, int(bw_), 22)
        hov = gui.hover(br)
        gui.text(br.center, lab, 11, t.vermilion if hov else (t.accent if not t.dark else t.gold_lt), "bold", anchor="center",
                 max_w=br.w)
        gui.line(t.accent if not hov else t.vermilion, (br.x + 6, br.bottom), (br.right - 6, br.bottom))
        if hov:
            gui.tooltip = tip
            if gui.clicked:
                gui.clicked = False
                if j == 0:
                    random_ai_leaders(s)
                elif j == 1:
                    random_ai_starts(app)
                else:
                    go_pick("pick_ai")
                    s.ai_place = 0
    # 하단 버튼
    by = r.bottom - 74
    gui.line(mix(t.gold, t.panel, 0.2), (r.x + 40, by - 8), (r.right - 40, by - 8))
    if gui.button((r.right - 512, by + 6, 116, 44), "이전", size=15, weight="title"):
        app.scene = "title"
        return
    if gui.button((r.right - 386, by + 6, 116, 44), "불러오기", size=15, weight="title"):
        app.open_slots("load")
    if gui.button((r.right - 260, by, 220, 56), "건국하기", "seal", size=20, weight="title",
                  enabled=any(s.victories.values())):
        start_from_setup(app)


FLAG_TARGETS = (("c1", "배경 색 1"), ("c2", "배경 색 2"), ("ec", "문양 색 1"), ("ec2", "문양 색 2"))
FLAG_TARGET_USED = {"c1": lambda fl: True, "c2": FL.uses_c2, "ec": FL.uses_ec, "ec2": FL.uses_ec2}


def draw_flag_editor(app):
    """국기 만들기: 배경 무늬(5×2)·문양(6×4)·색(색조·채도·명도 슬라이더 + RGB 0~255 직접 입력), 또는 역사 국기."""
    gui = app.gui
    t = app.theme
    s = app.setup
    fl = s.flag_draft
    preset = fl.get("preset")
    r = modal_frame(app, 960, 660, "국기 만들기")
    x, y = r.x + 24, r.y + 64
    draw_flag(gui, (x, y, 300, 200), fl)
    y += 220
    # 색 고르기 대상: 단색 배경이면 배경 색 2, 한 색 문양이면 문양 색 2(문양 없음이면 문양 색 1·2)는 꺼진다
    used = [not preset and FLAG_TARGET_USED[k](fl) for k, _ in FLAG_TARGETS]
    if not used[s.flag_target]:
        s.flag_target = 0
    tw = (300 - 3 * 4) / 4
    for i, (k, lb) in enumerate(FLAG_TARGETS):
        if gui.button((x + i * (tw + 4), y, tw, 32), lb, selected=used[i] and s.flag_target == i, size=11,
                      enabled=used[i]):
            s.flag_target = i
    ck = FLAG_TARGETS[s.flag_target][0]
    col = list(fl[ck])
    y += 46
    gui.rect(tuple(col), (x, y, 44, 30), radius=4)
    gui.rect(t.border, (x, y, 44, 30), 1, radius=4)
    gui.text((x + 56, y + 15), "역사 국기는 색을 바꿀 수 없습니다" if preset else FL.rgb2hex(col),
             13 if preset else 18, t.muted if preset else t.text, "bold", anchor="midleft")
    y += 42
    # 색조·채도·명도 슬라이더(색조는 스펙트럼, 채도는 회색→색, 명도는 검은색→흰색)
    hs = s.__dict__.setdefault("flag_hsl", {})
    h, sa, li = hs[ck] if ck in hs and hsl_rgb(*hs[ck]) == tuple(col) else rgb_hsl(col)
    rows = (("색조", h, 360, [hsl_rgb(k * 360 / 36, 100, 50) for k in range(37)]),
            ("채도", sa, 100, [hsl_rgb(h, k * 100 / 16, li) for k in range(17)]),
            ("명도", li, 100, [(round(k * 255 / 16),) * 3 for k in range(17)]))
    vals = []
    for i, (lab, v, hi, track) in enumerate(rows):
        gui.text((x, y + i * 36 + 8), lab, 13, t.muted if preset else t.text, "semibold", anchor="midleft")
        nv, _ = gui.slider((x + 44, y + i * 36, 256, 16), v, 0, hi, 1, f"flag_{ck}_hsl{i}", enabled=not preset,
                           track=track)
        vals.append(int(nv))
    if vals != [h, sa, li] and not preset:
        hs[ck] = tuple(vals)
        col = list(hsl_rgb(*vals))
    else:
        hs[ck] = (h, sa, li)
    y += 3 * 36 + 4
    # RGB 0~255 직접 입력(슬라이더를 움직이면 바로 따라 바뀌고, 입력하고 Enter면 슬라이더에 반영)
    cw3 = (300 - 2 * 8) / 3
    for i, ch in enumerate("RGB"):
        cx = x + i * (cw3 + 8)
        gui.text((cx, y + 15), ch, 13, t.muted, "bold", anchor="midleft")
        if not preset:
            nv = _num_input(gui, s, (cx + 18, y, cw3 - 18, 30), f"flagnum_{ck}_{i}", col[i])
            if nv != col[i]:
                col[i] = nv
                hs[ck] = rgb_hsl(col)
        else:
            gui.text((cx + cw3 - 4, y + 15), str(col[i]), 13, t.muted, anchor="midright")
    y += 36
    fl[ck] = tuple(col)
    y += 6
    gui.text((x, y), "역사 국기", 14, weight="bold")
    y += 24
    pw = (300 - 3 * 8) / 4
    for i, (pk, pn) in enumerate(FL.PRESETS):
        cell = pygame.Rect(x + i * (pw + 8), y, pw, 52)
        if gui.button(cell, "", selected=preset == pk, tooltip=pn):
            fl["preset"] = pk
        draw_flag(gui, cell.inflate(-10, -12), {"preset": pk})
    # 오른쪽: 배경 무늬·문양 고르기(현재 색으로 미리보기). 고르면 역사 국기는 해제된다.
    x2 = r.x + 360
    rw = r.right - 24 - x2
    y2 = r.y + 64
    gui.text((x2, y2), "배경", 14, weight="bold")
    y2 += 24
    gap = 10
    cw, chh = (rw - 4 * gap) / 5, 64
    for i, (bk, bn) in enumerate(FL.BACKGROUNDS):
        cell = pygame.Rect(x2 + (i % 5) * (cw + gap), y2 + (i // 5) * (chh + gap), cw, chh)
        if gui.button(cell, "", selected=not preset and fl["bg"] == bk, tooltip=bn):
            fl["bg"] = bk
            fl.pop("preset", None)
        draw_flag(gui, cell.inflate(-14, -12), {**fl, "preset": None, "em": "none", "bg": bk})
    y2 += 2 * (chh + gap) + 10
    gui.text((x2, y2), f"문양 · {dict(FL.EMBLEMS)[fl['em']]}", 14, weight="bold")
    y2 += 24
    gap = 8
    cw, chh = (rw - 5 * gap) / 6, 58
    for i, (ek, en) in enumerate(FL.EMBLEMS):
        cell = pygame.Rect(x2 + (i % 6) * (cw + gap), y2 + (i // 6) * (chh + gap), cw, chh)
        if gui.button(cell, "", selected=not preset and fl["em"] == ek, tooltip=en):
            fl["em"] = ek
            fl.pop("preset", None)
        draw_flag(gui, cell.inflate(-12, -10), {**fl, "preset": None, "bg": "solid", "em": ek})
    # 하단 버튼
    if gui.button((r.x + 24, r.bottom - 56, 110, 38), "무작위"):
        s.flag_draft = FL.random_flag()         # AI 국기 규칙을 따른다
    if gui.button((r.right - 220, r.bottom - 56, 92, 38), "취소"):
        s.flag_draft = None
        return
    if gui.button((r.right - 118, r.bottom - 56, 94, 38), "확인", "primary"):
        s.flag = FL.normalize(s.flag_draft)
        s.flag_draft = None
        return
    for k in list(gui.keys):
        if k.key == pygame.K_ESCAPE:
            s.flag_draft = None
            gui.keys.remove(k)


def draw_ai_leader_picker(app):
    """적 지도자 고르기: 분류별 전체 목록에서 한 번에 고른다. 플레이어·다른 칸이 이미 고른 지도자는 비활성."""
    gui = app.gui
    t = app.theme
    s = app.setup
    i = s.ai_pick
    cur = s.ai_leaders[i] if i < len(s.ai_leaders) else None
    taken = {s.leader} | {k for j, k in enumerate(s.ai_leaders[: s.n_enemies]) if j != i and k}
    cols, bw, bh, gap = 6, 150, 34, 6
    rows = sum((len(ks) + cols - 1) // cols for _, _, ks in LEADER_CATEGORIES)
    h = 64 + len(LEADER_CATEGORIES) * 28 + rows * (bh + gap) + 76
    r = modal_frame(app, 48 + cols * (bw + gap) - gap, h, f"AI {i + 1} 지도자 고르기")
    x, y = r.x + 24, r.y + 60
    for _, title, keys in LEADER_CATEGORIES:
        gui.text((x, y), title, 13, t.muted, "semibold")
        y += 24
        for n, k in enumerate(keys):
            l = LEADER_BY_KEY[k]
            cell = (x + (n % cols) * (bw + gap), y + (n // cols) * (bh + gap), bw, bh)
            mine = k == s.leader
            tip = (f"{l['name']}\n버프 {l['buff'][0]}: {l['buff'][1]}\n"
                   f"디버프 {l['debuff'][0]}: {l['debuff'][1]}")
            if k in taken:
                tip = ("내 지도자입니다." if mine else "다른 AI가 이미 골랐습니다.") + "\n" + tip
            if gui.button(cell, l["name"], selected=k == cur, enabled=k not in taken,
                          size=13 if len(l["name"]) <= 7 else 11, tooltip=tip):
                s.ai_leaders[i] = k
                s.ai_pick = None
                return
        y += ((len(keys) + cols - 1) // cols) * (bh + gap) + 4
    if gui.button((r.x + 24, r.bottom - 56, 140, 38), "무작위", selected=cur is None,
                  tooltip="게임을 시작할 때 남은 지도자 가운데 무작위로 정합니다"):
        s.ai_leaders[i] = None
        s.ai_pick = None
        return
    if gui.button((r.right - 124, r.bottom - 56, 100, 38), "닫기"):
        s.ai_pick = None
        return
    for k in list(gui.keys):
        if k.key == pygame.K_ESCAPE:
            s.ai_pick = None
            gui.keys.remove(k)


def _unique_ai_leaders(s):
    """지정한 AI 지도자 중 플레이어·앞 칸과 겹치는 것은 빼서(무작위로) 같은 지도자가 둘 나오지 않게 한다."""
    out, used = [], {s.leader}
    for k in (s.ai_leaders or [])[: s.n_enemies]:
        if k and k not in used:
            out.append(k)
            used.add(k)
        else:
            out.append(None)                     # 칸 순서를 지킨다(시작 지역과 짝): 빈 칸은 무작위
    return out


def fit_ai_slots(s):
    """적 국가 칸 수(지도자·시작 지역 목록)를 적 세력 수에 맞춘다."""
    s.ai_leaders = (list(s.ai_leaders) + [None] * s.n_enemies)[: max(s.n_enemies, len(s.ai_leaders))]
    s.ai_starts = (list(s.ai_starts) + [None] * s.n_enemies)[: max(s.n_enemies, len(s.ai_starts))]


def random_ai_leaders(s):
    """모두 무작위 지도자: 내 지도자를 뺀 지도자 가운데 겹치지 않게 무작위(게임 시작 때와 같은 규칙)."""
    fit_ai_slots(s)
    pool = [l["key"] for l in LEADERS if l["key"] not in ("cus", s.leader)]
    random.shuffle(pool)
    for i in range(s.n_enemies):
        s.ai_leaders[i] = pool.pop() if pool else None


def random_ai_starts(app):
    """모두 무작위 지역: 게임 시작 때와 같은 규칙(수도끼리 육상 6칸 이상, 황해·강원 7칸, 무연륙 섬 제외).
    내 시작 지역을 골랐으면 거기에 맞춰서, 안 골랐으면 적 국가끼리만 규칙에 맞게(내 수도는 시작할 때 거기에 맞춰 정한다)."""
    from ..game import pick_starts
    s = app.setup
    fit_ai_slots(s)
    n = s.n_enemies
    if s.start:
        s.ai_starts[:n] = pick_starts(app.world, random.Random(), 1 + n, [s.start] + [None] * n)[1:]
    else:
        s.ai_starts[:n] = pick_starts(app.world, random.Random(), n, [None] * n)
    app.map.invalidate()


def start_from_setup(app):
    s = app.setup
    if not any(s.victories.values()):
        s.victories["conquest"] = True
    seed = int(s.seed) if s.seed.strip().isdigit() else random.randrange(1_000_000)
    settings = Settings(
        n_enemies=s.n_enemies, difficulty=s.difficulty, fog=s.fog,
        victories=tuple(k for k, v in s.victories.items() if v), player_leader=s.leader,
        player_leader_name=(s.custom_name.strip() or "이름 없는 지도자") if s.leader == "cus" else "",
        player_name=s.name.strip() or "대한", player_start=s.start, player_flag=dict(s.flag),
        ai_leaders=_unique_ai_leaders(s), ai_starts=list(s.ai_starts[: s.n_enemies]), seed=seed, max_turns=s.max_turns)
    app.start_game(settings)


def josa_euro(word: str) -> str:
    """받침이 있으면(ㄹ 제외) '으로', 없으면 '로'."""
    ch = word[-1]
    if "가" <= ch <= "힣":
        jong = (ord(ch) - 0xAC00) % 28
        return "로" if jong in (0, 8) else "으로"
    return "(으)로"


def draw_start_popup(app, rid):
    """지도에서 지역을 고르면 뜨는 시작 정보 팝업."""
    from .. import rules as R
    from .mapview import TERRAIN_COLORS
    gui = app.gui
    t = app.theme
    w = app.world
    info = w.regions[rid]
    sw, sh = app.gui.size()
    ph = min(500, sh - 40)
    r = modal_frame(app, 600, ph)
    x, cw = r.x + 28, r.w - 56
    gui.text((x, r.y + 20), info.name, 22, weight="bold")
    sub = f"{info.rtype} · 조선 {info.do8}도 · {'남한' if info.ns == '남' else ('북한' if info.ns == '북' else '남북 병합')}"
    if info.island:
        sub += f" · {info.island}"
    gui.text((x, r.y + 54), sub, 13, t.muted)
    y = r.y + 86
    out = R.region_output(info.pop0, info.farm, info.fishery, info.factory, info.bank, False)
    food = R.food_output(info.farm, info.fishery)
    half = (cw - 20) // 2

    def stat(col, row, k, v, vc=None):
        xx = x + col * (half + 20)
        yy = y + row * 24
        gui.text((xx, yy), k, 13, t.muted)
        gui.text((xx + half, yy), v, 13, vc or t.text, "semibold", anchor="topright")

    stat(0, 0, "인구", f"{info.pop0:,.1f}만 명")
    stat(1, 0, "산출(GDP)", f"{out:,.0f} /턴")
    stat(0, 1, "세수(세율 10%)", f"{out * 0.1:,.0f} /턴")
    stat(1, 1, "시작 자금", f"{C.START_MONEY:,}")
    bal = food - info.pop0
    stat(0, 2, "식량 생산 / 소비", f"{food:,.0f} / {info.pop0:,.0f}")
    stat(1, 2, "식량 수지", f"{bal:+,.0f} /턴", t.good if bal >= 0 else t.bad)
    y += 3 * 24 + 8

    def chips(title, items):
        nonlocal y
        gui.text((x, y), title, 12, t.muted, "semibold")
        y += 20
        cx = x
        for c in items or ["없음"]:
            cwid = measure(c, 12)[0] + 16
            if cx + cwid > x + cw and cx > x:
                cx = x
                y += 26
            rr = pygame.Rect(cx, y, cwid, 22)
            gui.rect(t.panel_alt, rr, radius=11)
            gui.text(rr.center, c, 12, anchor="center")
            cx += cwid + 6
        y += 30

    blds = [f"{nm} {lv}단계" for nm, lv in (("농장", info.farm), ("어장", info.fishery), ("공장", info.factory),
                                             ("은행", info.bank)) if lv]
    if info.specialty:
        blds.append("특산물 시설 1단계")
    if info.start_port:
        blds.append("항구")
    chips("건물", blds)
    res = []
    if info.oil:
        res.append(f"정유 석유 {info.oil}/턴")
    if info.coal:
        res.append(f"탄광 석탄 {info.coal}/턴")
    if info.power_source:
        from .panels import power_text
        res.append(power_text(info))
    if info.specialty:
        res += [f"특산물: {sp}" for sp in info.specialties]   # 두 종류면 따로 표기
    chips("자원·특산물", res)
    geo = [f"인접 지역 {len(w.land_adj[rid])}곳"]
    if info.coastal:
        geo.append("해안: " + ", ".join(w.seas[s].name for s in info.seas))
    units = "보병 1" + (" · 상륙함 1" if info.island == "무연륙 섬" else "")
    geo.append(f"시작 병력 {units}")
    chips("지리·병력", geo)
    terr = [(n, w.terrain_between(rid, n)) for n in sorted(w.land_adj[rid])]
    terr = [(n, tr) for n, tr in terr if tr]
    if terr:
        gui.text((x, y), "지형 경계 (넘어오는 공격 ×0.9)", 12, t.muted, "semibold")
        y += 20
        for n, tr in terr[:4]:
            gui.line(TERRAIN_COLORS[tr["kind"]], (x, y + 9), (x + 16, y + 9), 4)
            gui.text((x + 24, y), f"{w.regions[n].name} · {tr['label']}({tr['name']})", 12, max_w=cw - 24)
            y += 20
        if len(terr) > 4:
            gui.text((x + 24, y), f"외 {len(terr) - 4}곳", 12, t.muted)
    bw = (cw - 12) // 2
    by = r.bottom - 68
    if gui.button((x, by, bw, 46), f"{info.short}{josa_euro(info.short)} 시작", "primary", size=15, weight="bold"):
        app.setup.start = rid
        app.setup.ai_starts = [None if a == rid else a for a in app.setup.ai_starts]   # 적 국가와 겹치면 그 칸은 무작위로
        app.pick_popup = None
        start_from_setup(app)
        return
    if gui.button((x + bw + 12, by, bw, 46), "이전", size=15):
        app.pick_popup = None            # 팝업만 닫고 지도로 돌아가 다른 지역 고르기
        return
    for k in gui.keys:
        if k.key == pygame.K_ESCAPE:   # Esc: 팝업만 닫고 다른 지역 고르기
            app.pick_popup = None


# ------------------------------------------------------------------ 정치체제
def draw_government(app):
    gui = app.gui
    t = app.theme
    r = modal_frame(app, 760, 600, "정치체제를 고르세요")
    gui.text((r.x + 24, r.y + 52), "지도자 효과와 곱으로 합산됩니다. 한 번 정하면 바꿀 수 없습니다.", 13, t.muted)
    y = r.y + 84
    from ..leaders import banned_govs
    banned = banned_govs(app.game.player.leader)
    for gdef in GOVERNMENTS:
        row = pygame.Rect(r.x + 24, y, r.w - 48, 64)
        if gdef["key"] in banned:
            gui.rect(t.panel_alt, row, radius=8)
            gui.text((row.x + 16, row.y + 10), gdef["name"], 16, t.muted, weight="bold")
            lead = LEADER_BY_KEY[app.game.player.leader]
            gui.text((row.x + 16, row.y + 36), f"선택 불가 — {lead['debuff'][0]}", 12, t.bad)
            y += 70
            continue
        hov = gui.hover(row)
        gui.rect(t.panel_alt if hov else t.panel, row, radius=8)
        gui.rect(t.border, row, 1, radius=8)
        gui.text((row.x + 16, row.y + 10), gdef["name"], 16, weight="bold")
        if gov_buff_scale(app.game.player.leader) != 1.0 and gdef.get("buff_keys"):
            lead = LEADER_BY_KEY[app.game.player.leader]
            k = gov_buff_scale(app.game.player.leader)
            gui.text((row.x + 16, row.y + 36), f"＋ {gdef['buff'][1]} ({lead['debuff'][0]}: {k:.0%})", 12, t.good)
        else:
            gui.text((row.x + 16, row.y + 36), f"＋ {gdef['buff'][1]}", 12, t.good)
        gui.text((row.x + 330, row.y + 36), f"－ {gdef['debuff'][1]}", 12, t.bad)
        if hov and gui.clicked:
            gui.clicked = False
            app.game.set_player_government(gdef["key"])
            app.scene = "main"
            app.changed()
            app.toast(f"{gdef['name']}을(를) 채택했습니다. 첫 턴입니다 — 지역을 눌러 [행동]에서 슬롯을 지정하세요.")
        y += 70


# ------------------------------------------------------------------ 모달 분기
def draw_active_modal(app):
    name = app.active_modal()
    if name == "dialogue":
        draw_dialogue(app)
    elif name == "rebellion":
        draw_rebellion(app)
    elif name == "proposal":
        draw_proposal(app)
    elif name == "diplomacy":
        draw_diplomacy(app)
    elif name == "ranking":
        draw_ranking(app)
    elif name == "log":
        draw_log(app)
    elif name == "help":
        draw_help(app)
    elif name == "gameover":
        draw_gameover(app)
    elif name == "specialty":
        draw_specialty(app)
    elif name == "saveslots":
        draw_save_slots(app)
    elif name == "pause":
        draw_pause(app)
    elif name == "battle":
        draw_battle(app)


def _units_text(units):
    return ", ".join(f"{C.UNITS[k]['name']} {n}" for k in C.UNIT_ORDER for n in [units.get(k, 0)] if n) or "없음"


def draw_battle(app):
    """전투 확인: 양측 병력, 적용되는 버프·디버프, 예상 결과 → [전투] / [취소]."""
    g = app.game
    gui = app.gui
    t = app.theme
    st = app.modal[1]
    army = g.armies.get(st["army"])
    node = st["node"]
    if not army or not g.hostile_units_at(army.owner, node):
        close(app)
        return
    can_surprise = any(army.units.get(k) for k in C.SURPRISE_UNITS) and not g.mods(army.owner).value("no_surprise")
    if not can_surprise:
        st["mode"] = "assault"
    bd = g.battle_breakdown(army, node, st["mode"])
    if bd is None:
        close(app)
        return
    n_oc = len(bd["outcomes"])
    box_h = 112 + 20 * max(1, min(6, max(len(bd["att_factors"]), len(bd["def_factors"]))))
    r = modal_frame(app, 820, box_h + 124 + n_oc * 118 + 76,
                    f"전투 확인 — {app.world.node_name(army.loc)} → {app.world.node_name(node)}")
    pv = bd["preview"]
    if can_surprise:
        idx = gui.segmented((r.right - 244, r.y + 18, 220, 30), ["돌격", "기습"], 0 if st["mode"] == "assault" else 1,
                            size=12)
        st["mode"] = "assault" if idx == 0 else "surprise"
    # 양측 체력: 지금 남은 체력 / 가득 찬 체력
    att_hp = sum(army.hp_left(k) for k in bd["att_units"] if k in army.units)
    att_max = sum(C.UNITS[k]["hp"] * n for k, n in bd["att_units"].items())
    def_max = sum(C.UNITS[k]["hp"] * n for u in bd["def_units"].values() for k, n in u.items())
    def_hp = pv["def_hp"]
    colw = (r.w - 72) / 2
    for i, (title, units_txt, val, factors, color, hp, mx) in enumerate((
            (f"공격 · {g.fname(army.owner)}", _units_text(bd["att_units"]), f"공격력 {pv['A']:,.1f}",
             bd["att_factors"], t.accent, att_hp, att_max),
            ("방어 · " + ", ".join(g.fname(o) for o in bd["def_units"]),
             " / ".join(_units_text(u) for u in bd["def_units"].values()), f"방어력 {pv['D']:,.1f}",
             bd["def_factors"], t.bad, def_hp, def_max))):
        x = r.x + 24 + i * (colw + 24)
        y = r.y + 64
        gui.rect(t.panel_alt, (x, y, colw, box_h), radius=10)
        gui.text((x + 14, y + 10), title, 14, color, "bold", max_w=colw - 28)
        y = gui.wrap((x + 14, y + 34), units_txt, colw - 28, 13)
        gui.text((x + 14, y + 2), val, 16, weight="bold")
        gui.text((x + colw - 14, y + 4), f"체력 {hp:,.0f} / {max(hp, mx):,.0f}", 13, t.text, "semibold",
                 anchor="topright")
        y += 30
        gui.text((x + 14, y), "적용 보정", 12, t.muted, "semibold")
        y += 20
        if not factors:
            gui.text((x + 14, y), "없음", 12, t.muted)
        for label, mult in factors[:6]:
            good = mult > 1
            gui.text((x + 14, y), label, 12, max_w=colw - 100)
            gui.text((x + colw - 14, y), f"×{mult:.2f}", 12, t.good if good else t.bad, "semibold", anchor="topright")
            y += 20
    # 예상 결과: 양측 체력 막대(남은 체력 · 예상 피해 · 피해 뒤 남는 체력)와 생존 여부
    y = r.y + 64 + box_h + 14
    gui.text((r.x + 24, y), "예상 결과 (무작위 ±15%)", 14, weight="bold")
    lx = r.right - 24
    for lab, c in (("이미 잃은 체력", t.panel), ("예상 피해", t.warn), ("피해 뒤 남는 체력", t.muted)):
        tw = measure(lab, 11)[0]
        gui.text((lx, y + 9), lab, 11, t.muted, anchor="midright")
        lx -= tw + 18
        gui.rect(c, (lx, y + 3, 12, 12), radius=2)
        gui.rect(t.border, (lx, y + 3, 12, 12), 1, radius=2)
        lx -= 12
    y += 26
    for oc in bd["outcomes"]:
        row = pygame.Rect(r.x + 24, y, r.w - 48, 110)
        gui.rect(t.panel_alt, row, radius=8)
        gui.text((row.x + 12, row.y + 8), oc["label"], 13, weight="semibold")
        res = "적 전멸 → 진입·점령" if oc["capture"] else "적이 남음 → 진입 못 함"
        gui.text((row.right - 12, row.y + 8), res, 13, t.good if oc["capture"] else t.warn, "bold", anchor="topright")
        for j, (who, hp, mx, dmg, lost, col) in enumerate((
                ("아군", att_hp, att_max, oc["att_dmg"], oc["att_lost"], t.accent),
                ("적군", def_hp, def_max, oc["def_dmg"], oc["def_lost"], t.bad))):
            by = row.y + 34 + j * 36
            _hp_bar(gui, t, (row.x + 64, by, row.w - 380, 14), hp, max(hp, mx), dmg, col)
            gui.text((row.x + 12, by + 7), who, 13, col, "bold", anchor="midleft")
            left = max(0.0, hp - dmg)
            alive = left > 0.05 * max(1.0, hp) and not (j == 1 and oc["capture"])
            gui.text((row.right - 300, by + 7), f"{hp:,.0f} − {dmg:,.0f} → {left:,.0f}", 12, t.text, "semibold",
                     anchor="midleft")
            gui.text((row.right - 12, by + 7), ("생존" if alive else "전멸") +
                     (f" · 손실 {_units_text(lost)}" if lost else " · 손실 없음"), 12,
                     t.good if (alive if j == 0 else not alive) else t.bad, "semibold", anchor="midright", max_w=170)
        y += 118
    if gui.button((r.right - 264, r.bottom - 60, 110, 42), "취소"):
        close(app)
        return
    fight = gui.button((r.right - 144, r.bottom - 60, 120, 42), "전투", "danger", size=15, weight="bold")
    for k in list(gui.keys):
        if k.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and not gui.focus:
            gui.keys.remove(k)                   # Enter = [전투](턴 종료로 넘어가지 않게)
            fight = True
    if fight:
        ok, msg = g.order_army(army.id, node, st["mode"])
        app.attack_mode = st["mode"]
        close(app)
        app.toast(msg if isinstance(msg, str) else str(msg), None if ok else t.bad)
    for k in list(gui.keys):
        if k.key == pygame.K_ESCAPE:
            gui.keys.remove(k)
            close(app)


def _hp_bar(gui, t, rect, hp, mx, dmg, color):
    """체력 막대: [피해 뒤 남는 체력(진영 색) | 예상 피해(주황) | 이미 잃은 체력(빈칸)]."""
    r = pygame.Rect(rect)
    gui.rect(t.panel, r, radius=4)
    if mx <= 0:
        return
    left = max(0.0, hp - dmg)
    w_left = r.w * left / mx
    w_dmg = r.w * min(hp, dmg) / mx
    if w_left > 0:
        gui.rect(color, (r.x, r.y, max(1, w_left), r.h), radius=4)
    if w_dmg > 0:
        gui.rect(t.warn, (r.x + w_left, r.y, max(1, w_dmg), r.h), radius=2)
    gui.rect(t.border, r, 1, radius=4)


def draw_pause(app):
    """일시정지 창: 게임 메뉴 버튼 6개."""
    g = app.game
    gui = app.gui
    r = modal_frame(app, 460, 330, "일시정지")
    bw, bh = (r.w - 60) / 2, 48
    x0, y0 = r.x + 24, r.y + 70
    items = [
        ("저장 F5", lambda: app.open_slots("save"), True),
        ("저장하고 나가기", lambda: app.open_slots("save_exit"), True),
        ("불러오기 F9", lambda: app.open_slots("load"), True),
        ("도움말 F1", lambda: setattr(app, "modal", ("help", None)), True),
        ("이벤트 로그", lambda: setattr(app, "modal", ("log", None)), True),
        ("반기 랭킹", lambda: setattr(app, "modal", ("ranking", max(g.rankings) if g.rankings else None)),
         bool(g.rankings)),
    ]
    for i, (label, act, ok) in enumerate(items):
        bx = x0 + (i % 2) * (bw + 12)
        by = y0 + (i // 2) * (bh + 10)
        if gui.button((bx, by, bw, bh), label, size=14, enabled=ok):
            act()
            return
    if gui.button((r.centerx - 80, r.bottom - 60, 160, 42), "계속하기", "primary", size=14):
        close(app)
        return
    for k in gui.keys:
        if k.key in (pygame.K_ESCAPE, pygame.K_p):
            close(app)


def draw_save_slots(app):
    """저장 슬롯 3개: 저장 / 저장하고 나가기 / 불러오기."""
    import time
    gui = app.gui
    t = app.theme
    mode = app.modal[1]
    title = {"save": "저장할 슬롯 선택", "save_exit": "저장하고 나가기 — 슬롯 선택", "load": "불러올 슬롯 선택"}[mode]
    r = modal_frame(app, 560, 120 + 76 * C.SAVE_SLOTS, title)
    y = r.y + 64
    for i in range(1, C.SAVE_SLOTS + 1):
        info = app.slot_cache.get(i)
        row = pygame.Rect(r.x + 24, y, r.w - 48, 64)
        gui.rect(t.panel_alt, row, radius=8)
        gui.text((row.x + 16, row.y + 10), f"슬롯 {i}", 15, weight="bold")
        if info:
            when = time.strftime("%m-%d %H:%M", time.localtime(info["mtime"]))
            gui.text((row.x + 16, row.y + 36), f"{info['label']} · 저장 {when} · v{info['version']}", 12, t.muted,
                     max_w=row.w - 150)
        else:
            gui.text((row.x + 16, row.y + 36), "비어 있음", 12, t.muted)
        if mode == "load":
            label, ok = "불러오기", info is not None
        else:
            label, ok = ("덮어쓰기" if info else "저장"), True
        if gui.button((row.right - 116, row.y + 14, 104, 36), label, "primary" if ok else "default", enabled=ok, size=13):
            if mode == "load":
                app.load(f"slot{i}")
                return
            if app.save(f"slot{i}"):
                close(app)
                if mode == "save_exit":
                    app.game = None
                    app.reset_ui()
                    app.scene = "title"
                return
        y += 76
    if mode == "save_exit":
        # 저장하지 않고 시작 화면으로
        if gui.button((r.x + 24, r.bottom - 56, 140, 40), "저장 안 함", "danger"):
            close(app)
            app.game = None
            app.reset_ui()
            app.scene = "title"
            return
    if gui.button((r.right - 144, r.bottom - 56, 120, 40), "취소"):
        close(app)


def close(app):
    app.modal = None


def draw_rebellion(app):
    g = app.game
    gui = app.gui
    t = app.theme
    rid = g.pending_rebellions[0]
    pid = g.player_id
    rr = g.regions[rid]
    r = modal_frame(app, 560, 380, "반란 발생!")
    info = app.world.regions[rid]
    gui.text((r.x + 24, r.y + 56), f"{info.name} · 실질 행복도 {g.eff_happy(rr):+.1f} · 인구 {rr.pop:.1f}만", 15,
             weight="semibold")
    gui.wrap((r.x + 24, r.y + 84), "다른 행동보다 먼저 대응해야 합니다. 진압에 실패하면 이 지역이 수도가 되어 새 국가로 분리독립합니다(건물·인구 계승, 첫 24턴 행복도 0 이상).",
             r.w - 48, 13, t.muted)
    cost = g.rebellion_accept_cost(pid, rid)
    p = g.suppress_chance(pid, rid)
    y = r.y + 140
    f = g.player
    if gui.button((r.x + 24, y, r.w - 48, 44), f"요구 수용: 산출 4턴분 {cost:,.0f} 지불 (행복도 +20)", "primary",
                  enabled=f.money >= cost):
        app.toast(g.resolve_rebellion(pid, rid, "pay"))
    y += 52
    if gui.button((r.x + 24, y, r.w - 48, 44), f"요구 수용: 세율 5%p 인하 ({f.tax*100:.0f}% → {max(0, f.tax*100-5):.0f}%, 행복도 +20)"):
        app.toast(g.resolve_rebellion(pid, rid, "tax"))
    y += 52
    if gui.button((r.x + 24, y, r.w - 48, 44), f"진압 (성공률 {p*100:.0f}%, 성공 시 행복도 +5·병력 10% 손실)", "danger"):
        msg = g.resolve_rebellion(pid, rid, "suppress")
        app.toast(msg, t.bad if "실패" in msg else None)
        app.changed()
        if not g.player.alive:
            g.game_over = True
            app.modal = ("gameover", None)


def draw_proposal(app):
    g = app.game
    gui = app.gui
    t = app.theme
    prop = g.pending_proposals[0]
    fid = prop["from"]
    kind = prop["kind"]
    if not g.factions[fid].alive:
        g.pending_proposals.pop(0)
        return
    r = modal_frame(app, 520, 260, "외교 제안")
    f = g.factions[fid]
    gui.rect(hex2rgb(f.color), (r.x + 24, r.y + 62, 12, 16), radius=3)
    if kind == "coalition_war":
        # 연합 회원의 선전포고: 연합 전원이 동의해야 하고, 수락하면 연합 전원이 함께 선포한다
        tgt = prop["target"]
        if not g.factions[tgt].alive or D.at_war(g, fid, tgt) or not D.same_coalition(g, fid, g.player_id):
            g.pending_proposals.pop(0)
            return
        gui.text((r.x + 44, r.y + 60), f"{g.seen_name(fid)}({g.seen_leader(fid)})이(가) {g.seen_name(tgt)}에 "
                 "연합 공동 선전포고를 제안합니다.", 15, weight="semibold")
        gui.text((r.x + 24, r.y + 96), "수락하면 연합 전원이 함께 선포합니다(전쟁 피로·전쟁광 평판은 각자).", 13, t.muted)
        if gui.button((r.x + 24, r.bottom - 64, 220, 44), "동의", "primary"):
            g.pending_proposals.pop(0)
            ok, msg = D.declare_war(g, fid, tgt, _agreed=(g.player_id,))
            app.toast(msg or f"연합이 {g.seen_name(tgt)}에 선전포고했습니다.", None if ok else t.bad)
            app.changed()
        if gui.button((r.right - 244, r.bottom - 64, 220, 44), "거절"):
            g.pending_proposals.pop(0)
            D.add_opinion(g, fid, g.player_id, -3)
        return
    if kind == "trade":
        # AI의 자원·특산물 거래 제의: 턴당 n개 × 12턴, 개당 값은 받는 턴마다
        res, n, price, sell = prop["res"], prop["n"], prop["price"], prop["sell"]
        pid = g.player_id
        if D.at_war(g, fid, pid):
            g.pending_proposals.pop(0)
            return
        what = f"{D.RES_NAMES[res]} 턴당 {n}개를 {C.CONTRACT_TURNS}턴 동안 개당 {price:,.0f}에"
        gui.wrap((r.x + 44, r.y + 60), f"{g.seen_name(fid)}({g.seen_leader(fid)})이(가) {what} "
                 + ("팔겠다고" if sell else "사겠다고") + " 제안합니다.", r.w - 70, 15, weight="semibold")
        if sell:
            mine = (f"내 공장에 넣으면 턴당 약 {max(0.0, D.energy_value(g, pid, res, n)[1]):,.0f}"
                    if res in C.ENERGY else f"내 특산물 값 개당 {D.spec_price(g, pid):,.0f}")
            note = f"매 턴 {price * n:,.0f}을 냅니다(받은 만큼만). {mine}"
        else:
            have = D.spec_supply(g, pid) if res == "specialty" else int(g.energy_supply(pid)[res])
            note = f"매 턴 {price * n:,.0f}을 받습니다(보낸 만큼만). 지금 턴당 확보량 {have}개"
        gui.wrap((r.x + 24, r.y + 118), note + f" · 수락하면 서로 우호도 +{C.TRADE_OP_PER_UNIT * n:g}, 거절은 변화 없음",
                 r.w - 48, 12, t.muted)
        if gui.button((r.x + 24, r.bottom - 64, 220, 44), "수락", "primary"):
            g.pending_proposals.pop(0)
            seller, buyer = (fid, pid) if sell else (pid, fid)
            D.make_trade(g, seller, buyer, res, n, price, fid)
            app.toast(f"{D.RES_NAMES[res]} 거래 성사 ({C.CONTRACT_TURNS}턴)")
            app.changed()
        if gui.button((r.right - 244, r.bottom - 64, 220, 44), "거절"):
            g.pending_proposals.pop(0)
        return
    gui.text((r.x + 44, r.y + 60), f"{g.seen_name(fid)}({g.seen_leader(fid)})이(가) {D.TREATY_NAMES[kind]}을(를) 제안합니다.", 15,
             weight="semibold")
    gui.text((r.x + 24, r.y + 96), f"상대 우호도 {D.opinion(g, fid, g.player_id):+.0f} · 현재 관계 "
             f"{D.STAGE_NAMES[D.stage(g, fid, g.player_id)]}", 13, t.muted)
    if gui.button((r.x + 24, r.bottom - 64, 220, 44), "수락", "primary"):
        D.sign_treaty(g, fid, g.player_id, kind)
        g.pending_proposals.pop(0)
        app.toast(f"{D.TREATY_NAMES[kind]} 체결")
        app.changed()
    if gui.button((r.right - 244, r.bottom - 64, 220, 44), "거절"):
        g.pending_proposals.pop(0)
        D.add_opinion(g, fid, g.player_id, -3)


# ------------------------------------------------------------------ 외교 창
class DiploDraft:
    def __init__(self, fid):
        self.fid = fid
        self.offer = D.empty_offer()
        self.counter = None
        self.result = ""


def _side_editor(app, x, y, w, side, owner, other, label):
    gui = app.gui
    g = app.game
    t = app.theme
    f = g.factions[owner]
    gui.text((x, y), label, 14, weight="bold")
    gui.text((x + w, y + 3), f"자원은 턴당 개수 × {C.CONTRACT_TURNS}턴", 11, t.muted, anchor="topright")
    y += 26
    # 자원은 쌓이지 않으니(식량 제외) 턴당 확보량까지만 내줄 수 있다. 식량은 비축 ÷ 12턴
    sup = g.energy_supply(owner)
    rows = [("money", "돈", max(0, int(f.money)), 100)]
    rows.append(("food", "식량/턴", int(f.res.get("food", 0) // C.CONTRACT_TURNS), 1))
    rows += [(res, C.RESOURCE_NAMES[res] + "/턴", int(sup[res]), 1) for res in ("oil", "coal", "elec")]
    rows.append(("specialty", "특산물/턴", D.spec_supply(g, owner), 1))
    for key, name, mx, step in rows:
        side[key] = min(side[key], mx)
        gui.text((x, y + 6), name, 13)
        gui.text((x + 78, y + 6), f"{side[key]:,} / {mx:,}", 13, weight="semibold")

        def pick(v, side=side, key=key):
            side[key] = v
        if gui.button((x + w - 66, y, 66, 28), "선택", size=12, enabled=mx > 0):
            open_qty(app, f"{label} — {name}", mx, side[key], pick, step=step)
        y += 34
    y += 2
    side["passage"] = gui.checkbox((x, y, w, 24), "군사통행권", side["passage"])
    y += 30
    gui.text((x, y), "영토 (상대와 맞닿은 지역)", 12, t.muted)
    y += 20
    border = sorted({r.id for r in g.regions_of(owner)
                     if any(g.regions[n].owner == other for n in app.world.land_adj[r.id])})
    for rid in border[:6]:
        on = rid in side["regions"]
        new = gui.checkbox((x, y, w, 22), f"{app.world.regions[rid].name} (산출 {g.region_output_estimate(rid):,.0f})",
                           on, size=12)
        if new != on:
            side["regions"] = [r for r in side["regions"] if r != rid] + ([rid] if new else [])
        y += 24
    if not border:
        gui.text((x, y), "없음", 12, t.muted)
    return y


def draw_diplomacy(app):
    g = app.game
    gui = app.gui
    t = app.theme
    ds = app.dip_state
    pid = g.player_id
    fid = ds.fid
    other = g.factions[fid]
    if not other.alive:
        close(app)
        return
    r = modal_frame(app, 980, 700)
    draw_flag(gui, (r.x + 24, r.y + 22, 48, 32), FL.faction_flag(other))
    from ..leaders import GOV_BY_KEY
    gui.text((r.x + 82, r.y + 18), f"{other.name}", 20, weight="bold")
    gui.text((r.x + 82, r.y + 46), f"{other.leader_name} · {GOV_BY_KEY.get(other.gov, {}).get('name', '')} · "
             f"국력 {g.power.get(fid, 0):.2f} · 지역 {g.region_count(fid)}곳", 12, t.muted)
    if gui.button((r.right - 44, r.y + 16, 28, 28), "×", "ghost", size=18):
        close(app)
        return
    # 관계 단계 표시
    st = D.stage(g, fid, pid)
    op = D.opinion(g, fid, pid)
    steps = ["우호", "통행권·불가침", "동맹", "연합"]
    sx = r.x + 420
    for i, nm in enumerate(steps):
        cell = pygame.Rect(sx + i * 128, r.y + 20, 122, 30)
        active = st >= i + 1
        col = t.bad if st == -1 else (t.accent if active else t.panel_alt)
        gui.rect(col, cell, radius=15)
        gui.text(cell.center, nm, 12, (255, 255, 255) if active or st == -1 else t.muted, "semibold", anchor="center")
    status = "전쟁 중" if st == -1 else D.STAGE_NAMES[st]
    pl = D.peace_left(g, pid, fid)
    gui.text((sx, r.y + 58), f"상대의 우호도 {op:+.2f} · 현재 {status}"
             + (f" · 전쟁 점수 {D.war_score(g, pid, fid):+.1f}" if st == -1 else "")
             + (f" · 강화 불가침 {pl}턴 남음" if pl else ""), 13,
             t.bad if st == -1 else t.text)
    # AI의 태도: 전쟁 중이면 강화 판단, 아니면 체제 기본 우호도와 전쟁 검토 문턱
    from .. import ai as AI
    if st == -1:
        a = AI.war_assessment(g, fid, pid)
        why = ", ".join((a["pro"] + a["con"])[:3])
        hint = f"강화 의향 {a['desire']:.1f} (≥{C.AI_PEACE_ACCEPT:.1f}이면 강화 수락)" + (f" · {why}" if why else "")
    else:
        ratio = g.mil_power(fid) / max(10.0, AI.perceived_power(g, fid, pid))
        thr = AI.war_op_threshold(g, other, pid, ratio)
        hint = (f"체제 기본 우호도 {D.op_baseline(g, fid, pid):+.0f} · 호전성 {AI.eff_aggression(g, other):.1f}: "
                f"우호도가 약 {thr:+.0f} 이하로 떨어지면 전쟁을 검토")
    gui.text((sx, r.y + 77), hint, 11, t.muted, max_w=r.right - 24 - sx)
    # 거래
    col_w = 300
    y1 = _side_editor(app, r.x + 24, r.y + 96, col_w, ds.offer["give"], pid, fid, "내가 제공")
    y2 = _side_editor(app, r.right - 24 - col_w, r.y + 96, col_w, ds.offer["take"], fid, pid, "상대가 제공")
    mx = r.x + 24 + col_w + 24
    mw = r.w - 2 * (col_w + 48)
    gui.text((mx, r.y + 96), "AI 예상 반응", 14, weight="bold")
    res, counter, info = D.evaluate_offer(g, fid, pid, ds.offer)
    label = {"accept": "수락할 것", "counter": "수정 제안", "reject": "거절할 것"}[res]
    col = {"accept": t.good, "counter": t.warn, "reject": t.bad}[res]
    gui.text((mx, r.y + 124), label, 18, col, "bold")
    gui.wrap((mx, r.y + 154), info, mw, 12, t.muted)
    m = D.trade_m(g, fid, pid)
    gui.wrap((mx, r.y + 214), f"요구 배수 m = {m:.2f}\n(받는 가치 ≥ 주는 가치 × m 이면 수락)", mw, 12, t.muted)
    if gui.button((mx, r.y + 270, mw, 38), "제안하기", "primary"):
        op0 = D.opinion(g, fid, pid)
        res2, counter2, info2 = D.respond_offer(g, fid, pid, ds.offer)
        if res2 == "accept":
            gain = D.opinion(g, fid, pid) - op0
            app.toast(f"거래 성사! 상대 우호도 {gain:+.2f}" if abs(gain) >= 0.005 else "거래 성사!")
            ds.offer = D.empty_offer()
            app.changed()
        elif res2 == "counter":
            ds.counter = counter2
            app.toast("상대가 수정안을 냈습니다.", t.warn)
        else:
            app.toast("거절당했습니다: " + info2, t.bad)
    if ds.counter:
        gui.wrap((mx, r.y + 316), f"수정안: 돈 {ds.counter['give']['money']:,}을 달라고 합니다.", mw, 12, t.warn)
        if gui.button((mx, r.y + 356, mw, 32), "수정안 수락", "primary"):
            D.execute_offer(g, pid, fid, ds.counter)
            D.trade_done_opinion(g, fid, pid, ds.counter)
            ds.counter = None
            ds.offer = D.empty_offer()
            app.toast("거래 성사!")
            app.changed()
    if gui.button((mx, r.y + 396, mw, 30), "초기화", size=12):
        ds.offer = D.empty_offer()
        ds.counter = None
    # 진행 중인 자원 계약(이 나라와)
    cy = r.y + 436
    cs = D.contracts_between(g, pid, fid)
    gui.text((mx, cy), f"진행 중인 자원 계약 {len(cs)}건", 12, weight="semibold")
    cy += 18
    for c in cs[:5]:
        arrow = "→ 상대" if c["from"] == pid else "← 상대"
        price = f" · 개당 {c['price']:,.0f}" if c["price"] > 0 else ""
        gui.text((mx, cy), f"{D.RES_NAMES[c['res']]} 턴당 {c['n']} {arrow} · 남은 {c['left']}턴{price}", 11, t.muted,
                 max_w=mw)
        cy += 16
    # 조약 버튼
    y = r.bottom - 110
    gui.line(t.border, (r.x + 24, y - 10), (r.right - 24, y - 10))
    gui.text((r.x + 24, y), "조약·전쟁", 14, weight="bold")
    # 우호 선언·비난: 마우스를 올리면 세력별 우호도 변화 미리보기
    sw_ = 150
    ok_f, why_f = D.friendship_check(g, pid, fid)
    tip_f = (("수락 예상: " if ok_f else "불가: ") + why_f + "\n" +
             D.effects_text(g, D.friendship_effects(g, pid, fid)) + f"\n쿨타임 {C.DECL_COOLDOWN}턴")
    if gui.button((r.right - 24 - 2 * sw_ - 8, y - 4, sw_, 28), "우호 선언", "primary" if ok_f else "default",
                  size=12, enabled=ok_f, tooltip=tip_f):
        ok2, msg = D.declare_friendship(g, pid, fid)
        app.toast(msg, None if ok2 else t.bad)
        app.changed()
    ok_d, why_d = D.denounce_check(g, pid, fid)
    n_rec = D.recent_denounces(g, pid)
    tip_d = ((why_d + "\n" if why_d else "") + D.effects_text(g, D.denounce_effects(g, pid, fid))
             + f"\n최근 {C.DENOUNCE_WINDOW}턴 비난 {n_rec}회"
             + (f" — {C.DENOUNCE_SPAM_N}번째부터 모든 세력 우호도 {C.DENOUNCE_SPAM}" if n_rec + 1 >= C.DENOUNCE_SPAM_N else "")
             + f"\n쿨타임 {C.DECL_COOLDOWN}턴")
    if gui.button((r.right - 24 - sw_, y - 4, sw_, 28), "비난", "danger", size=12, enabled=ok_d, tooltip=tip_d):
        ok2, msg = D.denounce(g, pid, fid)
        app.toast(msg, t.warn if ok2 else t.bad)
        app.changed()
    y += 26
    bw = (r.w - 48 - 5 * 8) / 6
    buttons = []
    if st == -1:
        buttons.append(("peace", "강화 제안"))
    else:
        buttons += [("nonaggr", "불가침 제안"), ("passage", "통행권 제안"), ("alliance", "동맹 제안"),
                    ("coalition", "연합 제안")]
    for i, (kind, lab) in enumerate(buttons):
        ok, why = D.treaty_check(g, fid, pid, kind)
        if gui.button((r.x + 24 + i * (bw + 8), y, bw, 40), lab, "primary" if ok else "default",
                      tooltip=("수락 예상: " if ok else "거절 예상: ") + why):
            ok2, msg = D.propose_treaty(g, pid, fid, kind)
            app.toast(msg, None if ok2 else t.bad)
            app.changed()
    i = len(buttons)
    p = D.pair(pid, fid)
    if st != -1:
        if p in g.dip.nonaggr and p not in g.dip.alliance:
            if gui.button((r.x + 24 + i * (bw + 8), y, bw, 40), "불가침 파기", "danger", enabled=pl == 0,
                          tooltip="모든 세력의 우호도 -30" if pl == 0 else f"강화 불가침 {pl}턴 동안 파기 불가"):
                ok, msg = D.break_nonaggr(g, pid, fid)
                app.toast(msg or "불가침조약을 파기했습니다.", t.bad)
            i += 1
        elif p in g.dip.alliance:
            if gui.button((r.x + 24 + i * (bw + 8), y, bw, 40), "동맹 탈퇴", "danger"):
                D.leave_alliance(g, pid, fid)
            i += 1
        can_war = not D.has_nonaggr(g, pid, fid)
        tip = (f"전쟁 피로도 +{C.WAR_WEARY_START['aggressor']:.0f}(전쟁 중 턴당 +{C.WAR_WEARY_TURN['aggressor']:g}), "
               f"상대 우호도 -100,\n전쟁광 평판: 다른 모든 세력 우호도 {D.warmonger_penalty(g, pid):+.0f}"
               if can_war else "불가침·동맹 중에는 먼저 파기")
        if gui.button((r.x + 24 + i * (bw + 8), y, bw, 40), "선전포고", "danger", enabled=can_war, tooltip=tip):
            ok, msg = D.declare_war(g, pid, fid)
            app.toast(msg or f"{other.name}에 선전포고했습니다.", t.bad)
            app.changed()
    if D.coalition_of(g, pid) is not None and gui.button((r.right - 24 - bw, r.y + 58 + 0, bw, 28), "연합 탈퇴",
                                                         "danger", size=12, tooltip="모든 회원 우호도 -50"):
        D.leave_coalition(g, pid)


# ------------------------------------------------------------------ 랭킹·로그·도움말·종료
def ranking_value_text(g, row, key) -> str:
    v = row.get(key, 0)
    if key == "happy":
        return f"{v:+.1f}"
    if key == "gdp":
        return f"{v:,.0f} ({row.get('gdp_share', 0) * 100:.1f}%)"
    if key == "science":
        return f"{v}/{len(C.SCIENCE_STEPS)}"
    if key == "econ":
        return f"{v}/{C.ECON_STAGES}"
    return f"{v:,.0f}"


def draw_ranking(app):
    """반기 랭킹: 첫 행(머리글)의 열을 누르면 그 항목 순으로 줄을 세운다. 조우하지 않은 국가는 국기와 '미지의 국가'만."""
    g = app.game
    gui = app.gui
    t = app.theme
    keys = sorted(g.rankings)
    turn = app.modal[1] if app.modal[1] in g.rankings else (keys[-1] if keys else None)
    rows = g.rankings.get(turn, [])
    title = f"{g.ranking_label(turn)} 랭킹" if turn else "반기 랭킹"
    sh = gui.size()[1]
    rh = max(24, min(40, int((sh - 40 - 210) / max(1, len(rows)))))    # 국가가 많으면(최대 16) 줄 간격을 좁혀 화면 안에
    r = modal_frame(app, 1040, 150 + rh * max(1, len(rows)) + 60, title)
    pid = g.player_id
    cols = g.RANKING_COLS
    sel = getattr(app, "rank_col", "regions")
    if turn:
        gui.text((r.right - 24, r.y + 26), f"발표 {R.date_label(turn)}", 12, t.muted, anchor="topright")
    x0 = r.x + 24
    y = r.y + 64
    name_w = 210
    wts = [1.6 if k == "gdp" else 1.0 for k, _ in cols]          # GDP 칸은 '액수(비율%)'라 넓게
    unit = (r.w - 48 - 50 - name_w) / sum(wts)
    cx = [x0 + 50 + name_w + unit * sum(wts[:i]) for i in range(len(cols))]
    gui.text((x0, y + 8), "순위", 13, t.muted, "semibold")
    gui.text((x0 + 50, y + 8), "국가", 13, t.muted, "semibold")
    for i, (k, nm) in enumerate(cols):
        if gui.button((cx[i], y, unit * wts[i] - 6, 32), nm, "primary" if k == sel else "default",
                      size=12):
            app.rank_col = sel = k
    y += 42
    order = sorted(rows, key=lambda rr: (-rr.get(sel, 0), -rr.get("regions", 0)))
    for pos, row in enumerate(order, 1):
        fid = row["fid"]
        me = fid == pid
        known = g.has_met(pid, fid)
        fs = 14 if rh >= 34 else 12
        ty = y + (rh - 4) // 2
        if me:
            gui.rect(t.panel_alt, pygame.Rect(x0 - 8, y - 2, r.w - 32, rh - 4), radius=6)
        gui.text((x0 + 4, ty), f"{pos}", fs, weight="bold", anchor="midleft")
        fh = min(20, rh - 10)
        draw_flag(gui, (x0 + 50, ty - fh // 2, fh * 3 // 2, fh), FL.faction_flag(g.factions[fid]))
        gui.text((x0 + 90, ty), g.seen_name(fid) + (" (나)" if me else ""), fs,
                 None if known else t.muted, "bold" if me else "regular", max_w=name_w - 46, anchor="midleft")
        for i, (k, _) in enumerate(cols):
            txt = ranking_value_text(g, row, k) if known else "?"
            gui.text((cx[i] + 6, ty), txt, fs - 1, None if known else t.muted,
                     "bold" if k == sel and known else "regular", max_w=unit * wts[i] - 12, anchor="midleft")
        y += rh
    if not rows:
        gui.text((x0, y), "아직 발표된 랭킹이 없습니다.", 13, t.muted)
    # 지난 발표 보기
    i = keys.index(turn) if turn in keys else -1
    if gui.button((r.x + 24, r.bottom - 56, 120, 40), "◀ 이전 발표", enabled=i > 0):
        app.modal = ("ranking", keys[i - 1])
    if gui.button((r.x + 152, r.bottom - 56, 120, 40), "다음 발표 ▶", enabled=0 <= i < len(keys) - 1):
        app.modal = ("ranking", keys[i + 1])
    if gui.button((r.right - 144, r.bottom - 56, 120, 40), "닫기", "primary"):
        close(app)


def draw_log(app):
    g = app.game
    gui = app.gui
    t = app.theme
    r = modal_frame(app, 820, 640, "이벤트 로그")
    pid = g.player_id
    evs = [e for e in reversed(g.history) if pid in e["fids"] or e["kind"] in ("war", "peace", "eliminated",
                                                                                "ranking", "victory", "diplo", "alert")]
    evs = [(e, txt) for e in evs for txt in [g.event_for_player(e)] if txt is not None]   # 미지의 국가는 가림
    area = pygame.Rect(r.x + 16, r.y + 60, r.w - 32, r.h - 130)
    off = gui.begin_scroll("log", area, len(evs) * 24)
    y = area.y - off
    for e, txt in evs:
        col = {"battle": t.bad, "war": t.bad, "rebel": t.warn, "famine": t.warn, "captured": t.good}.get(e["kind"], t.text)
        gui.text((area.x + 8, y), f"턴 {e['turn']}", 12, t.muted)
        gui.text((area.x + 64, y), txt, 13, col, max_w=area.w - 80)
        y += 24
    gui.end_scroll("log", area, len(evs) * 24)
    if gui.button((r.right - 144, r.bottom - 56, 120, 40), "닫기", "primary"):
        close(app)


HELP = """[조작]
좌클릭: 구역·해역 선택   우클릭: 선택한 부대의 이동·공격 대상 지정
마우스 휠 / + -: 확대·축소   드래그 / 방향키: 지도 이동   더블클릭: 확대
Enter: 다음 지역 / 턴 종료   Shift+Enter: 바로 턴 종료   Tab: 빈 슬롯 순회   A: 빈 슬롯 자동 지정   1~7: 지도 모드
P 일시정지 / F5 저장 / F9 불러오기   Ctrl+D: 다크 모드   Esc: 선택 해제

· 빈 슬롯 지역이 남아 있으면 우하단 버튼이 [다음 지역]이 되어 수도부터 획득 순서대로 행동 메뉴를 엽니다.
· 정치 지도에서 진한 색 내 영토는 생산·행동이 진행 중인 지역입니다.
· 생산 집중: 건설·병력 생산을 하지 않는 지역의 인구 산출 +15%.
· 좌측 [내정]: 세율·자원 시장·특산물·지출 우선순위. [국가 현황]: 통계·재정·승리 조건 진행.
· [자원 배정]의 [자동 배정]: 발전소에 석유 → 석탄 → 공장에 전기 → 석탄 → 석유 순으로 배정.
· 석유·석탄·전기·특산물은 쌓이지 않습니다: 매 턴 생산량(+계약)만큼 쓰고, 남는 석유·석탄·전기는 턴 종료 때 저절로 팝니다.
· 외교 거래·선물의 자원은 '턴당 n개 × 12턴' 계약입니다. AI도 남는 자원을 팔고 모자라면 사자고 제안합니다.
· [부대] 탭의 [합치기]: 부대가 둘뿐이면 바로 합침. 셋 이상이면 합칠 부대를 체크한 뒤 Enter나 [합치기]를 한 번 더.

[규칙 요약]
· 각 내 지역은 턴마다 슬롯 1개: 건물 착공, 유닛 생산, 인접 중립 지역 편입 중 하나.
· 비용은 매 턴 나눠서 내고, 자금이 모자라면 멈춥니다. 취소하면 낸 비용의 50% 환급.
· 자국 영토 안에서는 2칸, 그 밖은 1칸 이동. 해군은 턴당 한 칸: 항구→해역, 해역→해역, 해역→상륙·입항.
· 산출 Y = 30P + 150g(농장) + 150g(어장) + 1000g(공장)φ + 600g(은행)
· 세수 = Y × 세율. 세율 10%(전제군주제 12%)보다 높으면 행복도가 떨어지고 낮으면 오릅니다.
· 실질 행복도 = 행복도 − 전쟁 피로도 − 징집 피로. 10 이상·식량 충분일 때 인구 증가, -50 이하부터 반란.
· 전쟁 피로도: 선전포고 +15, 당하면 +10, 전쟁 중 턴당 +0.75, 당하면 +0.5, 평시 턴당 1 회복.
· 점령한 적 지역은 4턴 저항 뒤 20턴에 걸쳐 회복, 36턴 동안 반란 없음.
· 전투: 방어측 피해 0.5rA²/(A+D), 공격측 피해 0.5rD²/(A+D). 방어선은 돌격 방어를 높입니다.
· 승리: 정복 / 과학 / 경제 / 외교 / 시간 종료. 진행 상황은 [국가 현황]에 나옵니다."""


def draw_help(app):
    r = modal_frame(app, 820, 560, "도움말")
    app.gui.wrap((r.x + 24, r.y + 60), HELP, r.w - 48, 13)
    if app.gui.button((r.right - 144, r.bottom - 56, 120, 40), "닫기", "primary"):
        close(app)


def draw_dialogue(app):
    """지도자 대사 팝업: 초상화와 대사. 우상단 X 또는 Enter로 닫고, 쌓인 다음 팝업으로 넘어간다."""
    from .. import dialogue as DLG
    g = app.game
    gui = app.gui
    t = app.theme
    q = g.dialogues
    d = q[0]
    f = g.factions[d["fid"]]
    text = DLG.line(f.leader, d["kind"])
    if not text:                                  # 대사가 없는 지도자(직접 입력 등)는 건너뛴다
        q.pop(0)
        return
    r = modal_frame(app, 780, 380)
    ph = 260
    draw_portrait(gui, (r.x + 28, r.y + 56, ph * 3 // 4, ph), f.leader, t)
    x = r.x + 28 + ph * 3 // 4 + 28
    w = r.right - 28 - x
    gui.text((x, r.y + 24), DLG.TITLES.get(d["kind"], ""), 14,
             t.bad if d["kind"] in ("war", "denounce", "victory") else t.accent, "bold")
    gui.text((x, r.y + 56), f.leader_name, 22, weight="bold", max_w=w)
    draw_flag(gui, (x, r.y + 94, 36, 24), FL.faction_flag(f))
    lang = DLG.language(f.leader)
    sub = f.name + (f" · {lang}" if lang and not lang.startswith("한국어") else "")
    gui.text((x + 46, r.y + 96), sub, 14, t.muted, max_w=w - 46)
    i = text.rfind("(")
    if i > 0 and text.rstrip().endswith(")"):           # 외국어 대사: 괄호 속 우리말 뜻은 다음 줄
        body = f"“{text[:i].rstrip()}”\n{text[i:].strip()}"
    else:
        body = f"“{text}”"
    gui.wrap((x, r.y + 140), body, w, 17, line_h=32, words=True, center=True)
    gui.text((r.right - 28, r.bottom - 34), "Enter 또는 X로 닫기" + (f" · 다음 {len(q) - 1}건" if len(q) > 1 else ""),
             12, t.muted, anchor="topright")
    done = gui.button((r.right - 52, r.y + 14, 36, 36), "×", "ghost", size=18)
    guard = pygame.time.get_ticks() < getattr(app, "enter_guard", 0)
    for k in list(gui.keys):
        if k.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            gui.keys.remove(k)
            done = done or not guard               # 턴 종료 Enter가 이어서 대사를 넘기지 않게
    if done and q:
        q.pop(0)


def draw_gameover(app):
    g = app.game
    gui = app.gui
    t = app.theme
    r = modal_frame(app, 560, 280)
    if g.winner:
        fids, kind = g.winner
        me = g.player_id in fids
        title = ("승리! " if me else "패배 — ") + C.VICTORY_TYPES[kind]
        names = ", ".join(g.fname(f) for f in fids)
        gui.text((r.centerx, r.y + 50), title, 26, t.good if me else t.bad, "bold", anchor="center")
        gui.text((r.centerx, r.y + 100), f"승자: {names} · {g.date_label()}", 15, anchor="center")
    else:
        gui.text((r.centerx, r.y + 50), "패배", 26, t.bad, "bold", anchor="center")
        gui.text((r.centerx, r.y + 100), "모든 영토를 잃었습니다.", 15, anchor="center")
    if gui.button((r.x + 24, r.bottom - 64, 240, 44), "새 게임", "primary"):
        app.game = None
        app.scene = "title"
        app.reset_ui()
    if gui.button((r.right - 264, r.bottom - 64, 240, 44), "지도 계속 보기"):
        close(app)


# ------------------------------------------------------------------ 특산물 배분
def draw_specialty(app):
    g = app.game
    gui = app.gui
    t = app.theme
    pid = g.player_id
    f = g.player
    r = modal_frame(app, 980, 660, "특산물 배분")
    if gui.button((r.right - 44, r.y + 16, 28, 28), "×", "ghost", size=18):
        close(app)
        return
    gui.text((r.x + 24, r.y + 52), f"한 지역에 최대 {C.SPECIALTY_MAX_TYPES}종, 종류별 턴당 1개 소비 · 남는 특산물은 쌓이지 않고 사라짐"
             " · 변경은 이번 턴 자원 단계에 반영", 12, t.muted)
    f.auto_specialty = gui.checkbox((r.right - 260, r.y + 20, 220, 24), "행복도 낮은 지역부터 자동", f.auto_specialty)
    # 재고
    stock = {k: v for k, v in f.specialty.items() if v > 0}
    kinds = g.specialty_kinds(pid)
    prod = {}
    for rr in g.regions_of(pid):
        if rr.b["specialty"]:
            for sp in app.world.regions[rr.id].specialties:
                prod[sp] = prod.get(sp, 0) + rr.b["specialty"]
    used = {}
    for rr in g.regions_of(pid):
        for k in rr.supplied:
            used[k] = used.get(k, 0) + 1
    # 좌: 지역 목록 (행복도 낮은 순)
    regs = sorted(g.regions_of(pid), key=lambda rr: rr.happy)
    left = pygame.Rect(r.x + 16, r.y + 80, 430, r.h - 150)
    gui.rect(t.panel_alt, left, radius=8)
    off = gui.begin_scroll("spec_regions", left, len(regs) * 34 + 8)
    y = left.y + 4 - off
    for rr in regs:
        row = pygame.Rect(left.x + 4, y, left.w - 12, 30)
        sel = app.spec_sel == rr.id
        if sel:
            gui.rect(t.panel, row, radius=6)
            gui.rect(t.accent, row, 1, radius=6)
        gui.text((row.x + 8, row.y + 6), app.world.regions[rr.id].name, 13, weight="semibold", max_w=170)
        hc = t.good if rr.happy >= 0 else t.bad
        gui.text((row.x + 190, row.y + 6), f"{rr.happy:+.0f}", 13, hc)
        marks = (" 고정" if rr.spec_pin else "") + (" 제외" if rr.spec_block else "")
        gui.text((row.right - 8, row.y + 6), f"{len(rr.supplied)}/{C.SPECIALTY_MAX_TYPES} {marks}", 12, t.muted,
                 anchor="topright")
        if gui.hover(row) and gui.clicked:
            gui.clicked = False
            app.spec_sel = rr.id
        y += 34
    gui.end_scroll("spec_regions", left, len(regs) * 34 + 8)
    # 우: 선택 지역 편집
    x = r.x + 470
    w = r.right - 24 - x
    y = r.y + 80
    rid = app.spec_sel
    if rid not in g.regions or g.regions[rid].owner != pid:
        gui.text((x, y), "왼쪽에서 지역을 고르세요.", 14, t.muted)
        gui.text((x, y + 30), f"보유 특산물 {len(kinds)}종 · 이번 턴 {sum(stock.values())}개", 13)
    else:
        rr = g.regions[rid]
        gui.text((x, y), f"{app.world.regions[rid].name}  (행복도 {rr.happy:+.1f}, 실질 {g.eff_happy(rr):+.1f})", 16,
                 weight="bold")
        y += 30
        gui.text((x, y), "종류", 12, t.muted)
        gui.text((x + 170, y), "이번 턴/생산", 12, t.muted)
        gui.text((x + 250, y), "상태", 12, t.muted)
        y += 22
        area = pygame.Rect(x - 4, y, w + 8, r.bottom - 70 - y)
        rows = kinds
        off = gui.begin_scroll("spec_kinds", area, len(rows) * 34)
        yy = y - off
        for k in rows:
            if k in rr.spec_pin:
                st, col = "고정 공급", t.accent
            elif k in rr.spec_block:
                st, col = "제외", t.bad
            elif k in rr.supplied:
                st, col = "공급 중(자동)", t.good
            else:
                st, col = "-", t.muted
            gui.text((x, yy + 6), k, 13, max_w=160)
            gui.text((x + 170, yy + 6), f"{stock.get(k, 0)}/{prod.get(k, 0)}", 12, t.muted)
            gui.text((x + 250, yy + 6), st, 12, col, "semibold")
            bx = x + w - 170
            if gui.button((bx, yy + 2, 54, 26), "고정", size=11, selected=k in rr.spec_pin,
                          ):
                ok, msg = g.set_specialty(pid, rid, k, "auto" if k in rr.spec_pin else "pin")
                if not ok:
                    app.toast(msg, t.bad)
            if gui.button((bx + 58, yy + 2, 54, 26), "제외", size=11, selected=k in rr.spec_block,
                          color=t.bad):
                g.set_specialty(pid, rid, k, "auto" if k in rr.spec_block else "block")
            if gui.button((bx + 116, yy + 2, 54, 26), "자동", size=11):
                g.set_specialty(pid, rid, k, "auto")
            yy += 34
        gui.end_scroll("spec_kinds", area, len(rows) * 34)
        if not rows:
            gui.text((x, y), "보유한 특산물이 없습니다.", 13, t.muted)
    if gui.button((r.x + 16, r.bottom - 56, 220, 40), "모든 수동 지정 해제", size=12):
        for rr in g.regions_of(pid):
            rr.spec_pin.clear()
            rr.spec_block.clear()
        app.toast("모든 지역을 자동 배분으로 되돌렸습니다.")
    if gui.button((r.right - 144, r.bottom - 56, 120, 40), "닫기", "primary"):
        close(app)
