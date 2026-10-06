"""설정 화면과 모달: 정치체제, 반란, 조약 제안, 외교, 연말 랭킹, 로그, 도움말, 게임 종료."""
from __future__ import annotations

import random

import pygame

from .. import config as C
from .. import diplomacy as D
from .. import flags as FL
from ..leaders import GOVERNMENTS, LEADERS, LEADER_BY_KEY, LEADER_CATEGORIES
from ..state import NEUTRAL, Settings
from .art import draw_flag, draw_portrait, render_flag
from .theme import hex2rgb, measure, mix


class SetupState:
    def __init__(self):
        self.name = "대한"
        self.leader = "sej"
        self.custom_name = ""
        self.n_enemies = 4
        self.difficulty = 2
        self.fog = 1
        self.victories = {k: True for k in C.VICTORY_TYPES}
        self.start = None
        self.ai_leaders = []          # 빈 칸은 무작위
        self.seed = ""
        self.max_turns = C.TIME_VICTORY_TURNS
        self.flag = FL.normalize({"bg": "solid", "c1": FL.hex2rgb(C.FACTION_COLORS[0]), "em": "disc"})
        self.flag_draft = None        # 국기 편집 창이 열려 있으면 편집 중인 사본
        self.ai_pick = None           # 적 지도자 고르기 창이 열려 있으면 그 칸 번호
        self.flag_target = 0          # FLAG_TARGETS 순번: 배경 색 1·2, 문양 색 1·2


def modal_frame(app, w, h, title=None):
    dim = pygame.Surface(app.screen.get_size(), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 90))
    app.screen.blit(dim, (0, 0))
    sw, sh = app.gui.size()
    r = pygame.Rect(0, 0, w, h)
    r.center = (sw // 2, sh // 2)
    app.gui.panel(r, radius=12)
    if title:
        app.gui.text((r.x + 24, r.y + 20), title, 20, weight="bold")
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
    "science": "과학승리: ① 수도에 항공우주연구소 → ② 산맥과 맞닿은 지역에 천체관측소 → ③ 바다와 맞닿은 지역에\n"
               "로켓 발사대 → ④ 공장 5단계 지역에서 로켓 추진체 → ⑤ 공장 5단계 지역에서 탑승 모듈 →\n"
               "⑥ 석유 생산 지역에서 발사체 연료. 세 유닛을 발사대 지역에 모으고 턴을 마치면 승리\n"
               f"(단계마다 턴당 {C.SCIENCE_COST_PER_TURN:,} × {C.SCIENCE_TURNS}턴, 단계가 오를 때마다 ×{C.SCIENCE_COST_GROWTH:g})",
    "economic": f"경제승리: 전체 GDP(중립 지역 산출 포함) 중 내 몫이 기준 이상인 상태로 {C.ECON_VICTORY_TURNS}턴 유지하면 승리\n"
                f"(기준은 시작 국가 수에 따라: 8개국 50%, 6개국 60%, 한 나라 늘 때마다 −5%p)",
    "diplomatic": "외교승리: 살아 있는 모든 나라가 하나의 연합에 속하면 연합 전원이 함께 승리",
    "time": f"시간 종료 승리: 정해진 턴(아래 슬라이더, 기본 {C.TIME_VICTORY_TURNS}턴)이 되면\n"
            "점수(점유 지역·GDP·인구 비율의 평균)가 가장 높은 세력이 승리",
}


# ------------------------------------------------------------------ 시작 페이지
_logo = {}


def draw_title(app):
    """시작 페이지: 가운데 로고, 아래 [새로 시작]·[이어하기]."""
    import os
    gui = app.gui
    sw, sh = gui.size()
    if "src" not in _logo:
        try:
            _logo["src"] = pygame.image.load(os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                                          "assets", "ui", "logo.png"))
        except Exception:
            _logo["src"] = None
    src = _logo["src"]
    bw, bh, gap = 220, 54, 20
    lw = min(sw * 0.72, (sh - bh - 120) * 0.9 * (src.get_width() / src.get_height()) if src else 600, 1100)
    lh = lw * src.get_height() / src.get_width() if src else 120
    top = (sh - (lh + 48 + bh)) / 2
    lr = pygame.Rect(int((sw - lw) / 2), int(top), int(lw), int(lh))
    if src:
        pr = gui.R(lr)
        if _logo.get("size") != pr.size:
            _logo["size"], _logo["img"] = pr.size, pygame.transform.smoothscale(src, pr.size)
        gui.screen.blit(_logo["img"], pr.topleft)
    else:
        gui.text(lr.center, "한반도의 문명", 48, weight="bold", anchor="center")
    by = lr.bottom + 48
    bx = sw / 2 - bw - gap / 2
    if gui.button((bx, by, bw, bh), "새로 시작", "primary", size=18, weight="bold"):
        app.scene = "setup"
    if gui.button((bx + bw + gap, by, bw, bh), "이어하기", size=18, weight="bold"):
        app.open_slots("load")
    from ..version import RELEASE_DATE, VERSION
    gui.text((sw - 16, sh - 12), f"v{VERSION} · {RELEASE_DATE} 업데이트", 11, app.theme.muted, anchor="bottomright")


