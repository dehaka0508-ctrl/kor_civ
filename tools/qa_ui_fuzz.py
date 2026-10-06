"""UI 퍼저: 창 없이(dummy) 게임 화면을 무작위로 클릭·드래그·휠·키 입력해 예외를 찾는다(개발용).

  python tools/qa_ui_fuzz.py --frames 20000 --seed 1
세이브는 임시 폴더에 쓴다. 문제는 처음 한 번만 자세히 출력하고 마지막에 요약한다.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
import time
import traceback
from collections import Counter

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame                                      # noqa: E402

from korciv.state import Settings                  # noqa: E402
from korciv.ui import app as appmod                # noqa: E402
from korciv.ui import modals, panels               # noqa: E402
from korciv.ui.gui import UI                       # noqa: E402

KEYS = [pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_a, pygame.K_p, pygame.K_1, pygame.K_2, pygame.K_3,
        pygame.K_4, pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_F1, pygame.K_F2, pygame.K_F5, pygame.K_F9,
        pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN, pygame.K_EQUALS, pygame.K_MINUS,
        pygame.K_TAB, pygame.K_BACKSPACE, pygame.K_SPACE, pygame.K_n, pygame.K_s, pygame.K_q, pygame.K_DELETE]

PROBLEMS = Counter()
EXAMPLES = {}


def report(tag, msg):
    PROBLEMS[tag] += 1
    if tag not in EXAMPLES:
        EXAMPLES[tag] = msg
        print("[문제]", tag, "\n", msg, flush=True)


class Mouse:
    pos = (0, 0)
    pressed = (False, False, False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--size", default="1280x800")
    ap.add_argument("--warm", type=int, default=0, help="퍼징 전에 AI가 플레이어 대신 진행할 턴 수(후반 상태 점검)")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    appmod.SAVE_DIR = tempfile.mkdtemp(prefix="korciv_qa_")
    pygame.mouse.get_pos = lambda: Mouse.pos
    pygame.mouse.get_pressed = lambda num_buttons=3: Mouse.pressed
    w, h = (int(x) for x in a.size.split("x"))
    app = appmod.App(width=w, height=h)
    held = set()
    if a.warm:
        warm_up(app, a.warm, rng)
        globals()["RESTART_P"] = 0.01
    pygame.key.get_pressed = lambda: type("P", (), {"__getitem__": lambda s, k: k in held})()
    sw, sh = app.window.get_size()
    pending_up = None
    slow = 0
    seen = Counter()
    t_start = time.time()
    for i in range(a.frames):
        events = []
        held.clear()
        if pending_up:
            Mouse.pressed = (False, False, False)
            events.append(pending_up)
            pending_up = None
        else:
            r = rng.random()
            if r < 0.55:                     # 클릭(UI 쪽에 더 자주)
                zone = rng.random()
                u = UI["u"]
                if zone < 0.35:
                    x, y = rng.uniform(0, 460 * u), rng.uniform(0, sh)          # 좌측 세로 탭·패널
                elif zone < 0.5:
                    x, y = rng.uniform(0, sw), rng.uniform(0, 60 * u)           # 상단 바
                elif zone < 0.62:
                    x, y = rng.uniform(0, sw), rng.uniform(sh - 90 * u, sh)     # 하단
                elif zone < 0.8:
                    x, y = rng.uniform(sw * 0.2, sw * 0.8), rng.uniform(sh * 0.15, sh * 0.85)  # 가운데(모달)
                else:
                    x, y = rng.uniform(0, sw), rng.uniform(0, sh)
                Mouse.pos = (int(x), int(y))
                btn = 1 if rng.random() < 0.85 else 3
                Mouse.pressed = (btn == 1, False, btn == 3)
                events.append(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=btn, pos=Mouse.pos))
                pending_up = pygame.event.Event(pygame.MOUSEBUTTONUP, button=btn, pos=Mouse.pos)
            elif r < 0.65:                   # 드래그 이동
                Mouse.pressed = (True, False, False)
                Mouse.pos = (max(0, min(sw - 1, Mouse.pos[0] + rng.randint(-120, 120))),
                             max(0, min(sh - 1, Mouse.pos[1] + rng.randint(-120, 120))))
                events.append(pygame.event.Event(pygame.MOUSEMOTION, pos=Mouse.pos, rel=(0, 0), buttons=(1, 0, 0)))
            elif r < 0.72:
                events.append(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=rng.choice([-1, 1, 2, -3]), flipped=False))
            elif r < 0.85:
                k = rng.choice(KEYS)
                events.append(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
            elif r < 0.9:
                held.add(rng.choice([pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN]))
            elif r < 0.93:
                events.append(pygame.event.Event(pygame.TEXTINPUT, text=rng.choice(["가", "a", "9", "!", "한반도"])))
            else:
                force_state(app, rng)
        app.gui.begin(events)
        t0 = time.time()
        try:
            app.frame()
        except Exception:
            report(f"예외: {traceback.format_exc().strip().splitlines()[-1][:120]}",
                   f"frame={i} scene={app.scene} modal={app.modal} left={app.left_tab}/{app.tab} "
                   f"sel={app.sel}\n{traceback.format_exc()}")
            recover(app)
        dt = time.time() - t0
        seen[(app.scene, app.active_modal() if app.game else (app.modal or [None])[0],
              app.left_tab if app.left_open else "-")] += 1
        if dt > 1.5:
            slow += 1
            report("느린 프레임(>1.5초)", f"frame={i} {dt:.1f}s scene={app.scene} modal={app.modal}")
        if app.gui._clip_stack:
            report("clip 누수", f"frame={i} scene={app.scene} left={app.left_tab}/{app.tab} modal={app.modal}")
            app.gui._clip_stack.clear()
            app.screen.set_clip(None)
        if not app.running:
            report("앱 종료됨", f"frame={i}")
            app.running = True
        if i % 2000 == 0:
            g = app.game
            print(f"frame {i} scene={app.scene} turn={g.turn if g else '-'} {time.time() - t_start:.0f}s", flush=True)
    print("== 방문한 화면(장면, 모달, 좌측 탭) ==")
    for k, v in seen.most_common(40):
        print(v, k)
    print("== 요약 ==")
    for k, v in PROBLEMS.most_common():
        print(f"{v}회 · {k}")
    if not PROBLEMS:
        print("문제 없음")


def recover(app):
    app.modal = None
    app.qty = None
    app.ctx_menu = None
    if app.game:
        app.game.pending_rebellions.clear()
        app.game.pending_proposals.clear()
    app.gui._clip_stack.clear()
    app.screen.set_clip(None)


RESTART_P = 0.12


def warm_up(app, turns, rng):
    """플레이어도 AI가 조종하게 해서 turns 턴 진행한 뒤 다시 플레이어에게 넘긴다."""
    app.start_game(Settings(seed=rng.randrange(10 ** 6), n_enemies=rng.randint(4, 9), fog=1))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    g.player.is_ai = True
    for _ in range(turns):
        if g.game_over:
            break
        g.end_turn()
    g.player.is_ai = False
    g.pending_rebellions.clear()
    g.pending_proposals.clear()
    print(f"워밍업 {g.turn}턴, 생존 {sum(f.alive for f in g.factions)}/{len(g.factions)}, 플레이어 생존 {g.player.alive}",
          flush=True)


def force_state(app, rng):
    """무작위 입력만으로는 닿기 어려운 화면 상태로 바로 옮긴다."""
    g = app.game
    r = rng.random()
    if r < 0.05 or (g is None and r < 0.5):
        app.scene = rng.choice(["title", "setup", "pick_start"])
        if app.scene == "setup" and rng.random() < 0.4:
            app.setup.flag_draft = dict(app.setup.flag)
        elif app.scene == "setup" and rng.random() < 0.4:
            app.setup.ai_pick = rng.randrange(max(1, app.setup.n_enemies))
        return
    if g is None or r < RESTART_P:
        app.start_game(Settings(seed=rng.randrange(10 ** 6), n_enemies=rng.randint(1, 9), fog=rng.choice([0, 1, 2]),
                                player_leader=rng.choice(["sej", "cus", "yis", "kim", "ito"]),
                                player_leader_name="큐에이"))
        if rng.random() < 0.7:
            app.game.set_player_government(rng.choice(["presidential", "absolute", "socialist", "philosopher"]))
            app.scene = "main"
        return
    if app.scene not in ("main", "government"):
        app.scene = "main" if g.setup_done else "government"
    k = rng.random()
    pid = g.player_id
    if k < 0.3:
        app.left_open = True
        app.left_tab = rng.choice([t[0] for t in panels.SIDE_TABS] + ["region"] * 3)
        if app.left_tab == "region":
            node = rng.choice(list(g.regions) + list(app.world.seas))
            app.select(node)
            app.left_open = True
            app.left_tab = "region"
            app.tab = rng.choice(["action", "army", "info"])
        if app.left_tab == "diplo":
            others = [f.id for f in g.factions if f.alive and f.id != pid]
            app.dip_view = rng.choice(others + [None]) if others else None
    elif k < 0.45:
        others = [f.id for f in g.factions if f.alive and f.id != pid]
        if others:
            app.open_diplomacy(rng.choice(others))
    elif k < 0.6:
        app.modal = rng.choice([("help", None), ("log", None), ("ranking", None), ("pause", None),
                                ("specialty", None), ("gameover", None), ("saveslots", "save"),
                                ("saveslots", "load"), ("saveslots", "save_exit")])
        if app.modal[0] == "saveslots":
            app.open_slots(app.modal[1])
        if app.modal[0] == "specialty":
            mine = [r.id for r in g.regions_of(pid)]
            app.spec_sel = rng.choice(mine) if mine else None
    elif k < 0.7:
        mine = [r.id for r in g.regions_of(pid)]
        if mine:
            rid = rng.choice(mine)
            app.lm_name = g.default_landmark_name(rid)
            app.modal = ("landmark_name", rid)
    elif k < 0.8:
        mine = [r.id for r in g.regions_of(pid)]
        if mine and rng.random() < 0.5:
            g.pending_rebellions.append(rng.choice(mine))
        else:
            others = [f.id for f in g.factions if f.alive and f.id != pid]
            if others:
                g.pending_proposals.append({"from": rng.choice(others),
                                            "kind": rng.choice(["nonaggr", "passage", "alliance", "coalition", "peace"])})
    elif k < 0.9:
        for _ in range(rng.randint(1, 4)):
            g.pending_rebellions.clear()
            g.pending_proposals.clear()
            app.end_turn()
    else:
        mine = [a for a in g.armies.values() if a.owner == pid]
        if mine:
            a = rng.choice(mine)
            app.select(a.loc)
            app.sel_army = a.id
            app.left_open, app.left_tab, app.tab = True, "region", "army"
            near = list(app.world.node_neighbors(a.loc))
            if near and rng.random() < 0.5:
                app.right_click(rng.choice(near), (300, 300))


if __name__ == "__main__":
    main()
