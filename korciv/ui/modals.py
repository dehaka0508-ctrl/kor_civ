"""설정 화면과 모달: 정치체제, 반란, 조약 제안, 외교, 연말 랭킹, 로그, 도움말, 게임 종료."""
from __future__ import annotations

import random

import pygame

from .. import config as C
from .. import diplomacy as D
from ..leaders import GOVERNMENTS, LEADERS, LEADER_BY_KEY
from ..state import NEUTRAL, Settings
from .theme import hex2rgb, mix


class SetupState:
    def __init__(self):
        self.name = "대한"
        self.leader = "sejong"
        self.custom_name = ""
        self.n_enemies = 4
        self.difficulty = 2
        self.fog = 1
        self.victories = {k: True for k in C.VICTORY_TYPES}
        self.start = None
        self.ai_leaders = []          # 빈 칸은 무작위
        self.seed = ""


def modal_frame(app, w, h, title=None):
    sw, sh = app.screen.get_size()
    dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 90))
    app.screen.blit(dim, (0, 0))
    r = pygame.Rect(0, 0, w, h)
    r.center = (sw // 2, sh // 2)
    app.gui.panel(r, radius=12)
    if title:
        app.gui.text((r.x + 24, r.y + 20), title, 20, weight="bold")
    return r


# ------------------------------------------------------------------ 게임 설정
def draw_setup(app):
    gui = app.gui
    t = app.theme
    s = app.setup
    sw, sh = app.screen.get_size()
    r = pygame.Rect(0, 0, 1180, 760)
    r.center = (sw // 2, sh // 2)
    gui.panel(r, radius=14)
    gui.text((r.x + 32, r.y + 24), "한반도 시군구 문명", 28, weight="bold")
    gui.text((r.x + 34, r.y + 64), "424개 시군구 · 1턴 = 1주 · 2026년 1월 1주 시작", 14, t.muted)
    # 좌측: 국가·지도자
    x, y = r.x + 32, r.y + 104
    gui.text((x, y), "국가 이름", 13, t.muted, "semibold")
    s.name = gui.text_input((x, y + 22, 260, 34), "name", s.name, max_len=10)
    y += 70
    gui.text((x, y), "내 지도자", 13, t.muted, "semibold")
    y += 24
    cols, bw, bh = 4, 150, 34
    for i, l in enumerate(LEADERS):
        cx = x + (i % cols) * (bw + 6)
        cy = y + (i // cols) * (bh + 6)
        tip = f"{l['name']} (호전성 {l['aggr']})\n버프 {l['buff'][0]}: {l['buff'][1]}\n디버프 {l['debuff'][0]}: {l['debuff'][1]}"
        if gui.button((cx, cy, bw, bh), l["name"], selected=s.leader == l["key"], size=13, tooltip=tip):
            s.leader = l["key"]
    y += 6 * (bh + 6) + 8
    lead = LEADER_BY_KEY[s.leader]
    if s.leader == "custom":
        gui.text((x, y + 8), "지도자 이름", 13, t.muted)
        s.custom_name = gui.text_input((x + 90, y, 200, 32), "custom", s.custom_name, max_len=10)
        y += 40
    gui.text((x, y), f"버프 · {lead['buff'][0]}: {lead['buff'][1]}", 13, t.good)
    gui.text((x, y + 22), f"디버프 · {lead['debuff'][0]}: {lead['debuff'][1]}", 13, t.bad)
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
        s.victories[k] = gui.checkbox((x2 + (i % 2) * 230, y + (i // 2) * 28, 220, 24), nm, s.victories[k])
    y += 64
    gui.text((x2, y), "시작 구역", 13, t.muted, "semibold")
    st_name = app.world.regions[s.start].name if s.start else "무작위"
    gui.text((x2 + 80, y), st_name, 14, weight="semibold")
    if gui.button((x2 + 250, y - 6, 110, 30), "지도에서 선택"):
        app.scene = "pick_start"
        app.map.z = 1.0
        app.map.cx, app.map.cy = 280, 520
        app.map.invalidate()
    if gui.button((x2 + 366, y - 6, 100, 30), "무작위"):
        s.start = None
    y += 40
    gui.text((x2, y), "적 지도자 (클릭해 바꾸기, 빈 칸은 무작위)", 13, t.muted, "semibold")
    y += 24
    while len(s.ai_leaders) < s.n_enemies:
        s.ai_leaders.append(None)
    keys = [None] + [l["key"] for l in LEADERS if l["key"] != "custom"]
    for i in range(s.n_enemies):
        cx = x2 + (i % 3) * 158
        cy = y + (i // 3) * 36
        cur = s.ai_leaders[i]
        lab = LEADER_BY_KEY[cur]["name"] if cur else "무작위"
        if gui.button((cx, cy, 152, 30), f"AI {i+1}: {lab}", size=12):
            s.ai_leaders[i] = keys[(keys.index(cur) + 1) % len(keys)]
    y += 3 * 36 + 8
    gui.text((x2, y + 8), "시드", 13, t.muted)
    s.seed = gui.text_input((x2 + 40, y, 120, 32), "seed", s.seed, max_len=9)
    # 하단 버튼
    if gui.button((r.right - 360, r.bottom - 64, 150, 44), "불러오기"):
        app.load()
    if gui.button((r.right - 196, r.bottom - 64, 170, 44), "게임 시작", "primary", size=16, weight="bold",
                  enabled=any(s.victories.values())):
        seed = int(s.seed) if s.seed.strip().isdigit() else random.randrange(1_000_000)
        settings = Settings(
            n_enemies=s.n_enemies, difficulty=s.difficulty, fog=s.fog,
            victories=tuple(k for k, v in s.victories.items() if v), player_leader=s.leader,
            player_leader_name=s.custom_name.strip() if s.leader == "custom" else "",
            player_name=s.name.strip() or "대한", player_start=s.start,
            ai_leaders=[k for k in s.ai_leaders[: s.n_enemies] if k], seed=seed)
        app.start_game(settings)
    gui.text((r.x + 32, r.bottom - 44), "조작: 좌클릭 선택 · 우클릭 명령 · 휠 확대 · 드래그 이동 · Enter 턴 종료 · F1 도움말",
             12, t.muted)


# ------------------------------------------------------------------ 정치체제
def draw_government(app):
    gui = app.gui
    t = app.theme
    r = modal_frame(app, 760, 600, "정치체제를 고르세요")
    gui.text((r.x + 24, r.y + 52), "지도자 효과와 곱으로 합산됩니다. 한 번 정하면 바꿀 수 없습니다.", 13, t.muted)
    y = r.y + 84
    for gdef in GOVERNMENTS:
        row = pygame.Rect(r.x + 24, y, r.w - 48, 64)
        hov = gui.hover(row)
        pygame.draw.rect(app.screen, t.panel_alt if hov else t.panel, row, border_radius=8)
        pygame.draw.rect(app.screen, t.border, row, 1, border_radius=8)
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
            app.toast(f"{gdef['name']}을(를) 채택했습니다. 첫 턴입니다 — 우측 행동 탭에서 슬롯을 지정하세요.")
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
    elif name == "landmark_name":
        draw_landmark_name(app)
    elif name == "specialty":
        draw_specialty(app)


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
    gui.text((r.x + 24, r.y + 56), f"{info.name} · 행복도 {rr.happy:+.1f} · 인구 {rr.pop:.1f}만", 15, weight="semibold")
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
    pygame.draw.rect(app.screen, hex2rgb(f.color), (r.x + 24, r.y + 62, 12, 16), border_radius=3)
    gui.text((r.x + 44, r.y + 60), f"{f.name}({f.leader_name})이(가) {D.TREATY_NAMES[kind]}을(를) 제안합니다.", 15,
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
    money_max = max(0, int(f.money))
    gui.text((x, y + 6), "돈", 13)
    side["money"] = gui.stepper((x + 70, y, w - 70, 28), min(side["money"], money_max), 0, money_max, 100, 1000)
    y += 34
    for res in ("food", "oil", "coal", "elec"):
        mx = int(f.res.get(res, 0))
        gui.text((x, y + 6), C.RESOURCE_NAMES[res], 13)
        side[res] = gui.stepper((x + 70, y, w - 70, 28), min(side[res], mx), 0, mx, 1, 10)
        y += 34
    sp = int(sum(f.specialty.values()))
    gui.text((x, y + 6), "특산물", 13)
    side["specialty"] = gui.stepper((x + 70, y, w - 70, 28), min(side["specialty"], sp), 0, sp, 1, 10)
    y += 36
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
    pygame.draw.rect(app.screen, hex2rgb(other.color), (r.x + 24, r.y + 22, 14, 22), border_radius=3)
    from ..leaders import GOV_BY_KEY
    gui.text((r.x + 46, r.y + 18), f"{other.name}", 20, weight="bold")
    gui.text((r.x + 46, r.y + 46), f"{other.leader_name} · {GOV_BY_KEY.get(other.gov, {}).get('name', '')} · "
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
        pygame.draw.rect(app.screen, col, cell, border_radius=15)
        gui.text(cell.center, nm, 12, (255, 255, 255) if active or st == -1 else t.muted, "semibold", anchor="center")
    status = "전쟁 중" if st == -1 else D.STAGE_NAMES[st]
    gui.text((sx, r.y + 58), f"상대의 우호도 {op:+.1f} · 현재 {status}"
             + (f" · 전쟁 점수 {D.war_score(g, pid, fid):+.1f}" if st == -1 else ""), 13,
             t.bad if st == -1 else t.text)
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
    pygame.draw.line(app.screen, t.border, (r.x + 24, y - 10), (r.right - 24, y - 10))
    gui.text((r.x + 24, y), "조약·전쟁", 14, weight="bold")
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
            if gui.button((r.x + 24 + i * (bw + 8), y, bw, 40), "불가침 파기", "danger",
                          tooltip="모든 세력의 우호도 -30"):
                ok, msg = D.break_nonaggr(g, pid, fid)
                app.toast(msg or "불가침조약을 파기했습니다.", t.bad)
            i += 1
        elif p in g.dip.alliance:
            if gui.button((r.x + 24 + i * (bw + 8), y, bw, 40), "동맹 탈퇴", "danger"):
                D.leave_alliance(g, pid, fid)
            i += 1
        can_war = not D.has_nonaggr(g, pid, fid)
        if gui.button((r.x + 24 + i * (bw + 8), y, bw, 40), "선전포고", "danger", enabled=can_war,
                      tooltip="전 지역 행복도 -10, 상대 우호도 -100" if can_war else "불가침·동맹 중에는 먼저 파기"):
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
        pygame.draw.rect(app.screen, hex2rgb(g.factions[row["fid"]].color), (x0, y + 6, 10, 16), border_radius=3)
        me = row["fid"] == g.player_id
        gui.text((x0 + 16, y + 4), row["name"] + (" (나)" if me else ""), 14, weight="bold" if me else "regular")
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
    area = pygame.Rect(r.x + 16, r.y + 60, r.w - 32, r.h - 130)
    off = gui.begin_scroll("log", area, len(evs) * 24)
    y = area.y - off
    for e in evs:
        col = {"battle": t.bad, "war": t.bad, "rebel": t.warn, "famine": t.warn, "captured": t.good}.get(e["kind"], t.text)
        gui.text((area.x + 8, y), f"턴 {e['turn']}", 12, t.muted)
        gui.text((area.x + 64, y), e["text"], 13, col, max_w=area.w - 80)
        y += 24
    gui.end_scroll("log", area, len(evs) * 24)
    if gui.button((r.right - 144, r.bottom - 56, 120, 40), "닫기", "primary"):
        close(app)


HELP = """[조작]
좌클릭: 구역·해역 선택   우클릭: 선택한 부대의 이동·공격 대상 지정
마우스 휠 / + -: 확대·축소   드래그 / 방향키: 지도 이동   더블클릭: 확대
Enter: 턴 종료   Tab: 빈 슬롯 순회   A: 빈 슬롯 자동 지정   1~7: 지도 모드   F2: 개발자 안개 토글
F5 저장 / F9 불러오기   Ctrl+D: 다크 모드   Esc: 선택 해제

[규칙 요약]
· 각 내 지역은 턴마다 슬롯 1개: 건물 착공, 유닛 생산, 인접 중립 지역 편입 중 하나.
· 비용은 매 턴 나눠서 내고, 자금이 모자라면 멈춥니다. 취소하면 낸 비용의 50% 환급.
· 자국 영토 안에서는 2칸, 그 밖은 1칸 이동. 해군은 항구↔해역↔해역↔상륙 턴당 2단계.
· 산출 Y = 30P + 150g(농장) + 150g(어장) + 1000g(공장)φ + 600g(은행) + 9000(랜드마크)
· 세수 = Y × 세율. 세율 10%보다 높으면 행복도가 떨어지고 낮으면 오릅니다.
· 행복도 10 이상·식량 충분일 때 인구 증가, -50 이하부터 반란 확률 상승.
· 전투: 방어측 피해 0.5rA²/(A+D), 공격측 피해 0.5rD²/(A+D). 방어선은 돌격 방어를 높입니다.
· 승리: 정복 / 경제(GDP > 나머지 합 ×2, 10턴) / 평화(전원 연합 24턴) / 랜드마크(8도 + 수도)"""


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
        app.scene = "setup"
        app.reset_ui()
    if gui.button((r.right - 264, r.bottom - 64, 240, 44), "지도 계속 보기"):
        close(app)


# ------------------------------------------------------------------ 랜드마크 이름
def draw_landmark_name(app):
    g = app.game
    gui = app.gui
    t = app.theme
    rid = app.modal[1]
    r = modal_frame(app, 520, 300, "랜드마크 이름 짓기")
    info = app.world.regions[rid]
    turns = g.mods(g.player_id).value("landmark_turns", C.LANDMARK_TURNS)
    gui.text((r.x + 24, r.y + 56), f"{info.name} · {turns}턴 동안 매 턴 {C.LANDMARK_COST_PER_TURN:,} 지불", 13, t.muted)
    gui.text((r.x + 24, r.y + 92), "이름", 13, t.muted, "semibold")
    app.lm_name = gui.text_input((r.x + 24, r.y + 114, r.w - 48, 38), "lm_name", app.lm_name, size=15, max_len=16)
    gui.text((r.x + 24, r.y + 160), f"비워 두면 「{g.default_landmark_name(rid)}」로 짓습니다.", 12, t.muted)
    if gui.button((r.x + 24, r.bottom - 64, 220, 44), "착공", "primary"):
        gui.focus = None
        ok, msg = g.start_project(g.player_id, rid, "landmark", "landmark", name=app.lm_name)
        app.toast(msg, None if ok else t.bad)
        close(app)
        app.changed()
    if gui.button((r.right - 244, r.bottom - 64, 220, 44), "취소"):
        gui.focus = None
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
        sp = app.world.regions[rr.id].specialty
        if sp and rr.b["specialty"]:
            prod[sp] = prod.get(sp, 0) + rr.b["specialty"]
    used = {}
    for rr in g.regions_of(pid):
        for k in rr.supplied:
            used[k] = used.get(k, 0) + 1
    # 좌: 지역 목록 (행복도 낮은 순)
    regs = sorted(g.regions_of(pid), key=lambda rr: rr.happy)
    left = pygame.Rect(r.x + 16, r.y + 80, 430, r.h - 150)
    pygame.draw.rect(app.screen, t.panel_alt, left, border_radius=8)
    off = gui.begin_scroll("spec_regions", left, len(regs) * 34 + 8)
    y = left.y + 4 - off
    for rr in regs:
        row = pygame.Rect(left.x + 4, y, left.w - 12, 30)
        sel = app.spec_sel == rr.id
        if sel:
            pygame.draw.rect(app.screen, t.panel, row, border_radius=6)
            pygame.draw.rect(app.screen, t.accent, row, 1, border_radius=6)
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
        gui.text((x, y), f"{app.world.regions[rid].name}  (행복도 {rr.happy:+.1f})", 16, weight="bold")
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