# ------------------------------------------------------------------ 게임 설정
def draw_setup(app):
    gui = app.gui
    t = app.theme
    s = app.setup
    sw, sh = app.gui.size()
    r = pygame.Rect(0, 0, 1180, 760)
    r.center = (sw // 2, sh // 2)
    gui.panel(r, radius=14)
    gui.text((r.x + 32, r.y + 24), "한반도의 문명", 28, weight="bold")
    gui.text((r.x + 34, r.y + 64), "426개 시군구 · 1턴 = 1주 · 2026년 1월 1주 시작", 14, t.muted)
    # 좌측: 국가·지도자
    x, y = r.x + 32, r.y + 104
    gui.text((x, y), "국가 이름", 13, t.muted, "semibold")
    s.name = gui.text_input((x, y + 22, 260, 34), "name", s.name, max_len=10)
    y += 70
    gui.text((x, y), "내 지도자", 13, t.muted, "semibold")
    y += 24
    # 분류 탭(4개) + 직접 입력
    cats = [c[1] for c in LEADER_CATEGORIES]
    cur_cat = getattr(s, "leader_cat", None)
    if cur_cat is None:
        cur_cat = next((i for i, c in enumerate(LEADER_CATEGORIES) if s.leader in c[2]), 0)
    s.leader_cat = gui.segmented((x, y, 618, 32), cats, cur_cat, size=11)
    y += 40
    shown = [LEADER_BY_KEY[k] for k in LEADER_CATEGORIES[s.leader_cat][2]] + [LEADER_BY_KEY["cus"]]
    cols, bw, bh = 4, 150, 34
    for i, l in enumerate(shown):
        cx = x + (i % cols) * (bw + 6)
        cy = y + (i // cols) * (bh + 6)
        tip = f"{l['name']} (호전성 {l['aggr']})\n버프 {l['buff'][0]}: {l['buff'][1]}\n디버프 {l['debuff'][0]}: {l['debuff'][1]}"
        if gui.button((cx, cy, bw, bh), l["name"], selected=s.leader == l["key"], size=13 if len(l["name"]) <= 7 else 11,
                      tooltip=tip):
            s.leader = l["key"]
    y += 4 * (bh + 6) + 8
    lead = LEADER_BY_KEY[s.leader]
    if s.leader == "cus":
        gui.text((x, y + 8), "지도자 이름", 13, t.muted)
        s.custom_name = gui.text_input((x + 90, y, 200, 32), "custom", s.custom_name, max_len=10)
        y += 40
    gui.text((x, y), f"버프 · {lead['buff'][0]}: {lead['buff'][1]}", 13, t.good, max_w=618)
    gui.text((x, y + 22), f"디버프 · {lead['debuff'][0]}: {lead['debuff'][1]}", 13, t.bad, max_w=618)
    # 초상화(세로 3:4)와 국기
    y += 54
    ph = min(160, r.bottom - 56 - y)
    draw_portrait(gui, (x, y, ph * 3 // 4, ph), s.leader, t)
    fx = x + ph * 3 // 4 + 24
    gui.text((fx, y), "국기", 13, t.muted, "semibold")
    draw_flag(gui, (fx, y + 22, 132, 88), s.flag)
    if gui.button((fx, y + 118, 132, 32), "국기 만들기"):
        s.flag_draft = dict(s.flag)
    # 우측: 게임 설정
    x2 = r.x + 680
    y = r.y + 104
    gui.text((x2, y), "적 세력 수", 13, t.muted, "semibold")
    s.n_enemies = gui.stepper((x2 + 110, y - 6, 120, 30), s.n_enemies, 1, 9)
    y += 40
    gui.text((x2, y), "난이도 (AI에만 적용)", 13, t.muted, "semibold")
    s.difficulty = gui.segmented((x2, y + 22, 468, 32), [d[0] for d in C.DIFFICULTIES], s.difficulty, size=11)
    d = C.DIFFICULTIES[s.difficulty]
    gui.text((x2, y + 58), f"AI 인구 성장률 ×{d[1]:.2f} · 생산 수입 ×{d[2]:.2f}", 12, t.muted)
    y += 86
    gui.text((x2, y), "전장의 안개", 13, t.muted, "semibold")
    s.fog = gui.segmented((x2, y + 22, 468, 32), C.FOG_MODES, s.fog, size=12)
    y += 66
    gui.text((x2, y), "승리 조건", 13, t.muted, "semibold")
    y += 22
    for i, (k, nm) in enumerate(C.VICTORY_TYPES.items()):
        cb = (x2 + (i % 3) * 156, y + (i // 3) * 28, 150, 24)
        s.victories[k] = gui.checkbox(cb, nm, s.victories[k])
        if gui.hover(pygame.Rect(cb)):
            gui.tooltip = VICTORY_TIPS.get(k, nm)
    y += 58
    on = s.victories.get("time", False)
    gui.text((x2, y + 2), f"시간 종료: {s.max_turns}턴 ({s.max_turns / C.TURNS_PER_YEAR:g}년)", 12,
             t.text if on else t.muted, "semibold")
    v, _ = gui.slider((x2 + 200, y + 4, 260, 16), s.max_turns, C.TIME_VICTORY_MIN, C.TIME_VICTORY_MAX,
                      C.TIME_VICTORY_STEP, "max_turns", enabled=on)
    s.max_turns = int(v)
    y += 34
    gui.text((x2, y), "시작 구역", 13, t.muted, "semibold")
    st_name = app.world.regions[s.start].name if s.start else "무작위"
    gui.text((x2 + 80, y), st_name, 14, weight="semibold")
    if gui.button((x2 + 250, y - 6, 110, 30), "지도에서 선택"):
        app.scene = "pick_start"
        app.pick_popup = None
        app.map.z = 1.0
        app.map.cx, app.map.cy = 280, 520
        app.map.invalidate()
    if gui.button((x2 + 366, y - 6, 100, 30), "무작위"):
        s.start = None
    y += 40
    gui.text((x2, y), "적 지도자 (눌러서 고르기, 무작위는 게임 시작 때 정함)", 13, t.muted, "semibold")
    y += 24
    while len(s.ai_leaders) < s.n_enemies:
        s.ai_leaders.append(None)
    for i in range(s.n_enemies):
        cx = x2 + (i % 3) * 158
        cy = y + (i // 3) * 36
        cur = s.ai_leaders[i]
        lab = LEADER_BY_KEY[cur]["name"] if cur else "무작위"
        if gui.button((cx, cy, 152, 30), f"AI {i+1}: {lab}", size=12):
            s.ai_pick = i                        # 지도자 고르기 창
    y += 3 * 36 + 8
    gui.text((x2, y + 8), "시드", 13, t.muted)
    s.seed = gui.text_input((x2 + 40, y, 120, 32), "seed", s.seed, max_len=9)
    # 하단 버튼
    if gui.button((r.right - 524, r.bottom - 64, 150, 44), "이전", tooltip="시작 페이지로"):
        app.scene = "title"
        return
    if gui.button((r.right - 360, r.bottom - 64, 150, 44), "이어하기", tooltip="저장한 게임 불러오기"):
        app.open_slots("load")
    if gui.button((r.right - 196, r.bottom - 64, 170, 44), "게임 시작", "primary", size=16, weight="bold",
                  enabled=any(s.victories.values())):
        start_from_setup(app)
    gui.text((r.x + 32, r.bottom - 44), "조작: 좌클릭 선택 · 우클릭 명령 · 휠 확대 · 드래그 이동 · Enter 턴 종료 · F1 도움말",
             12, t.muted)


FLAG_TARGETS = (("c1", "배경 색 1"), ("c2", "배경 색 2"), ("ec", "문양 색 1"), ("ec2", "문양 색 2"))
FLAG_TARGET_USED = {"c1": lambda fl: True, "c2": FL.uses_c2, "ec": FL.uses_ec, "ec2": FL.uses_ec2}


def draw_flag_editor(app):
    """국기 만들기: 배경 무늬(5×2)·문양(6×4)·색(RGB 각 00~FF 슬라이더), 또는 역사 국기."""
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
    y += 44
    for i, (ch, cc) in enumerate((("R", (220, 60, 60)), ("G", (40, 160, 70)), ("B", (50, 100, 220)))):
        gui.text((x, y + i * 40 + 8), ch, 15, cc if not preset else t.muted, "bold", anchor="midleft")
        v, _ = gui.slider((x + 26, y + i * 40, 200, 16), col[i], 0, 255, 1, f"flag_{ck}_{i}", enabled=not preset)
        col[i] = int(v)
        if not preset:
            col[i] = _num_input(gui, s, (x + 236, y + i * 40 - 7, 64, 30), f"flagnum_{ck}_{i}", col[i])
        else:
            gui.text((x + 300, y + i * 40 + 8), str(col[i]), 13, t.muted, anchor="midright")
    fl[ck] = tuple(col)
    y += 3 * 40 + 6
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
    if gui.button((r.x + 24, r.bottom - 56, 110, 38), "무작위", tooltip="무작위 색으로 AI 국기 규칙에 따라 만듭니다"):
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
            tip = (f"{l['name']} (호전성 {l['aggr']})\n버프 {l['buff'][0]}: {l['buff'][1]}\n"
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
    return out


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
        ai_leaders=_unique_ai_leaders(s), seed=seed, max_turns=s.max_turns)
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
        tgt = f"AI 목표 호전성 {gdef['target']}" if gdef["target"] else "플레이어 전용"
        gui.text((row.right - 16, row.y + 12), tgt, 11, t.muted, anchor="topright")
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
    if name == "rebellion":
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
    can_surprise = any(army.units.get(k) for k in C.SURPRISE_UNITS)
    if not can_surprise:
        st["mode"] = "assault"
    bd = g.battle_breakdown(army, node, st["mode"])
    if bd is None:
        close(app)
        return
    r = modal_frame(app, 780, 600, f"전투 확인 — {app.world.node_name(army.loc)} → {app.world.node_name(node)}")
    pv = bd["preview"]
    if can_surprise:
        idx = gui.segmented((r.right - 244, r.y + 18, 220, 30), ["돌격", "기습"], 0 if st["mode"] == "assault" else 1,
                            size=12)
        st["mode"] = "assault" if idx == 0 else "surprise"
    colw = (r.w - 72) / 2
    for i, (title, units_txt, val, factors, color) in enumerate((
            (f"공격 · {g.fname(army.owner)}", _units_text(bd["att_units"]), f"공격력 {pv['A'] / C.UNIT_STAT_SCALE:,.1f}",
             bd["att_factors"], t.accent),
            ("방어 · " + ", ".join(g.fname(o) for o in bd["def_units"]),
             " / ".join(_units_text(u) for u in bd["def_units"].values()), f"방어력 {pv['D'] / C.UNIT_STAT_SCALE:,.1f}",
             bd["def_factors"], t.bad))):
        x = r.x + 24 + i * (colw + 24)
        y = r.y + 64
        gui.rect(t.panel_alt, (x, y, colw, 250), radius=10)
        gui.text((x + 14, y + 10), title, 14, color, "bold", max_w=colw - 28)
        y = gui.wrap((x + 14, y + 36), units_txt, colw - 28, 13)
        gui.text((x + 14, y + 4), val, 16, weight="bold")
        y += 34
        gui.text((x + 14, y), "적용 보정", 12, t.muted, "semibold")
        y += 20
        if not factors:
            gui.text((x + 14, y), "없음", 12, t.muted)
        for label, mult in factors[:6]:
            good = mult > 1
            gui.text((x + 14, y), label, 12, max_w=colw - 100)
            gui.text((x + colw - 14, y), f"×{mult:.2f}", 12, t.good if good else t.bad, "semibold", anchor="topright")
            y += 20
    # 예상 결과
    y = r.y + 330
    gui.text((r.x + 24, y), "예상 결과 (무작위 ±15%)", 14, weight="bold")
    y += 26
    for oc in bd["outcomes"]:
        row = pygame.Rect(r.x + 24, y, r.w - 48, 56)
        gui.rect(t.panel_alt, row, radius=8)
        gui.text((row.x + 12, row.y + 8), oc["label"], 13, weight="semibold")
        res = "적 병력 전멸 → 진입·점령" if oc["capture"] else "적 병력이 남음 → 진입 못 함"
        gui.text((row.right - 12, row.y + 8), res, 13, t.good if oc["capture"] else t.warn, "semibold",
                 anchor="topright")
        gui.text((row.x + 12, row.y + 32),
                 f"적 피해 {oc['def_dmg'] / C.UNIT_STAT_SCALE:,.1f} (예상 손실 {_units_text(oc['def_lost'])}) · "
                 f"아군 피해 {oc['att_dmg'] / C.UNIT_STAT_SCALE:,.1f} (예상 손실 {_units_text(oc['att_lost'])})", 12, t.muted,
                 max_w=row.w - 24)
        y += 64
    if gui.button((r.right - 264, r.bottom - 60, 110, 42), "취소"):
        close(app)
        return
    if gui.button((r.right - 144, r.bottom - 60, 120, 42), "전투", "danger", size=15, weight="bold"):
        ok, msg = g.order_army(army.id, node, st["mode"])
        app.attack_mode = st["mode"]
        close(app)
        app.toast(msg if isinstance(msg, str) else str(msg), None if ok else t.bad)
    for k in list(gui.keys):
        if k.key == pygame.K_ESCAPE:
            gui.keys.remove(k)
            close(app)


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
        ("연말 랭킹", lambda: setattr(app, "modal", ("ranking", max(g.rankings) if g.rankings else None)),
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
    y += 26
    rows = [("money", "돈", max(0, int(f.money)), 100)]
    rows += [(res, C.RESOURCE_NAMES[res], int(f.res.get(res, 0)), 1) for res in ("food", "oil", "coal", "elec")]
    rows.append(("specialty", "특산물", int(sum(f.specialty.values())), 1))
    for key, name, mx, step in rows:
        side[key] = min(side[key], mx)
        gui.text((x, y + 6), name, 13)
        gui.text((x + 70, y + 6), f"{side[key]:,} / {mx:,}", 13, weight="semibold")

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
    gui.text((sx, r.y + 58), f"상대의 우호도 {op:+.1f} · 현재 {status}"
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
        res2, counter2, info2 = D.respond_offer(g, fid, pid, ds.offer)
        if res2 == "accept":
            app.toast("거래 성사!")
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
            D.add_opinion(g, fid, pid, C.OP_TRADE_DONE)
            ds.counter = None
            ds.offer = D.empty_offer()
            app.toast("거래 성사!")
            app.changed()
    if gui.button((mx, r.y + 396, mw, 30), "초기화", size=12):
        ds.offer = D.empty_offer()
        ds.counter = None
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
def draw_ranking(app):
    g = app.game
    gui = app.gui
    t = app.theme
    year = app.modal[1]
    rows = g.rankings.get(year, [])
    r = modal_frame(app, 860, 120 + 40 * max(1, len(rows)) + 60, f"{year}년 연말 랭킹")
    cols = [("money", "잔고"), ("net", "턴당 순수익"), ("happy", "평균 행복도"), ("pop", "총인구(만)"), ("regions", "지역 수")]
    x0 = r.x + 24
    y = r.y + 64
    gui.text((x0, y), "세력", 13, t.muted, "semibold")
    cw = (r.w - 48 - 180) / len(cols)
    for i, (_, nm) in enumerate(cols):
        gui.text((x0 + 180 + i * cw, y), nm, 13, t.muted, "semibold")
    y += 28
    ranks = {}
    for k, _ in cols:
        for pos, row in enumerate(sorted(rows, key=lambda rr: -rr[k])):
            ranks[(row["fid"], k)] = pos + 1
    for row in sorted(rows, key=lambda rr: -rr["regions"]):
        draw_flag(gui, (x0, y + 5, 24, 16), FL.faction_flag(g.factions[row["fid"]]))
        me = row["fid"] == g.player_id
        gui.text((x0 + 30, y + 4), g.seen_name(row["fid"]) + (" (나)" if me else ""), 14,
                 weight="bold" if me else "regular", max_w=150)
        for i, (k, _) in enumerate(cols):
            v = row[k]
            s = f"{v:+.1f}" if k == "happy" else f"{v:,.0f}"
            gui.text((x0 + 180 + i * cw, y + 4), f"{ranks[(row['fid'], k)]}위 · {s}", 13)
        y += 40
    if gui.button((r.right - 144, r.bottom - 56, 120, 40), "닫기", "primary"):
        close(app)


def draw_log(app):
    g = app.game
    gui = app.gui
    t = app.theme
    r = modal_frame(app, 820, 640, "이벤트 로그")
    pid = g.player_id
    evs = [e for e in reversed(g.history) if pid in e["fids"] or e["kind"] in ("war", "peace", "eliminated",
                                                                                "ranking", "victory", "diplo")]
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
Enter: 다음 지역 / 턴 종료   Shift+Enter: 바로 턴 종료   Tab: 빈 슬롯 순회   A: 빈 슬롯 자동 지정   1~8: 지도 모드   F2: 개발자 안개 토글
P 일시정지 / F5 저장 / F9 불러오기   Ctrl+D: 다크 모드   Esc: 선택 해제

· 빈 슬롯 지역이 남아 있으면 우하단 버튼이 [다음 지역]이 되어 수도부터 획득 순서대로 행동 메뉴를 엽니다.
· 정치 지도에서 진한 색 내 영토는 생산·행동(또는 생산 집중)이 진행 중인 지역입니다.
· 생산 집중: 건설·병력 생산을 하지 않는 지역의 인구 산출 +15% (행동 탭에서 켜고 끔).
· 좌상단 [국가 현황]: 재정·자원·특산물 재고, 지출 우선순위(드래그로 순서 변경).

[규칙 요약]
· 각 내 지역은 턴마다 슬롯 1개: 건물 착공, 유닛 생산, 인접 중립 지역 편입 중 하나.
· 비용은 매 턴 나눠서 내고, 자금이 모자라면 멈춥니다. 취소하면 낸 비용의 50% 환급.
· 자국 영토 안에서는 2칸, 그 밖은 1칸 이동. 해군은 항구↔해역↔해역↔상륙 턴당 2단계.
· 산출 Y = 30P + 150g(농장) + 150g(어장) + 1000g(공장)φ + 600g(은행) + 9000(랜드마크)
· 세수 = Y × 세율. 세율 10%보다 높으면 행복도가 떨어지고 낮으면 오릅니다.
· 실질 행복도 = 행복도 − 전쟁 피로도 − 징집 피로. 10 이상·식량 충분일 때 인구 증가, -50 이하부터 반란.
· 전쟁 피로도(0~200): 선전포고 +15(당하면 +10), 전쟁 중 턴당 +0.75(당하면 +0.5), 평시 턴당 1 회복.
· 점령한 적 지역은 4턴 저항(산출·생산 없음, 행복도 −100) 뒤 20턴에 걸쳐 회복, 36턴 동안 반란 없음.
· 전투: 방어측 피해 0.5rA²/(A+D), 공격측 피해 0.5rD²/(A+D). 방어선은 돌격 방어를 높입니다.
· 승리: 정복 / 경제(GDP > 나머지 합 ×2, 10턴) / 랜드마크(8도 + 수도, 하나 지을 때마다 다음 비용 ×1.2) / 시간 종료(기본 480턴, 지역·GDP·인구 점수 1위)"""


def draw_help(app):
    r = modal_frame(app, 820, 560, "도움말")
    app.gui.wrap((r.x + 24, r.y + 60), HELP, r.w - 48, 13)
    if app.gui.button((r.right - 144, r.bottom - 56, 120, 40), "닫기", "primary"):
        close(app)


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
    gui.text((r.x + 24, r.y + 52), f"한 지역에 최대 {C.SPECIALTY_MAX_TYPES}종, 종류별 턴당 1개 소비 · 공급 시작 +3 / 중단 −3 (1회)"
             " · 변경은 다음 턴 자원 단계에 반영", 12, t.muted)
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
        gui.text((x, y + 30), f"보유 특산물 {len(kinds)}종 · 재고 {sum(stock.values())}개", 13)
    else:
        rr = g.regions[rid]
        gui.text((x, y), f"{app.world.regions[rid].name}  (행복도 {rr.happy:+.1f}, 실질 {g.eff_happy(rr):+.1f})", 16,
                 weight="bold")
        y += 30
        gui.text((x, y), "종류", 12, t.muted)
        gui.text((x + 170, y), "재고/생산", 12, t.muted)
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
                          tooltip="이 지역에 우선 공급"):
                ok, msg = g.set_specialty(pid, rid, k, "auto" if k in rr.spec_pin else "pin")
                if not ok:
                    app.toast(msg, t.bad)
            if gui.button((bx + 58, yy + 2, 54, 26), "제외", size=11, selected=k in rr.spec_block,
                          tooltip="이 지역에는 공급하지 않음", color=t.bad):
                g.set_specialty(pid, rid, k, "auto" if k in rr.spec_block else "block")
            if gui.button((bx + 116, yy + 2, 54, 26), "자동", size=11, tooltip="수동 지정 해제"):
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
